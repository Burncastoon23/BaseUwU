"""
TTL-based re-verification scheduler for the agent registry.

VerificationScheduler tracks registered AgentCards and triggers re-verification
via a VerificationSuite whenever a card's TTL has elapsed since its last
verification_date.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from registry.schema import AgentCard
from verifier.suite import VerificationSuite


class VerificationScheduler:
    """Schedule and execute periodic re-verification of registered agents.

    Parameters
    ----------
    suite:
        The :class:`VerificationSuite` used to probe agents.
    registry:
        Optional pre-populated mapping of *agent_id* -> :class:`AgentCard`.
    """

    def __init__(
        self,
        suite: VerificationSuite,
        registry: dict[str, AgentCard] | None = None,
    ) -> None:
        self.suite = suite
        self.registry: dict[str, AgentCard] = registry or {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_agent(self, card: AgentCard) -> None:
        """Register *card* with the scheduler.

        If a card with the same ``agent_id`` is already registered it is
        replaced.
        """
        self.registry[card.agent_id] = card

    # ------------------------------------------------------------------
    # Staleness detection
    # ------------------------------------------------------------------

    def get_stale_agents(self) -> list[AgentCard]:
        """Return cards whose TTL has elapsed (or that have never been verified).

        A card is considered stale when:
        * ``verification_date`` is *None*, **or**
        * ``now() > verification_date + timedelta(seconds=ttl_seconds)``
        """
        now = datetime.now(timezone.utc)
        stale: list[AgentCard] = []
        for card in self.registry.values():
            if card.verification_date is None:
                stale.append(card)
                continue
            # Ensure verification_date is timezone-aware for comparison
            vd = card.verification_date
            if vd.tzinfo is None:
                vd = vd.replace(tzinfo=timezone.utc)
            expiry = vd + timedelta(seconds=card.ttl_seconds)
            if now > expiry:
                stale.append(card)
        return stale

    # ------------------------------------------------------------------
    # Re-verification
    # ------------------------------------------------------------------

    async def check_and_refresh(self) -> list[str]:
        """Re-verify all stale agents and return their agent_ids.

        For each stale card:
        1. Runs the full probe suite via :meth:`VerificationSuite.run_all`.
        2. Updates the card's trust level and ``verification_date`` in place.
        3. Updates the in-registry reference.

        Returns
        -------
        list[str]
            ``agent_id`` values of every agent that was re-verified this call.
        """
        stale = self.get_stale_agents()
        refreshed: list[str] = []

        for card in stale:
            results = await self.suite.run_all(card)
            updated = self.suite.update_card_trust(card, results)
            self.registry[updated.agent_id] = updated
            refreshed.append(updated.agent_id)

        return refreshed
