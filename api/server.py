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
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agents.examples import CODE_AGENT, FINANCE_AGENT, SEARCH_AGENT
from api.routes import match_route
from registry.renderer import render_card_html
from registry.schema import AgentCard, TrustLevel
from verifier.scheduler import VerificationScheduler
from verifier.suite import VerificationSuite

# ---------------------------------------------------------------------------
# Shared state (module-level so the handler class can access it)
# ---------------------------------------------------------------------------

_registry: dict[str, AgentCard] = {}
_scheduler: VerificationScheduler | None = None
_registry_lock = threading.Lock()


def _init_state() -> None:
    """Populate registry with the three example agents and create scheduler."""
    global _registry, _scheduler
    with _registry_lock:
        for card in (CODE_AGENT, SEARCH_AGENT, FINANCE_AGENT):
            _registry[card.agent_id] = card
    suite = VerificationSuite()
    _scheduler = VerificationScheduler(suite=suite, registry=_registry)


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
                removed.append(aid)

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
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: "AgentRegistryHandler", status: int, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: "AgentRegistryHandler", status: int, message: str) -> None:
    _json_response(handler, status, {"error": message})


def _read_json_body(handler: "AgentRegistryHandler") -> dict[str, Any] | None:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
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
    status = 200 if already_exists else 201
    _json_response(handler, status, card.to_dict())


def _handle_delete_agent(handler: "AgentRegistryHandler", params: dict, qs: dict) -> None:
    agent_id = params["id"]
    with _registry_lock:
        card = _registry.pop(agent_id, None)
    if card is None:
        _error(handler, 404, f"Agent '{agent_id}' not found")
        return
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

    _json_response(handler, 201, {
        "merged_id": new_id,
        "source_ids": source_ids,
        "card": merged_card.to_dict(),
    })


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
    "GET /health":                    _handle_health,
    "GET /agents":                    _handle_list_agents,
    "GET /agents/obsolete":           _handle_list_obsolete,
    "POST /agents":                   _handle_register_agent,
    "POST /agents/consolidate":       _handle_consolidate,
    "POST /agents/refresh":           _handle_refresh,
    "POST /agents/merge":             _handle_merge_agents,
    "GET /agents/{id}":               _handle_get_agent,
    "GET /agents/{id}/card.html":     _handle_get_agent_html,
    "DELETE /agents/{id}":            _handle_delete_agent,
    "POST /agents/{id}/verify":       _handle_verify_agent,
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def run_server(port: int = 8080, host: str = "0.0.0.0") -> None:
    """Initialise state and start a threaded HTTP server on *host*:*port*."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("api.server")

    _init_state()

    server = ThreadingHTTPServer((host, port), AgentRegistryHandler)
    log.info("Agent Registry API listening on http://%s:%d", host, port)
    log.info("Loaded %d example agents: %s", len(_registry), list(_registry.keys()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        server.server_close()
