"""
CLI entry point for the AI agent capability registry.

Usage: python cli.py [command] [options]

Commands:
  list                    List all registered agents (text table)
  show <agent_id>         Show full capability card for an agent (text)
  show --html <agent_id>  Output HTML card
  verify <agent_id>       Run mock verification probes on an agent
  drift <agent_id>        Show drift report for an agent
  ingest-mcp <json_file>  Parse MCP manifest JSON file -> register agent
  ingest-a2a <json_file>  Parse A2A Agent Card JSON file -> register agent
  keygen [read|admin]     Generate an API key (default: admin)
  help                    Show this help
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

from agents import CODE_AGENT, SEARCH_AGENT, FINANCE_AGENT
from registry.renderer import (
    render_card_text,
    render_card_html,
    render_registry_index,
)
from registry.schema import AgentCard
from verifier.probe import MockProbe


# ---------------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, AgentCard] = {
    CODE_AGENT.agent_id: CODE_AGENT,
    SEARCH_AGENT.agent_id: SEARCH_AGENT,
    FINANCE_AGENT.agent_id: FINANCE_AGENT,
}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list() -> None:
    """List all registered agents as a text table."""
    cards = list(_REGISTRY.values())
    print(render_registry_index(cards))


def cmd_show(agent_id: str, html: bool = False) -> None:
    """Show full capability card for an agent."""
    card = _REGISTRY.get(agent_id)
    if card is None:
        print(f"Error: agent '{agent_id}' not found in registry.", file=sys.stderr)
        print(f"Known agents: {', '.join(_REGISTRY.keys())}", file=sys.stderr)
        sys.exit(1)
    if html:
        print(render_card_html(card))
    else:
        print(render_card_text(card))


async def _run_verify(agent_id: str) -> None:
    """Run mock verification probes on an agent and print results."""
    card = _REGISTRY.get(agent_id)
    if card is None:
        print(f"Error: agent '{agent_id}' not found in registry.", file=sys.stderr)
        print(f"Known agents: {', '.join(_REGISTRY.keys())}", file=sys.stderr)
        sys.exit(1)

    if not card.skills:
        print(f"Agent '{agent_id}' has no capabilities to verify.")
        return

    print(f"Running mock verification probes on: {card.name} ({agent_id})")
    print("-" * 60)

    passed = 0
    failed = 0
    for skill in card.skills:
        # Use the skill's success_rate to decide whether the mock passes.
        # Capabilities with success_rate >= 0.5 are assumed to pass; others fail.
        should_pass = skill.success_rate >= 0.5
        probe = MockProbe(
            capability_name=skill.name,
            should_pass=should_pass,
        )
        result = await probe.run(card)
        status = "PASS" if result.passed else "FAIL"
        ts = result.timestamp.strftime("%H:%M:%S UTC")
        msg = f"  [{status}] {result.capability_name:<25} @ {ts}"
        if result.error_msg:
            msg += f"  — {result.error_msg}"
        print(msg)
        if result.passed:
            passed += 1
        else:
            failed += 1

    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(card.skills)} probe(s).")


def cmd_verify(agent_id: str) -> None:
    asyncio.run(_run_verify(agent_id))


def cmd_drift(agent_id: str) -> None:
    """Show a simple drift report for an agent."""
    card = _REGISTRY.get(agent_id)
    if card is None:
        print(f"Error: agent '{agent_id}' not found in registry.", file=sys.stderr)
        print(f"Known agents: {', '.join(_REGISTRY.keys())}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    print(f"Drift report for: {card.name} ({agent_id})")
    print("=" * 60)

    if card.verification_date is None:
        print("  Status  : NEVER VERIFIED — no baseline to compare against.")
    else:
        vd = card.verification_date
        if vd.tzinfo is None:
            vd = vd.replace(tzinfo=timezone.utc)
        age_s = (now - vd).total_seconds()
        age_h = age_s / 3600
        stale = age_s > card.ttl_seconds
        status = "STALE" if stale else "FRESH"
        print(f"  Status  : {status}")
        print(f"  Verified: {vd.strftime('%Y-%m-%d %H:%M UTC')}  ({age_h:.1f}h ago)")
        print(f"  TTL     : {card.ttl_seconds // 3600}h  "
              f"({'expired' if stale else 'valid until ' + (vd.replace(second=0, microsecond=0)).strftime('%Y-%m-%d %H:%M UTC')})")

    print()
    print("  Capability drift summary:")
    print(f"  {'Capability':<25} {'Verified?':<12} {'Success Rate'}")
    print("  " + "-" * 50)
    for skill in card.skills:
        v = "yes" if skill.verified else "no"
        rate = f"{skill.success_rate * 100:.0f}%" if skill.success_rate > 0 else "n/a"
        drift_flag = ""
        if not skill.verified and skill.success_rate > 0:
            drift_flag = "  [self-declared rate — unconfirmed]"
        print(f"  {skill.name:<25} {v:<12} {rate}{drift_flag}")

    print("=" * 60)


def cmd_ingest_mcp(json_file: str) -> None:
    """Parse an MCP manifest JSON file and register the resulting agent."""
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {json_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in '{json_file}': {exc}", file=sys.stderr)
        sys.exit(1)

    card = AgentCard.from_mcp_manifest(data)
    _REGISTRY[card.agent_id] = card
    print(f"Ingested MCP agent: {card.name} (id={card.agent_id})")
    print(f"  {len(card.skills)} capability/ies parsed:")
    for skill in card.skills:
        print(f"    - {skill.name}: {skill.description}")
    print()
    print(render_card_text(card))


def cmd_ingest_a2a(json_file: str) -> None:
    """Parse an A2A agent-card JSON file and register the resulting agent."""
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {json_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in '{json_file}': {exc}", file=sys.stderr)
        sys.exit(1)

    card = AgentCard.from_a2a_card(data)
    _REGISTRY[card.agent_id] = card
    print(f"Ingested A2A agent: {card.name} (id={card.agent_id})")
    print(f"  {len(card.skills)} skill(s) parsed:")
    for skill in card.skills:
        print(f"    - {skill.name}: {skill.description}")
    print()
    print(render_card_text(card))


def cmd_keygen(level: str = "admin") -> None:
    """Generate an API key and print the env-var line to configure it."""
    from api.auth import generate_key
    key = generate_key()
    print(f"{level}:{key}")
    print(f"\n# Add to the server environment:", file=sys.stderr)
    print(f"export REGISTRY_API_KEYS=\"{level}:{key}\"", file=sys.stderr)


def cmd_help() -> None:
    print(__doc__)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("help", "--help", "-h"):
        cmd_help()
        return

    command = args[0]

    if command == "list":
        cmd_list()

    elif command == "show":
        remaining = args[1:]
        html = False
        if remaining and remaining[0] == "--html":
            html = True
            remaining = remaining[1:]
        if not remaining:
            print("Error: 'show' requires an <agent_id> argument.", file=sys.stderr)
            sys.exit(1)
        cmd_show(remaining[0], html=html)

    elif command == "verify":
        if len(args) < 2:
            print("Error: 'verify' requires an <agent_id> argument.", file=sys.stderr)
            sys.exit(1)
        cmd_verify(args[1])

    elif command == "drift":
        if len(args) < 2:
            print("Error: 'drift' requires an <agent_id> argument.", file=sys.stderr)
            sys.exit(1)
        cmd_drift(args[1])

    elif command == "ingest-mcp":
        if len(args) < 2:
            print("Error: 'ingest-mcp' requires a <json_file> argument.", file=sys.stderr)
            sys.exit(1)
        cmd_ingest_mcp(args[1])

    elif command == "ingest-a2a":
        if len(args) < 2:
            print("Error: 'ingest-a2a' requires a <json_file> argument.", file=sys.stderr)
            sys.exit(1)
        cmd_ingest_a2a(args[1])

    elif command == "keygen":
        level = args[1] if len(args) > 1 else "admin"
        if level not in ("read", "admin"):
            print("Error: level must be 'read' or 'admin'.", file=sys.stderr)
            sys.exit(1)
        cmd_keygen(level)

    else:
        print(f"Error: unknown command '{command}'.", file=sys.stderr)
        print("Run 'python cli.py help' for usage.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
