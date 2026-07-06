"""
SQLite persistence layer for the agent registry.

Single-file store (stdlib sqlite3, WAL mode) shared by the API server and CLI.
Rows hold the JSON produced by the existing to_dict()/from_dict() methods, so
the schema stays stable even as dataclasses evolve.

DB path resolution: explicit argument > REGISTRY_DB env var > data/registry.db
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from registry.schema import AgentCard
from registry.sku import AgentSKU

DEFAULT_DB_PATH = "data/registry.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    payload  TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skus (
    sku_code TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    payload  TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sku_aliases (
    alias    TEXT PRIMARY KEY,
    sku_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_agent ON verification_history(agent_id);
"""


def resolve_db_path(path: Optional[str] = None) -> str:
    return path or os.environ.get("REGISTRY_DB") or DEFAULT_DB_PATH


class SQLiteStore:
    """Thread-safe write-through store. One connection guarded by a lock —
    the HTTP server already serialises registry mutations, this just makes
    them durable."""

    def __init__(self, path: Optional[str] = None):
        self.path = resolve_db_path(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- agents -------------------------------------------------------------

    def save_agent(self, card: AgentCard) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agents(agent_id, payload, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(agent_id) DO UPDATE SET payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                (card.agent_id, json.dumps(card.to_dict()), self._now()),
            )
            self._conn.commit()

    def delete_agent(self, agent_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
            self._conn.commit()

    def load_agents(self) -> dict[str, AgentCard]:
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM agents").fetchall()
        out: dict[str, AgentCard] = {}
        for (payload,) in rows:
            card = AgentCard.from_dict(json.loads(payload))
            out[card.agent_id] = card
        return out

    # -- SKUs ---------------------------------------------------------------

    def save_sku(self, sku: AgentSKU) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO skus(sku_code, agent_id, payload, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(sku_code) DO UPDATE SET agent_id=excluded.agent_id, "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (sku.sku_code, sku.agent_id, json.dumps(sku.to_dict()), self._now()),
            )
            self._conn.commit()

    def delete_sku(self, sku_code: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM skus WHERE sku_code=?", (sku_code,))
            self._conn.commit()

    def load_skus(self) -> list[AgentSKU]:
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM skus").fetchall()
        return [AgentSKU.from_dict(json.loads(payload)) for (payload,) in rows]

    def save_alias(self, alias: str, sku_code: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sku_aliases(alias, sku_code, created_at) VALUES(?,?,?) "
                "ON CONFLICT(alias) DO UPDATE SET sku_code=excluded.sku_code",
                (alias, sku_code, self._now()),
            )
            self._conn.commit()

    def load_aliases(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT alias, sku_code FROM sku_aliases").fetchall()
        return dict(rows)

    # -- verification history -------------------------------------------------

    def add_verification(self, agent_id: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO verification_history(agent_id, timestamp, payload) VALUES(?,?,?)",
                (agent_id, entry.get("timestamp", self._now()), json.dumps(entry)),
            )
            self._conn.commit()

    def load_history(self, agent_id: Optional[str] = None) -> list[dict[str, Any]]:
        q = "SELECT payload FROM verification_history"
        args: tuple = ()
        if agent_id:
            q += " WHERE agent_id=?"
            args = (agent_id,)
        q += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [json.loads(payload) for (payload,) in rows]

    # -- misc -----------------------------------------------------------------

    def is_empty(self) -> bool:
        with self._lock:
            (n,) = self._conn.execute("SELECT COUNT(*) FROM agents").fetchone()
        return n == 0
