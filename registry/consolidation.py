"""
Consolidation engine for the agent capability registry.

Determines which agents are obsolete, superseded, or redundant based on
capability overlap, performance metrics, and trust levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from registry.schema import AgentCard, TrustLevel


# ---------------------------------------------------------------------------
# Enums & dataclasses
# ---------------------------------------------------------------------------

class ObsolescenceReason(Enum):
    SUPERSEDED = "superseded"           # A newer agent covers all capabilities
    STALE = "stale"                     # TTL expired AND re-verification failed
    LOW_PERFORMANCE = "low_performance" # success_rate < threshold on all capabilities
    CAPABILITY_SUBSET = "capability_subset"  # all caps are strict subset of another agent
    MERGED = "merged"                   # explicitly merged into a composite agent


@dataclass
class SupersessionEdge:
    """B supersedes A."""
    superseded_id: str        # agent being replaced
    superseding_id: str       # agent that replaces it
    reason: ObsolescenceReason
    overlap_score: float      # 0-1, fraction of superseded agent's caps covered by superseding
    performance_delta: float  # avg success_rate(superseding) - avg success_rate(superseded)
    explanation: str


@dataclass
class ConsolidationReport:
    agents_kept: list[str]
    agents_removed: list[str]
    edges: list[SupersessionEdge]
    merged_agents: list[str]  # newly created composite agents
    summary: str

    def to_dict(self) -> dict:
        return {
            "agents_kept": self.agents_kept,
            "agents_removed": self.agents_removed,
            "edges": [
                {
                    "superseded_id": e.superseded_id,
                    "superseding_id": e.superseding_id,
                    "reason": e.reason.value,
                    "overlap_score": e.overlap_score,
                    "performance_delta": e.performance_delta,
                    "explanation": e.explanation,
                }
                for e in self.edges
            ],
            "merged_agents": self.merged_agents,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Trust level ordering helper
# ---------------------------------------------------------------------------

_TRUST_ORDER = {
    TrustLevel.UNVERIFIED: 0,
    TrustLevel.SELF_DECLARED: 1,
    TrustLevel.VERIFIED: 2,
    TrustLevel.AUDITED: 3,
}


def _trust_gte(a: TrustLevel, b: TrustLevel) -> bool:
    """Return True if trust level a >= trust level b."""
    return _TRUST_ORDER[a] >= _TRUST_ORDER[b]


# ---------------------------------------------------------------------------
# ConsolidationEngine
# ---------------------------------------------------------------------------

class ConsolidationEngine:
    """
    Analyzes a registry of AgentCards and identifies which agents are obsolete.

    Supersession rules (in priority order):
    1. MERGED: agent_id is in a MergedAgent's source_ids -> MERGED reason
    2. SUPERSEDED: agent B covers >= threshold (default 0.8) of agent A's capabilities
       AND avg_success_rate(B) >= avg_success_rate(A) - tolerance (default 0.05)
       AND (B.trust_level >= A.trust_level OR B.avg_success_rate > A.avg_success_rate + 0.1)
    3. CAPABILITY_SUBSET: strict subset (score=1.0) regardless of performance
    4. LOW_PERFORMANCE: all capabilities have success_rate < 0.3 AND trust_level == UNVERIFIED
    5. STALE: verification_date + ttl_seconds < now AND last verification failed

    Capability matching: two capabilities match if their names are identical,
    OR if one name contains the other as a substring (case-insensitive),
    OR if their descriptions share >50% word overlap (Jaccard on word sets).
    """

    def __init__(
        self,
        supersession_threshold: float = 0.8,
        performance_tolerance: float = 0.05,
    ) -> None:
        self.supersession_threshold = supersession_threshold
        self.performance_tolerance = performance_tolerance

    # ------------------------------------------------------------------
    # Capability matching helpers
    # ------------------------------------------------------------------

    def _name_match(self, name_a: str, name_b: str) -> bool:
        """True if two capability names semantically match."""
        a = name_a.strip().lower()
        b = name_b.strip().lower()
        if a == b:
            return True
        if a in b or b in a:
            return True
        return False

    def _desc_jaccard(self, desc_a: str, desc_b: str) -> float:
        """Word-level Jaccard similarity between two descriptions."""
        words_a = set(desc_a.lower().split())
        words_b = set(desc_b.lower().split())
        if not words_a and not words_b:
            return 1.0
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def _caps_match(self, cap_a, cap_b) -> bool:
        """True if two AgentCapability objects semantically match."""
        if self._name_match(cap_a.name, cap_b.name):
            return True
        if self._desc_jaccard(cap_a.description, cap_b.description) > 0.5:
            return True
        return False

    # ------------------------------------------------------------------
    # Overlap & performance
    # ------------------------------------------------------------------

    def capability_overlap(self, card_a: AgentCard, card_b: AgentCard) -> float:
        """Fraction of card_a's capabilities covered by card_b."""
        if not card_a.skills:
            return 1.0  # vacuously covered
        covered = 0
        for cap_a in card_a.skills:
            for cap_b in card_b.skills:
                if self._caps_match(cap_a, cap_b):
                    covered += 1
                    break
        return covered / len(card_a.skills)

    def avg_success_rate(self, card: AgentCard) -> float:
        """Average success_rate across all capabilities (skip 0.0 for unverified)."""
        rates = [cap.success_rate for cap in card.skills if cap.success_rate > 0.0]
        if not rates:
            return 0.0
        return sum(rates) / len(rates)

    # ------------------------------------------------------------------
    # Stale detection
    # ------------------------------------------------------------------

    def _is_stale(self, card: AgentCard) -> bool:
        """Return True if the card's TTL has expired and last verification failed."""
        if card.verification_date is None:
            return False
        now = datetime.now(timezone.utc)
        vd = card.verification_date
        # Ensure timezone-aware
        if vd.tzinfo is None:
            vd = vd.replace(tzinfo=timezone.utc)
        expired = (now - vd).total_seconds() > card.ttl_seconds
        if not expired:
            return False
        # Check if last verification failed: any skill not verified counts as failed
        last_failed = any(not cap.verified for cap in card.skills)
        return last_failed

    # ------------------------------------------------------------------
    # Low performance detection
    # ------------------------------------------------------------------

    def _is_low_performance(self, card: AgentCard) -> bool:
        """Return True if all capabilities have success_rate < 0.3 and trust is UNVERIFIED."""
        if card.trust_level != TrustLevel.UNVERIFIED:
            return False
        if not card.skills:
            return False
        return all(cap.success_rate < 0.3 for cap in card.skills)

    # ------------------------------------------------------------------
    # Supersession edge detection
    # ------------------------------------------------------------------

    def find_supersession_edges(self, cards: list[AgentCard]) -> list[SupersessionEdge]:
        """Compare all pairs O(n²) and return all supersession relationships."""
        edges: list[SupersessionEdge] = []

        for i, card_a in enumerate(cards):
            for j, card_b in enumerate(cards):
                if i == j:
                    continue

                overlap = self.capability_overlap(card_a, card_b)
                avg_a = self.avg_success_rate(card_a)
                avg_b = self.avg_success_rate(card_b)
                perf_delta = avg_b - avg_a

                # Rule 3: CAPABILITY_SUBSET — strict subset (score == 1.0)
                if overlap == 1.0 and card_a is not card_b:
                    # Strict subset: B covers all of A's caps
                    # Only emit if B actually has more caps OR equal caps but better perf
                    if len(card_b.skills) >= len(card_a.skills):
                        edges.append(SupersessionEdge(
                            superseded_id=card_a.agent_id,
                            superseding_id=card_b.agent_id,
                            reason=ObsolescenceReason.CAPABILITY_SUBSET,
                            overlap_score=overlap,
                            performance_delta=perf_delta,
                            explanation=(
                                f"All {len(card_a.skills)} capabilities of '{card_a.name}' "
                                f"are covered by '{card_b.name}' (strict subset)."
                            ),
                        ))
                        continue

                # Rule 2: SUPERSEDED — threshold coverage + performance check
                if overlap >= self.supersession_threshold:
                    perf_ok = avg_b >= avg_a - self.performance_tolerance
                    trust_ok = _trust_gte(card_b.trust_level, card_a.trust_level)
                    perf_dominant = avg_b > avg_a + 0.1

                    if perf_ok and (trust_ok or perf_dominant):
                        edges.append(SupersessionEdge(
                            superseded_id=card_a.agent_id,
                            superseding_id=card_b.agent_id,
                            reason=ObsolescenceReason.SUPERSEDED,
                            overlap_score=overlap,
                            performance_delta=perf_delta,
                            explanation=(
                                f"'{card_b.name}' covers {overlap:.0%} of "
                                f"'{card_a.name}'s capabilities with "
                                f"performance delta {perf_delta:+.2f}."
                            ),
                        ))

        return edges

    # ------------------------------------------------------------------
    # Full consolidation pass
    # ------------------------------------------------------------------

    def consolidate(
        self,
        cards: list[AgentCard],
        merged_sources: dict[str, list[str]] | None = None,
    ) -> ConsolidationReport:
        """
        Run full consolidation pass.

        merged_sources: {new_agent_id: [source_agent_id, ...]} for explicit merges.

        Returns which agents to keep and which to remove.
        An agent can only be removed once (if superseded by multiple agents, pick
        the one with the highest overlap_score).
        Never remove an agent that is itself superseding others (keep the winner).
        """
        merged_sources = merged_sources or {}
        all_ids = {card.agent_id for card in cards}
        card_by_id: dict[str, AgentCard] = {card.agent_id: card for card in cards}

        # Collect removal candidates: agent_id -> best SupersessionEdge
        removal_candidates: dict[str, SupersessionEdge] = {}
        edges_to_emit: list[SupersessionEdge] = []
        merged_agent_ids: list[str] = list(merged_sources.keys())

        # Rule 1: MERGED
        # Build reverse map: source_id -> new composite agent id
        merged_by_source: dict[str, str] = {}
        for new_id, source_ids in merged_sources.items():
            for src_id in source_ids:
                if src_id in all_ids:
                    merged_by_source[src_id] = new_id

        for src_id, composite_id in merged_by_source.items():
            card_src = card_by_id.get(src_id)
            card_composite = card_by_id.get(composite_id)
            overlap = 1.0
            perf_delta = 0.0
            if card_src and card_composite:
                overlap = self.capability_overlap(card_src, card_composite)
                perf_delta = self.avg_success_rate(card_composite) - self.avg_success_rate(card_src)
            edge = SupersessionEdge(
                superseded_id=src_id,
                superseding_id=composite_id,
                reason=ObsolescenceReason.MERGED,
                overlap_score=overlap,
                performance_delta=perf_delta,
                explanation=f"Agent '{src_id}' was explicitly merged into '{composite_id}'.",
            )
            edges_to_emit.append(edge)
            # Merged sources are always removed (highest priority)
            removal_candidates[src_id] = edge

        # Rules 4 & 5: LOW_PERFORMANCE and STALE (autonomous removal, no superseding agent needed)
        for card in cards:
            if card.agent_id in removal_candidates:
                continue
            if self._is_low_performance(card):
                edge = SupersessionEdge(
                    superseded_id=card.agent_id,
                    superseding_id="",
                    reason=ObsolescenceReason.LOW_PERFORMANCE,
                    overlap_score=0.0,
                    performance_delta=0.0,
                    explanation=(
                        f"Agent '{card.name}' is UNVERIFIED with all capabilities "
                        f"below 0.3 success rate."
                    ),
                )
                edges_to_emit.append(edge)
                removal_candidates[card.agent_id] = edge
            elif self._is_stale(card):
                edge = SupersessionEdge(
                    superseded_id=card.agent_id,
                    superseding_id="",
                    reason=ObsolescenceReason.STALE,
                    overlap_score=0.0,
                    performance_delta=0.0,
                    explanation=(
                        f"Agent '{card.name}' TTL expired and last verification failed."
                    ),
                )
                edges_to_emit.append(edge)
                removal_candidates[card.agent_id] = edge

        # Rules 2 & 3: SUPERSEDED and CAPABILITY_SUBSET
        supersession_edges = self.find_supersession_edges(cards)

        # Collect the agents that are superseding others — these must be kept
        superseding_agents: set[str] = {
            e.superseding_id for e in supersession_edges if e.superseding_id
        }

        for edge in supersession_edges:
            edges_to_emit.append(edge)
            sid = edge.superseded_id
            # Skip already merged
            if sid in removal_candidates and removal_candidates[sid].reason == ObsolescenceReason.MERGED:
                continue
            # Never remove a superseding agent via supersession (keep winners)
            if sid in superseding_agents:
                # Only remove if there's a strictly better superseding agent
                # i.e., the agent being removed is not itself the "best" in any pair
                # We allow removal if the existing candidate has a better (higher) overlap
                pass
            # Pick best edge per superseded agent (highest overlap_score)
            if sid not in removal_candidates or edge.overlap_score > removal_candidates[sid].overlap_score:
                removal_candidates[sid] = edge

        # Final pass: ensure we never remove an agent that is the sole superseder of another
        # (i.e., if removing agent X would leave agent Y with no superseder, keep X if needed)
        # More concisely: never remove an agent whose agent_id appears as superseding_id
        # unless it is also being merged.
        final_removed: set[str] = set()
        for agent_id, edge in removal_candidates.items():
            if edge.reason == ObsolescenceReason.MERGED:
                final_removed.add(agent_id)
                continue
            # Don't remove an agent that is itself superseding others
            if agent_id in superseding_agents:
                # Allow removal only if it's also being superseded by something better
                # and is NOT the only superseder for any other agent
                # Check: is any other agent's only superseder this one?
                dependents = [
                    e.superseded_id for e in supersession_edges
                    if e.superseding_id == agent_id
                ]
                if dependents:
                    # This agent is superseding others; keep it
                    continue
            final_removed.add(agent_id)

        agents_removed = sorted(final_removed)
        agents_kept = sorted(aid for aid in all_ids if aid not in final_removed)

        # Deduplicate edges (same superseded+superseding pair may appear twice from both rules)
        seen_pairs: set[tuple[str, str]] = set()
        deduped_edges: list[SupersessionEdge] = []
        for e in edges_to_emit:
            pair = (e.superseded_id, e.superseding_id)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                deduped_edges.append(e)

        summary = (
            f"Consolidation complete: {len(agents_kept)} agents kept, "
            f"{len(agents_removed)} removed, "
            f"{len(merged_agent_ids)} composite agents created, "
            f"{len(deduped_edges)} supersession relationships found."
        )

        return ConsolidationReport(
            agents_kept=agents_kept,
            agents_removed=agents_removed,
            edges=deduped_edges,
            merged_agents=merged_agent_ids,
            summary=summary,
        )
