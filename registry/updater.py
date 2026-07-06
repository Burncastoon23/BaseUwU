"""
Auto-update engine: periodically re-verifies agents, detects performance degradation,
and flags candidates for consolidation/removal.
"""
import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from registry.schema import AgentCard, TrustLevel
from verifier.scheduler import VerificationScheduler

# Ordering of TrustLevel values for comparison (higher index = higher trust)
_TRUST_ORDER = [
    TrustLevel.UNVERIFIED,
    TrustLevel.SELF_DECLARED,
    TrustLevel.VERIFIED,
    TrustLevel.AUDITED,
]


def _trust_rank(level: TrustLevel) -> int:
    try:
        return _TRUST_ORDER.index(level)
    except ValueError:
        return -1


@dataclass
class UpdateEvent:
    event_type: str   # "verified", "degraded", "stale", "removed", "error"
    agent_id: str
    timestamp: datetime
    details: str
    old_trust: Optional[TrustLevel] = None
    new_trust: Optional[TrustLevel] = None

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "old_trust": self.old_trust.value if self.old_trust is not None else None,
            "new_trust": self.new_trust.value if self.new_trust is not None else None,
        }


class UpdateWatcher:
    """
    Background thread that watches the registry for agents needing update.

    Every `check_interval` seconds it:
    1. Calls scheduler.check_and_refresh() to re-verify stale agents
    2. For any agent whose trust_level DEGRADED (went down), emits a "degraded" event
    3. For any agent where ALL capabilities have success_rate < low_perf_threshold (0.3),
       calls the on_low_performance callback
    4. Emits events to a list (capped at max_events=500) for the API to query

    Thread-safe: uses threading.Lock for registry and event_log access.
    """

    def __init__(
        self,
        scheduler: VerificationScheduler,
        check_interval: int = 300,          # 5 minutes default
        low_perf_threshold: float = 0.3,
        on_low_performance: Optional[Callable[[AgentCard], None]] = None,
        on_degraded: Optional[Callable[[AgentCard, TrustLevel, TrustLevel], None]] = None,
        max_events: int = 500,
    ):
        self.scheduler = scheduler
        self.check_interval = check_interval
        self.low_perf_threshold = low_perf_threshold
        self.on_low_performance = on_low_performance
        self.on_degraded = on_degraded
        self.max_events = max_events

        self._event_log: list[UpdateEvent] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start background thread (daemon=True)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="UpdateWatcher")
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread to stop and join."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def get_events(
        self,
        since: Optional[datetime] = None,
        event_type: Optional[str] = None,
    ) -> list[UpdateEvent]:
        """Return events, optionally filtered."""
        with self._lock:
            events = list(self._event_log)
        if since is not None:
            # Make since timezone-aware if needed
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            events = [e for e in events if e.timestamp >= since]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        return events

    def force_refresh(self) -> int:
        """Trigger an immediate check (non-blocking, runs in thread pool). Returns number of agents queued."""
        with self._lock:
            stale = self.scheduler.get_stale_agents()
            count = len(stale)

        def _run():
            asyncio.run(self._do_refresh())

        t = threading.Thread(target=_run, daemon=True, name="UpdateWatcher-ForceRefresh")
        t.start()
        return count

    def _watch_loop(self) -> None:
        """Main loop: runs asyncio.run(scheduler.check_and_refresh()) then sleeps."""
        while not self._stop_event.is_set():
            try:
                asyncio.run(self._do_refresh())
            except Exception as exc:
                self._emit(UpdateEvent(
                    event_type="error",
                    agent_id="__watcher__",
                    timestamp=datetime.now(timezone.utc),
                    details=f"Unexpected error during refresh cycle: {exc}",
                ))
            # Sleep in small increments to remain responsive to stop signals
            deadline = time.monotonic() + self.check_interval
            while not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1.0, remaining))

    async def _do_refresh(self) -> None:
        """Core refresh logic: re-verify stale agents and emit appropriate events."""
        # Snapshot trust levels before refresh
        with self._lock:
            pre_trust: dict[str, TrustLevel] = {
                agent_id: card.trust_level
                for agent_id, card in self.scheduler.registry.items()
            }

        try:
            refreshed_ids = await self.scheduler.check_and_refresh()
        except Exception as exc:
            self._emit(UpdateEvent(
                event_type="error",
                agent_id="__scheduler__",
                timestamp=datetime.now(timezone.utc),
                details=f"check_and_refresh raised: {exc}",
            ))
            return

        now = datetime.now(timezone.utc)

        with self._lock:
            registry_snapshot = dict(self.scheduler.registry)

        for agent_id in refreshed_ids:
            card = registry_snapshot.get(agent_id)
            if card is None:
                continue

            old_trust = pre_trust.get(agent_id, TrustLevel.UNVERIFIED)
            new_trust = card.trust_level

            # Emit "verified" event
            self._emit(UpdateEvent(
                event_type="verified",
                agent_id=agent_id,
                timestamp=now,
                details=f"Agent re-verified. Trust: {old_trust.value} -> {new_trust.value}",
                old_trust=old_trust,
                new_trust=new_trust,
            ))

            # Emit "degraded" if trust went down
            if _trust_rank(new_trust) < _trust_rank(old_trust):
                degraded_event = UpdateEvent(
                    event_type="degraded",
                    agent_id=agent_id,
                    timestamp=now,
                    details=(
                        f"Trust level degraded from {old_trust.value} to {new_trust.value}"
                    ),
                    old_trust=old_trust,
                    new_trust=new_trust,
                )
                self._emit(degraded_event)
                if self.on_degraded is not None:
                    try:
                        self.on_degraded(card, old_trust, new_trust)
                    except Exception:
                        pass

            # Check if ALL capabilities are below the low performance threshold
            skills = card.skills
            if skills and all(
                s.success_rate < self.low_perf_threshold for s in skills
            ):
                self._emit(UpdateEvent(
                    event_type="stale",
                    agent_id=agent_id,
                    timestamp=now,
                    details=(
                        f"All {len(skills)} capabilities below "
                        f"performance threshold ({self.low_perf_threshold})"
                    ),
                ))
                if self.on_low_performance is not None:
                    try:
                        self.on_low_performance(card)
                    except Exception:
                        pass

    def _emit(self, event: UpdateEvent) -> None:
        """Thread-safe append to event_log with cap."""
        with self._lock:
            self._event_log.append(event)
            # Trim oldest entries if cap exceeded
            if len(self._event_log) > self.max_events:
                self._event_log = self._event_log[-self.max_events:]
