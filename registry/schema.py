"""
Agent capability registry schema.

Inspired by NANDA AgentFacts and A2A Agent Cards.
No external dependencies — stdlib only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TrustLevel(str, Enum):
    UNVERIFIED = "unverified"
    SELF_DECLARED = "self_declared"
    VERIFIED = "verified"
    AUDITED = "audited"


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AgentCapability:
    """A single capability (skill) exposed by an agent."""

    name: str
    description: str
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    verified: bool = False
    last_verified: Optional[datetime] = None
    success_rate: float = 0.0  # 0.0 – 1.0

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["last_verified"] = (
            self.last_verified.isoformat() if self.last_verified else None
        )
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentCapability":
        last_verified = d.get("last_verified")
        if isinstance(last_verified, str):
            last_verified = datetime.fromisoformat(last_verified)
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            input_types=d.get("input_types", []),
            output_types=d.get("output_types", []),
            verified=bool(d.get("verified", False)),
            last_verified=last_verified,
            success_rate=float(d.get("success_rate", 0.0)),
        )


@dataclass
class AgentCard:
    """Top-level descriptor for an agent."""

    agent_id: str
    name: str
    version: str
    description: str
    provider: str
    endpoint: str
    skills: list[AgentCapability] = field(default_factory=list)
    trust_level: TrustLevel = TrustLevel.UNVERIFIED
    verification_date: Optional[datetime] = None
    ttl_seconds: int = 86_400  # 24 h default

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "skills": [s.to_dict() for s in self.skills],
            "trust_level": self.trust_level.value,
            "verification_date": (
                self.verification_date.isoformat()
                if self.verification_date
                else None
            ),
            "ttl_seconds": self.ttl_seconds,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentCard":
        verification_date = d.get("verification_date")
        if isinstance(verification_date, str):
            verification_date = datetime.fromisoformat(verification_date)
        return cls(
            agent_id=d.get("agent_id", ""),
            name=d.get("name", ""),
            version=d.get("version", "0.0.0"),
            description=d.get("description", ""),
            provider=d.get("provider", ""),
            endpoint=d.get("endpoint", ""),
            skills=[
                AgentCapability.from_dict(s) for s in d.get("skills", [])
            ],
            trust_level=TrustLevel(d.get("trust_level", TrustLevel.UNVERIFIED)),
            verification_date=verification_date,
            ttl_seconds=int(d.get("ttl_seconds", 86_400)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentCard":
        return cls.from_dict(json.loads(json_str))

    # -- MCP tools/list -------------------------------------------------------

    @classmethod
    def from_mcp_manifest(cls, json_dict: dict[str, Any]) -> "AgentCard":
        """Parse an MCP ``tools/list`` response into an AgentCard.

        Expected shape (MCP 2024-11-05 spec):
        {
            "tools": [
                {
                    "name": "...",
                    "description": "...",
                    "inputSchema": { "type": "object", "properties": {...} }
                },
                ...
            ],
            # Optional top-level metadata extensions:
            "_meta": {
                "agent_id": "...",
                "name": "...",
                "version": "...",
                "provider": "...",
                "endpoint": "..."
            }
        }
        """
        meta: dict[str, Any] = json_dict.get("_meta", {})
        server_info: dict[str, Any] = json_dict.get("serverInfo", {})

        agent_id = meta.get("agent_id") or server_info.get("name", "unknown")
        name = meta.get("name") or server_info.get("name", "Unknown MCP Server")
        version = meta.get("version") or server_info.get("version", "0.0.0")
        description = meta.get("description", "")
        provider = meta.get("provider", "")
        endpoint = meta.get("endpoint", "")

        skills: list[AgentCapability] = []
        for tool in json_dict.get("tools", []):
            input_schema: dict[str, Any] = tool.get("inputSchema", {})
            input_props: dict[str, Any] = input_schema.get("properties", {})
            input_types: list[str] = list(input_props.keys())

            # MCP tools rarely declare output types; use annotations if present
            output_schema: dict[str, Any] = tool.get("outputSchema", {})
            output_props: dict[str, Any] = output_schema.get("properties", {})
            output_types: list[str] = list(output_props.keys()) if output_props else ["text"]

            skills.append(
                AgentCapability(
                    name=tool.get("name", ""),
                    description=tool.get("description", ""),
                    input_types=input_types,
                    output_types=output_types,
                    verified=False,
                )
            )

        return cls(
            agent_id=agent_id,
            name=name,
            version=version,
            description=description,
            provider=provider,
            endpoint=endpoint,
            skills=skills,
            trust_level=TrustLevel.UNVERIFIED,
        )

    # -- A2A /.well-known/agent-card.json ------------------------------------

    @classmethod
    def from_a2a_card(cls, json_dict: dict[str, Any]) -> "AgentCard":
        """Parse a Google A2A ``/.well-known/agent-card.json`` into an AgentCard.

        Expected shape:
        {
            "name": "...",
            "description": "...",
            "version": "...",
            "url": "https://...",
            "provider": { "organization": "...", "url": "..." },
            "skills": [
                {
                    "id": "...",
                    "name": "...",
                    "description": "...",
                    "tags": [...],
                    "examples": [...],
                    "inputModes": ["text", ...],
                    "outputModes": ["text", ...]
                },
                ...
            ],
            "capabilities": { ... },
            "authentication": { ... }
        }
        """
        provider_raw = json_dict.get("provider", {})
        if isinstance(provider_raw, dict):
            provider_str = provider_raw.get(
                "organization", provider_raw.get("url", "")
            )
        else:
            provider_str = str(provider_raw)

        agent_id = json_dict.get("id") or json_dict.get("name", "unknown")
        name = json_dict.get("name", "Unknown A2A Agent")
        version = json_dict.get("version", "0.0.0")
        description = json_dict.get("description", "")
        endpoint = json_dict.get("url", "")

        skills: list[AgentCapability] = []
        for skill in json_dict.get("skills", []):
            input_modes: list[str] = skill.get("inputModes", skill.get("input_modes", []))
            output_modes: list[str] = skill.get("outputModes", skill.get("output_modes", []))

            skills.append(
                AgentCapability(
                    name=skill.get("name") or skill.get("id", ""),
                    description=skill.get("description", ""),
                    input_types=input_modes,
                    output_types=output_modes,
                    verified=False,
                )
            )

        return cls(
            agent_id=agent_id,
            name=name,
            version=version,
            description=description,
            provider=provider_str,
            endpoint=endpoint,
            skills=skills,
            trust_level=TrustLevel.SELF_DECLARED,
        )


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """Outcome of probing a single capability."""

    capability_name: str
    passed: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_msg: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_name": self.capability_name,
            "passed": self.passed,
            "timestamp": self.timestamp.isoformat(),
            "error_msg": self.error_msg,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerificationResult":
        ts = d.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        else:
            ts = datetime.now(timezone.utc)
        return cls(
            capability_name=d.get("capability_name", ""),
            passed=bool(d.get("passed", False)),
            timestamp=ts,
            error_msg=d.get("error_msg"),
        )
