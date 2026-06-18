"""
Regression suite runner for the agent registry verifier.

VerificationSuite aggregates multiple CapabilityProbes, runs them against an
AgentCard, persists history to JSON, and derives trust levels from pass rates.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from registry.schema import AgentCard, TrustLevel, VerificationResult
from verifier.probe import CapabilityProbe


class VerificationSuite:
    """Run a set of probes against an AgentCard and track results over time.

    Parameters
    ----------
    probes:
        List of :class:`CapabilityProbe` instances to run.
    """

    def __init__(self, probes: list[CapabilityProbe] | None = None) -> None:
        self.probes: list[CapabilityProbe] = probes or []
        # history entries: list of dicts with keys "agent_id", "timestamp",
        # "results" (list[VerificationResult.to_dict()])
        self.history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Core run
    # ------------------------------------------------------------------

    async def run_all(self, card: AgentCard) -> list[VerificationResult]:
        """Run every probe concurrently against *card*.

        Returns a flat list of :class:`VerificationResult` objects (one per
        probe).  Results are also appended to :attr:`history`.
        """
        tasks = [probe.run(card) for probe in self.probes]
        results: list[VerificationResult] = await asyncio.gather(*tasks)

        # Persist this run in history
        self.history.append(
            {
                "agent_id": card.agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "results": [r.to_dict() for r in results],
            }
        )

        return list(results)

    # ------------------------------------------------------------------
    # Trust level derivation
    # ------------------------------------------------------------------

    def update_card_trust(
        self, card: AgentCard, results: list[VerificationResult]
    ) -> AgentCard:
        """Return a copy of *card* with :attr:`~AgentCard.trust_level` updated.

        Trust mapping (by pass rate):
        * >= 0.90  -> :attr:`TrustLevel.VERIFIED`
        * 0.50 – 0.89 -> :attr:`TrustLevel.SELF_DECLARED`
        * < 0.50   -> :attr:`TrustLevel.UNVERIFIED`

        The :attr:`~AgentCard.verification_date` is also set to *now*.
        """
        if not results:
            card.trust_level = TrustLevel.UNVERIFIED
            card.verification_date = datetime.now(timezone.utc)
            return card

        pass_rate = sum(1 for r in results if r.passed) / len(results)

        if pass_rate >= 0.90:
            card.trust_level = TrustLevel.VERIFIED
        elif pass_rate >= 0.50:
            card.trust_level = TrustLevel.SELF_DECLARED
        else:
            card.trust_level = TrustLevel.UNVERIFIED

        card.verification_date = datetime.now(timezone.utc)
        return card

    # ------------------------------------------------------------------
    # History persistence
    # ------------------------------------------------------------------

    def save_history(self, path: str) -> None:
        """Write the in-memory history to *path* as a JSON file."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.history, fh, indent=2)

    def load_history(self, path: str) -> None:
        """Load history from a JSON file at *path*, replacing in-memory state."""
        with open(path, "r", encoding="utf-8") as fh:
            raw: list[dict[str, Any]] = json.load(fh)
        self.history = raw

    # ------------------------------------------------------------------
    # Drift report
    # ------------------------------------------------------------------

    def drift_report(self, agent_id: str) -> str:
        """Return a human-readable text summary of success rate trend for *agent_id*.

        The report shows:
        * Overall pass rate across all recorded runs.
        * Per-run summary (timestamp + pass rate).
        * A simple trend indicator (improving / degrading / stable).
        """
        runs = [entry for entry in self.history if entry.get("agent_id") == agent_id]

        if not runs:
            return f"No verification history found for agent '{agent_id}'."

        lines: list[str] = [
            f"Drift report for agent: {agent_id}",
            f"Total runs recorded : {len(runs)}",
            "",
        ]

        pass_rates: list[float] = []
        for entry in runs:
            results = entry.get("results", [])
            if not results:
                rate = 0.0
            else:
                rate = sum(1 for r in results if r.get("passed")) / len(results)
            pass_rates.append(rate)
            lines.append(
                f"  {entry.get('timestamp', 'unknown')}  pass_rate={rate:.0%}"
                f"  ({sum(1 for r in results if r.get('passed'))}/{len(results)} passed)"
            )

        overall = sum(pass_rates) / len(pass_rates)
        lines.append("")
        lines.append(f"Overall average pass rate: {overall:.0%}")

        # Trend: compare first half vs second half
        if len(pass_rates) >= 2:
            mid = len(pass_rates) // 2
            first_half = sum(pass_rates[:mid]) / mid if mid else overall
            second_half_data = pass_rates[mid:]
            second_half = sum(second_half_data) / len(second_half_data)
            delta = second_half - first_half
            if delta > 0.05:
                trend = "IMPROVING"
            elif delta < -0.05:
                trend = "DEGRADING"
            else:
                trend = "STABLE"
            lines.append(f"Trend               : {trend} (Δ{delta:+.0%})")
        else:
            lines.append("Trend               : N/A (need at least 2 runs)")

        return "\n".join(lines)
