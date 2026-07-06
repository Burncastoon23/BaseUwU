"""
API-key authentication for the registry API.

Two access levels:
  - read : GET routes. Required only if REGISTRY_REQUIRE_READ_KEY=1.
  - admin: POST/DELETE routes. Always required when any key is configured.

Key sources (checked in order):
  - REGISTRY_API_KEYS env var: comma-separated "level:key" pairs,
    e.g. "admin:s3cret,read:abc". A bare key (no prefix) counts as admin.
  - keys file (REGISTRY_KEYS_FILE): one "level:key" per line, '#' comments.

If NO keys are configured at all, auth is disabled (open mode) — a warning
is logged at startup so this can't happen silently in production.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets

log = logging.getLogger("api.auth")

READ = "read"
ADMIN = "admin"


def generate_key() -> str:
    return secrets.token_urlsafe(32)


class ApiKeyAuth:
    def __init__(self, env: dict[str, str] | None = None):
        e = env if env is not None else os.environ
        self._keys: list[tuple[str, str]] = []  # (level, key)
        raw = e.get("REGISTRY_API_KEYS", "")
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            self._keys.append(self._parse(part))
        keys_file = e.get("REGISTRY_KEYS_FILE", "")
        if keys_file and os.path.exists(keys_file):
            with open(keys_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self._keys.append(self._parse(line))
        self.require_read_key = e.get("REGISTRY_REQUIRE_READ_KEY", "0") in ("1", "true", "yes")
        if not self._keys:
            log.warning("No API keys configured — auth is DISABLED (open mode). "
                        "Set REGISTRY_API_KEYS for production.")

    @staticmethod
    def _parse(entry: str) -> tuple[str, str]:
        if ":" in entry:
            level, key = entry.split(":", 1)
            level = level.strip().lower()
            if level not in (READ, ADMIN):
                level = ADMIN
            return level, key.strip()
        return ADMIN, entry

    @property
    def enabled(self) -> bool:
        return bool(self._keys)

    def _match_level(self, presented: str) -> str | None:
        """Return the level of the matching key, or None. Admin keys also
        satisfy read access."""
        for level, key in self._keys:
            if hmac.compare_digest(presented, key):
                return level
        return None

    def check(self, method: str, presented_key: str | None) -> tuple[bool, int, str]:
        """Return (allowed, status, message). status/message only meaningful
        when not allowed (401 = no key given, 403 = bad key/insufficient)."""
        if not self.enabled:
            return True, 200, ""
        needs_admin = method in ("POST", "DELETE", "PUT", "PATCH")
        if not needs_admin and not self.require_read_key:
            return True, 200, ""
        if not presented_key:
            return False, 401, "Missing X-API-Key header"
        level = self._match_level(presented_key)
        if level is None:
            return False, 403, "Invalid API key"
        if needs_admin and level != ADMIN:
            return False, 403, "Admin key required for this operation"
        return True, 200, ""
