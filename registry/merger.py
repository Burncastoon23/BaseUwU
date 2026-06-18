"""
Agent merger utilities for the capability registry.

Provides functions to create composite AgentCards from multiple source agents,
deduplicating capabilities and deriving conservative metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone

from registry.schema import AgentCard, AgentCapability, TrustLevel


# ---------------------------------------------------------------------------
# Trust level ordering (conservative = lower value wins)
# ---------------------------------------------------------------------------

_TRUST_ORDER = {
    TrustLevel.UNVERIFIED: 0,
    TrustLevel.SELF_DECLARED: 1,
    TrustLevel.VERIFIED: 2,
    TrustLevel.AUDITED: 3,
}

_ORDER_TRUST = {v: k for k, v in _TRUST_ORDER.items()}


def _min_trust(levels: list[TrustLevel]) -> TrustLevel:
    """Return the least-trusted TrustLevel in the list."""
    if not levels:
        return TrustLevel.UNVERIFIED
    return _ORDER_TRUST[min(_TRUST_ORDER[lvl] for lvl in levels)]


def _max_version(versions: list[str]) -> str:
    """Return the lexicographically/semantically greatest version string."""
    if not versions:
        return "0.0.0"

    def _version_key(v: str):
        # Try to parse as semver-ish: split on '.' and convert numeric parts
        parts = []
        for part in v.split("."):
            try:
                parts.append((0, int(part)))
            except ValueError:
                parts.append((1, part))  # non-numeric sorts after numeric
        return parts

    return max(versions, key=_version_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capability_union(cards: list[AgentCard]) -> list[AgentCapability]:
    """Union of all capabilities, deduped by name, best success_rate wins."""
    # Use case-folded name as the dedup key
    best: dict[str, AgentCapability] = {}
    for card in cards:
        for cap in card.skills:
            key = cap.name.strip().lower()
            if key not in best or cap.success_rate > best[key].success_rate:
                best[key] = cap
    # Return in insertion-stable order (dict preserves insertion order in Python 3.7+)
    return list(best.values())


def merge_agents(
    source_cards: list[AgentCard],
    new_id: str,
    new_name: str,
    new_description: str,
) -> AgentCard:
    """
    Create a new composite AgentCard that is the union of all source_cards' capabilities.

    - Deduplicate capabilities by name (keep the one with highest success_rate)
    - New trust_level = min(source trust_levels) to be conservative
    - New version = "merged-" + max version string
    - verification_date = now, ttl = min(source ttls)
    - endpoint = first non-empty endpoint found
    """
    if not source_cards:
        raise ValueError("merge_agents requires at least one source card.")

    # Deduplicated capability union
    merged_skills = capability_union(source_cards)

    # Conservative trust level
    trust_level = _min_trust([card.trust_level for card in source_cards])

    # Version: "merged-" + max source version
    max_ver = _max_version([card.version for card in source_cards])
    new_version = f"merged-{max_ver}"

    # TTL: use minimum across sources to be conservative
    min_ttl = min((card.ttl_seconds for card in source_cards), default=86_400)

    # Endpoint: first non-empty
    endpoint = ""
    for card in source_cards:
        if card.endpoint:
            endpoint = card.endpoint
            break

    # Provider: concatenate unique providers
    seen_providers: list[str] = []
    for card in source_cards:
        if card.provider and card.provider not in seen_providers:
            seen_providers.append(card.provider)
    provider = ", ".join(seen_providers) if seen_providers else ""

    return AgentCard(
        agent_id=new_id,
        name=new_name,
        version=new_version,
        description=new_description,
        provider=provider,
        endpoint=endpoint,
        skills=merged_skills,
        trust_level=trust_level,
        verification_date=datetime.now(timezone.utc),
        ttl_seconds=min_ttl,
    )
