"""
Tracks which agents have been marked obsolete and why.
Persists state to JSON so the registry survives restarts.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ObsolescenceRecord:
    agent_id: str
    reason: str                    # ObsolescenceReason.value
    superseded_by: Optional[str]   # agent_id of successor, if SUPERSEDED/MERGED
    flagged_at: datetime
    removed_at: Optional[datetime] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "reason": self.reason,
            "superseded_by": self.superseded_by,
            "flagged_at": self.flagged_at.isoformat(),
            "removed_at": self.removed_at.isoformat() if self.removed_at is not None else None,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ObsolescenceRecord":
        flagged_at = d.get("flagged_at")
        if isinstance(flagged_at, str):
            flagged_at = datetime.fromisoformat(flagged_at)
        else:
            flagged_at = datetime.now(timezone.utc)

        removed_at = d.get("removed_at")
        if isinstance(removed_at, str):
            removed_at = datetime.fromisoformat(removed_at)
        else:
            removed_at = None

        return cls(
            agent_id=d.get("agent_id", ""),
            reason=d.get("reason", ""),
            superseded_by=d.get("superseded_by"),
            flagged_at=flagged_at,
            removed_at=removed_at,
            notes=d.get("notes", ""),
        )


class ObsolescenceTracker:
    """
    Maintains the list of flagged and removed agents.
    An agent is "flagged" when ConsolidationEngine recommends removal.
    An agent is "removed" when the API actually deletes it from the registry.
    """

    def __init__(self, persist_path: Optional[str] = None):
        self._records: dict[str, ObsolescenceRecord] = {}
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def flag(
        self,
        agent_id: str,
        reason: str,
        superseded_by: Optional[str] = None,
        notes: str = "",
    ) -> ObsolescenceRecord:
        """Flag an agent as obsolete. Overwrites any existing record for the same agent_id."""
        record = ObsolescenceRecord(
            agent_id=agent_id,
            reason=reason,
            superseded_by=superseded_by,
            flagged_at=datetime.now(timezone.utc),
            removed_at=None,
            notes=notes,
        )
        self._records[agent_id] = record
        self._save()
        return record

    def confirm_removal(self, agent_id: str) -> None:
        """Mark a flagged agent as actually removed. Raises KeyError if not flagged."""
        if agent_id not in self._records:
            raise KeyError(f"No obsolescence record found for agent_id={agent_id!r}")
        self._records[agent_id].removed_at = datetime.now(timezone.utc)
        self._save()

    def is_flagged(self, agent_id: str) -> bool:
        """Return True if the agent has been flagged (whether or not removed)."""
        return agent_id in self._records

    def is_removed(self, agent_id: str) -> bool:
        """Return True if the agent has been flagged AND confirmed removed."""
        record = self._records.get(agent_id)
        return record is not None and record.removed_at is not None

    def get_flagged(self) -> list[ObsolescenceRecord]:
        """Return all records that are flagged but NOT yet removed."""
        return [r for r in self._records.values() if r.removed_at is None]

    def get_removed(self) -> list[ObsolescenceRecord]:
        """Return all records that have been confirmed removed."""
        return [r for r in self._records.values() if r.removed_at is not None]

    def get_record(self, agent_id: str) -> Optional[ObsolescenceRecord]:
        """Return the obsolescence record for agent_id, or None if not flagged."""
        return self._records.get(agent_id)

    def _save(self) -> None:
        """Persist the current state to JSON if a persist_path is configured."""
        if not self._persist_path:
            return
        data = {agent_id: record.to_dict() for agent_id, record in self._records.items()}
        with open(self._persist_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    def _load(self) -> None:
        """Load persisted state from JSON. Silently ignores missing file."""
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as fh:
                data: dict = json.load(fh)
            self._records = {
                agent_id: ObsolescenceRecord.from_dict(record_dict)
                for agent_id, record_dict in data.items()
            }
        except FileNotFoundError:
            self._records = {}

    def to_dict(self) -> dict:
        """Return a serialisable representation of all records."""
        return {agent_id: record.to_dict() for agent_id, record in self._records.items()}
