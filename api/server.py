"""
Threaded HTTP REST API server for the AI agent capability registry.

Usage:
    from api.server import run_server
    run_server(port=8080)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agents.examples import CODE_AGENT, FINANCE_AGENT, SEARCH_AGENT
from api.auth import ApiKeyAuth
from api.routes import match_route
from registry.obsolescence import ObsolescenceTracker
from registry.renderer import render_card_html
from registry.schema import AgentCard, TrustLevel
from registry.sku import SKURegistry, generate_sku
from registry.store import SQLiteStore
from verifier.scheduler import VerificationScheduler
from verifier.suite import VerificationSuite

# ---------------------------------------------------------------------------
# Shared state (module-level so the handler class can access it)
# ---------------------------------------------------------------------------

_registry: dict[str, AgentCard] = {}
_scheduler: VerificationScheduler | None = None
_registry_lock = threading.Lock()
_sku_registry = SKURegistry()
_store: SQLiteStore | None = None
_obsolescence: ObsolescenceTracker | None = None
_auth = ApiKeyAuth()

MAX_BODY_BYTES = 1024 * 1024  # 1 MiB


def _cors_origin(request_origin: str | None) -> str | None:
    """Resolve the Access-Control-Allow-Origin value from the configured
    allowlist (REGISTRY_CORS_ORIGINS, comma-separated; default '*')."""
    allowed = os.environ.get("REGISTRY_CORS_ORIGINS", "*")
    if allowed == "*":
        return "*"
    origins = {o.strip() for o in allowed.split(",") if o.strip()}
    if request_origin and request_origin in origins:
        return request_origin
    return None


def _init_state(db_path: str | None = None) -> None:
    """Load state from the SQLite store; seed the three example agents only
    when the database is empty (first boot)."""
    global _registry, _scheduler, _store, _obsolescence, _auth
    _auth = ApiKeyAuth()
    _store = SQLiteStore(db_path)
    obs_path = os.path.join(os.path.dirname(_store.path) or ".", "obsolescence.json")
    _obsolescence = ObsolescenceTracker(persist_path=obs_path)

    with _registry_lock:
        _registry.clear()
        if _store.is_empty():
            for card in (CODE_AGENT, SEARCH_AGENT, FINANCE_AGENT):
                _registry[card.agent_id] = card
                sku = _sku_registry.register(card)
                _store.save_agent(card)
                _store.save_sku(sku)
        else:
            _registry.update(_store.load_agents())
            _sku_registry.load_state(_store.load_skus(), _store.load_aliases())
    suite = VerificationSuite()
    _scheduler = VerificationScheduler(suite=suite, registry=_registry)


def _persist_agent_sku(agent_id: str) -> None:
    """Write-through: persist an agent's SKU and the current alias table.
    Caller must NOT hold _registry_lock requirements — store has its own lock."""
    if _store is None:
        return
    sku = _sku_registry.get_by_agent(agent_id)
    if sku is not None:
        _store.save_sku(sku)
    for alias, target in _sku_registry.aliases().items():
        _store.save_alias(alias, target)
        _store.delete_sku(alias)  # aliased codes are no longer live rows


# ---------------------------------------------------------------------------
# ConsolidationEngine (minimal in-process implementation)
# ---------------------------------------------------------------------------

MERGED_TAG = "MERGED"
OBSOLETE_TTL_MULTIPLIER = 3  # agent is "obsolete" if age > 3× TTL


def _is_obsolete(card: AgentCard) -> bool:
    """Flag a card obsolete if it has been stale for 3× its TTL."""
    if card.trust_level.value == MERGED_TAG:
        return True
    if card.verification_date is None:
        return False
    now = datetime.now(timezone.utc)
    vd = card.verification_date
    if vd.tzinfo is None:
        vd = vd.replace(tzinfo=timezone.utc)
    age_seconds = (now - vd).total_seconds()
    return age_seconds > card.ttl_seconds * OBSOLETE_TTL_MULTIPLIER


def _run_consolidation(dry_run: bool = False) -> dict[str, Any]:
    """Identify (and optionally remove) obsolete agents. Returns a report dict."""
    with _registry_lock:
        obsolete_ids = [
            aid for aid, card in _registry.items() if _is_obsolete(card)
        ]
        removed: list[str] = []
        if not dry_run:
            for aid in obsolete_ids:
                del _registry[aid]
                _sku_registry.deactivate(aid)
                removed.append(aid)

    if _obsolescence is not None:
        for aid in obsolete_ids:
            if not _obsolescence.is_flagged(aid):
                _obsolescence.flag(aid, reason="STALE", notes="flagged by consolidation pass")
        for aid in removed:
            _obsolescence.confirm_removal(aid)
    for aid in removed:
        if _store is not None:
            _store.delete_agent(aid)
        _persist_agent_sku(aid)

    return {
        "dry_run": dry_run,
        "obsolete_count": len(obsolete_ids),
        "obsolete_ids": obsolete_ids,
        "removed_ids": removed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _json_response(handler: "AgentRegistryHandler", status: int, data: Any) -> None:
    body = json.dumps(data, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    origin = _cors_origin(handler.headers.get("Origin"))
    if origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: "AgentRegistryHandler", status: int, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    origin = _cors_origin(handler.headers.get("Origin"))
    if origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: "AgentRegistryHandler", status: int, message: str) -> None:
    _json_response(handler, status, {"error": message})


def _read_json_body(handler: "AgentRegistryHandler") -> dict[str, Any] | None:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    if length > MAX_BODY_BYTES:
        _error(handler, 413, f"Body too large (max {MAX_BODY_BYTES} bytes)")
        return None
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        _error(handler, 400, f"Invalid JSON body: {exc}")
        return None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def _handle_list_agents(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    with _registry_lock:
        cards = [c.to_dict() for c in _registry.values()]
    _json_response(handler, 200, cards)


def _handle_get_agent(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    agent_id = params["id"]
    with _registry_lock:
        card = _registry.get(agent_id)
    if card is None:
        _error(handler, 404, f"Agent '{agent_id}' not found")
        return
    _json_response(handler, 200, card.to_dict())


def _handle_get_agent_html(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    agent_id = params["id"]
    with _registry_lock:
        card = _registry.get(agent_id)
    if card is None:
        _error(handler, 404, f"Agent '{agent_id}' not found")
        return
    _html_response(handler, 200, render_card_html(card))


def _handle_register_agent(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    body = _read_json_body(handler)
    if body is None:
        return
    try:
        card = AgentCard.from_dict(body)
    except Exception as exc:
        _error(handler, 422, f"Invalid agent card: {exc}")
        return
    if not card.agent_id:
        _error(handler, 422, "Field 'agent_id' is required")
        return
    with _registry_lock:
        already_exists = card.agent_id in _registry
        _registry[card.agent_id] = card
        if _scheduler is not None:
            _scheduler.add_agent(card)
        _sku_registry.register(card)
    if _store is not None:
        _store.save_agent(card)
    _persist_agent_sku(card.agent_id)
    status = 200 if already_exists else 201
    _json_response(handler, status, card.to_dict())


def _handle_delete_agent(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    agent_id = params["id"]
    with _registry_lock:
        card = _registry.pop(agent_id, None)
        if card is not None:
            _sku_registry.deactivate(agent_id)
    if card is None:
        _error(handler, 404, f"Agent '{agent_id}' not found")
        return
    if _store is not None:
        _store.delete_agent(agent_id)
    _persist_agent_sku(agent_id)
    _json_response(handler, 200, {"deleted": agent_id})


def _handle_list_obsolete(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    with _registry_lock:
        obsolete = [
            c.to_dict() for c in _registry.values() if _is_obsolete(c)
        ]
    _json_response(handler, 200, obsolete)


def _handle_consolidate(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    dry_run_param = qs.get("dry_run", ["false"])[0].lower()
    dry_run = dry_run_param in ("true", "1", "yes")
    report = _run_consolidation(dry_run=dry_run)
    _json_response(handler, 200, report)


def _handle_refresh(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    """Trigger async re-verification of all stale agents in a background thread."""
    if _scheduler is None:
        _error(handler, 503, "Scheduler not initialised")
        return

    def _run() -> None:
        asyncio.run(_scheduler.check_and_refresh())

    t = threading.Thread(target=_run, daemon=True, name="refresh-worker")
    t.start()
    _json_response(handler, 202, {"status": "refresh started", "thread": t.name})


def _handle_verify_agent(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    agent_id = params["id"]
    with _registry_lock:
        card = _registry.get(agent_id)
    if card is None:
        _error(handler, 404, f"Agent '{agent_id}' not found")
        return
    if _scheduler is None:
        _error(handler, 503, "Scheduler not initialised")
        return

    results = asyncio.run(_scheduler.suite.run_all(card))
    updated = _scheduler.suite.update_card_trust(card, results)
    with _registry_lock:
        _registry[updated.agent_id] = updated
        _sku_registry.register(updated)  # refreshes tier; sku_code stays stable

    if _store is not None:
        _store.save_agent(updated)
        if _scheduler.suite.history:
            _store.add_verification(agent_id, _scheduler.suite.history[-1])
    _persist_agent_sku(agent_id)

    _json_response(handler, 200, {
        "agent_id": agent_id,
        "trust_level": updated.trust_level.value,
        "verification_date": (
            updated.verification_date.isoformat()
            if updated.verification_date else None
        ),
        "results": [r.to_dict() for r in results],
    })


def _handle_merge_agents(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    body = _read_json_body(handler)
    if body is None:
        return

    source_ids: list[str] = body.get("source_ids", [])
    new_id: str = body.get("new_id", "")
    new_name: str = body.get("new_name", "")
    new_description: str = body.get("new_description", "")

    if not source_ids:
        _error(handler, 422, "Field 'source_ids' must be a non-empty list")
        return
    if not new_id:
        _error(handler, 422, "Field 'new_id' is required")
        return
    if not new_name:
        _error(handler, 422, "Field 'new_name' is required")
        return

    with _registry_lock:
        missing = [sid for sid in source_ids if sid not in _registry]
        if missing:
            _error(handler, 404, f"Agents not found: {missing}")
            return

        # Collect all skills from source agents (deduplicated by name)
        merged_skills: dict[str, Any] = {}
        provider_parts: list[str] = []
        endpoints: list[str] = []

        for sid in source_ids:
            src = _registry[sid]
            for skill in src.skills:
                if skill.name not in merged_skills:
                    merged_skills[skill.name] = skill
            if src.provider and src.provider not in provider_parts:
                provider_parts.append(src.provider)
            if src.endpoint and src.endpoint not in endpoints:
                endpoints.append(src.endpoint)

        # Build merged card
        merged_card = AgentCard(
            agent_id=new_id,
            name=new_name,
            version="1.0.0",
            description=new_description,
            provider=", ".join(provider_parts),
            endpoint=endpoints[0] if endpoints else "",
            skills=list(merged_skills.values()),
            trust_level=TrustLevel.UNVERIFIED,
        )
        _registry[new_id] = merged_card
        _sku_registry.register(merged_card)
        merged_sku_code = _sku_registry.get_by_agent(new_id)
        merged_sku_str = merged_sku_code.sku_code if merged_sku_code else None

        # Mark sources as MERGED by setting a special trust level value
        # We use a sentinel description tag since TrustLevel enum is fixed.
        # To signal MERGED we set trust_level to UNVERIFIED and append to description.
        for sid in source_ids:
            src = _registry[sid]
            src.description = f"[MERGED into {new_id}] " + src.description
            src.trust_level = TrustLevel.UNVERIFIED
            # Remove from active registry so they don't appear in normal listing
            # but keep a copy with the merged tag by re-storing
            _registry[sid] = src
            _sku_registry.deactivate(sid, superseded_by_sku=merged_sku_str)

    if _store is not None:
        _store.save_agent(merged_card)
        for sid in source_ids:
            _store.save_agent(_registry[sid])
            _persist_agent_sku(sid)
    _persist_agent_sku(new_id)
    if _obsolescence is not None:
        for sid in source_ids:
            _obsolescence.flag(sid, reason="MERGED", superseded_by=new_id)

    _json_response(handler, 201, {
        "merged_id": new_id,
        "source_ids": source_ids,
        "card": merged_card.to_dict(),
    })


# ---------------------------------------------------------------------------
# SKU route handlers
# ---------------------------------------------------------------------------

def _handle_list_skus(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    skus = _sku_registry.list_active()
    _json_response(handler, 200, [s.to_dict() for s in skus])


def _handle_get_sku(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    sku_code = params["sku_code"]
    sku, resolved_from = _sku_registry.resolve(sku_code)
    if sku is None:
        _error(handler, 404, f"SKU '{sku_code}' not found")
        return
    payload = sku.to_dict()
    if resolved_from:
        payload["resolved_from"] = resolved_from
    _json_response(handler, 200, payload)


def _handle_get_sku_agent(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    sku_code = params["sku_code"]
    sku = _sku_registry.get_by_sku(sku_code)
    if sku is None:
        _error(handler, 404, f"SKU '{sku_code}' not found")
        return
    with _registry_lock:
        card = _registry.get(sku.agent_id)
    if card is None:
        _error(handler, 404, f"Agent '{sku.agent_id}' not found in registry")
        return
    _json_response(handler, 200, card.to_dict())


def _handle_search_skus(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    query = qs.get("q", [""])[0]
    category = qs.get("category", [""])[0]
    tier = qs.get("tier", [""])[0]
    results = _sku_registry.search(query=query, category=category, tier=tier, active_only=True)
    _json_response(handler, 200, [s.to_dict() for s in results])


def _handle_sku_catalog(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    _json_response(handler, 200, _sku_registry.to_catalog())


def _handle_sku_sync(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    """Rebuild entire SKU registry from current agents."""
    with _registry_lock:
        cards = list(_registry.values())
    count = 0
    for card in cards:
        _sku_registry.register(card)
        _persist_agent_sku(card.agent_id)
        count += 1
    _json_response(handler, 200, {
        "status": "synced",
        "agent_count": count,
        "sku_count": len(_sku_registry.list_all()),
    })


def _handle_deactivate_sku(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    sku_code = params["sku_code"]
    sku = _sku_registry.get_by_sku(sku_code)
    if sku is None:
        _error(handler, 404, f"SKU '{sku_code}' not found")
        return
    _sku_registry.deactivate(sku.agent_id)
    _persist_agent_sku(sku.agent_id)
    updated = _sku_registry.get_by_sku(sku_code)
    _json_response(handler, 200, updated.to_dict() if updated else {"deactivated": sku_code})


def _handle_health(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    with _registry_lock:
        agent_count = len(_registry)
        stale_count = len(_scheduler.get_stale_agents()) if _scheduler else 0
    _json_response(handler, 200, {
        "status": "ok",
        "agent_count": agent_count,
        "stale_count": stale_count,
    })


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------

ROUTES: dict[str, Any] = {
    "GET /health":                            _handle_health,
    "GET /agents":                            _handle_list_agents,
    "GET /agents/obsolete":                   _handle_list_obsolete,
    "POST /agents":                           _handle_register_agent,
    "POST /agents/consolidate":               _handle_consolidate,
    "POST /agents/refresh":                   _handle_refresh,
    "POST /agents/merge":                     _handle_merge_agents,
    "GET /agents/{id}":                       _handle_get_agent,
    "GET /agents/{id}/card.html":             _handle_get_agent_html,
    "DELETE /agents/{id}":                    _handle_delete_agent,
    "POST /agents/{id}/verify":               _handle_verify_agent,
    # SKU routes
    "GET /sku":                               _handle_list_skus,
    "GET /sku/search":                        _handle_search_skus,
    "GET /sku/catalog":                       _handle_sku_catalog,
    "POST /sku/sync":                         _handle_sku_sync,
    "GET /sku/{sku_code}":                    _handle_get_sku,
    "GET /sku/{sku_code}/agent":              _handle_get_sku_agent,
    "DELETE /sku/{sku_code}":                 _handle_deactivate_sku,
}


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class AgentRegistryHandler(BaseHTTPRequestHandler):
    """HTTP request handler that dispatches to route handlers."""

    def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
        # Delegate to Python's standard logger to keep output clean
        import logging
        logging.getLogger("api.server").info(fmt % args)

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        allowed, status, msg = _auth.check(method, self.headers.get("X-API-Key"))
        if not allowed:
            _error(self, status, msg)
            return

        try:
            handler_fn, params = match_route(method, path, ROUTES)
        except KeyError:
            _error(self, 404, f"No route matched: {method} {path}")
            return

        try:
            handler_fn(self, params, qs)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            _error(self, 500, f"Internal server error: {exc}")

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:
        """CORS preflight."""
        self.send_response(204)
        origin = _cors_origin(self.headers.get("Origin"))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def run_server(port: int = 8080, host: str = "127.0.0.1", db_path: str | None = None) -> None:
    """Initialise state and start a threaded HTTP server on *host*:*port*."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("api.server")

    _init_state(db_path)

    server = ThreadingHTTPServer((host, port), AgentRegistryHandler)
    log.info("Agent Registry API listening on http://%s:%d", host, port)
    log.info("DB: %s — loaded %d agents: %s",
             _store.path if _store else "?", len(_registry), list(_registry.keys()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        server.server_close()
