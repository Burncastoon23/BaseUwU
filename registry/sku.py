"""
SKU (Stock Keeping Unit) system for AI agents.
Each agent in the registry gets a deterministic, human-readable SKU.

SKU format: {CATEGORY}-{SUBCATEGORY}-{SHORT_HASH}
Example: CODE-REVIEW-4a2f

The trust tier is a mutable attribute of the SKU, NOT part of the code —
codes stay stable across re-verification so external references never break.
Legacy 4-part codes ({CAT}-{SUB}-{TIER}-{HASH}) are kept as aliases and
resolve to the current code.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SkuCategory(Enum):
    CODE       = "CODE"
    SEARCH     = "SEARCH"
    DATA       = "DATA"
    FINANCE    = "FINANCE"
    MEDIA      = "MEDIA"
    INFRA      = "INFRA"
    COMPOSITE  = "COMP"   # merged agents
    GENERIC    = "GEN"


class SkuTier(Enum):
    VERIFIED   = "VRF"   # TrustLevel.VERIFIED or AUDITED
    DECLARED   = "DCL"   # TrustLevel.SELF_DECLARED
    UNKNOWN    = "UNK"   # TrustLevel.UNVERIFIED


@dataclass
class AgentSKU:
    sku_code: str                        # e.g. "CODE-REVIEW-VRF-4a2f"
    agent_id: str
    category: SkuCategory
    subcategory: str                     # derived from top capability name, max 8 chars, uppercase
    tier: SkuTier
    short_hash: str                      # 4-char hex from agent_id
    listed_at: datetime
    last_updated: datetime
    active: bool = True                  # False when agent is removed/obsolete
    superseded_by_sku: Optional[str] = None  # SKU of successor if obsolete
    tags: list[str] = field(default_factory=list)  # e.g. ["coding", "python", "verified"]
    avg_success_rate: float = 0.0
    capability_count: int = 0
    provider: str = ""

    def to_dict(self) -> dict:
        return {
            "sku_code": self.sku_code,
            "agent_id": self.agent_id,
            "category": self.category.value,
            "subcategory": self.subcategory,
            "tier": self.tier.value,
            "short_hash": self.short_hash,
            "listed_at": self.listed_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "active": self.active,
            "superseded_by_sku": self.superseded_by_sku,
            "tags": self.tags,
            "avg_success_rate": self.avg_success_rate,
            "capability_count": self.capability_count,
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentSKU":
        return cls(
            sku_code=d["sku_code"],
            agent_id=d["agent_id"],
            category=SkuCategory(d["category"]),
            subcategory=d["subcategory"],
            tier=SkuTier(d["tier"]),
            short_hash=d["short_hash"],
            listed_at=datetime.fromisoformat(d["listed_at"]),
            last_updated=datetime.fromisoformat(d["last_updated"]),
            active=bool(d.get("active", True)),
            superseded_by_sku=d.get("superseded_by_sku"),
            tags=list(d.get("tags", [])),
            avg_success_rate=float(d.get("avg_success_rate", 0.0)),
            capability_count=int(d.get("capability_count", 0)),
            provider=d.get("provider", ""),
        )


# ---------------------------------------------------------------------------
# Category detection helpers
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: list[tuple[SkuCategory, list[str]]] = [
    (SkuCategory.CODE,    ["code", "program", "develop", "debug", "review", "script", "compiler"]),
    (SkuCategory.SEARCH,  ["search", "web", "browse", "retrieve", "find", "crawl", "scrape"]),
    (SkuCategory.DATA,    ["data", "analys", "csv", "database", "sql", "chart", "plot", "statistic"]),
    (SkuCategory.FINANCE, ["financ", "portfolio", "risk", "trading", "invest", "market", "stock"]),
    (SkuCategory.MEDIA,   ["image", "video", "audio", "media", "photo", "transcri"]),
    (SkuCategory.INFRA,   ["file", "filesystem", "deploy", "infra", "server", "docker", "cloud", "devops"]),
]


def _detect_category(agent_card) -> SkuCategory:
    # COMPOSITE check first
    if (agent_card.agent_id.startswith("merged-") or
            agent_card.version.startswith("merged-")):
        return SkuCategory.COMPOSITE

    # Build corpus: name + description + all skill names
    skill_names = " ".join(s.name for s in agent_card.skills)
    corpus = (agent_card.name + " " + agent_card.description + " " + skill_names).lower()

    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in corpus:
                return category

    return SkuCategory.GENERIC


def _make_subcategory(agent_card) -> str:
    """First skill name, uppercased, max 8 chars, non-alpha replaced with _."""
    if agent_card.skills:
        raw = agent_card.skills[0].name
    else:
        raw = agent_card.name
    clean = re.sub(r"[^A-Za-z]", "_", raw).upper()
    return clean[:8]


def _detect_tier(agent_card) -> SkuTier:
    from registry.schema import TrustLevel
    if agent_card.trust_level in (TrustLevel.VERIFIED, TrustLevel.AUDITED):
        return SkuTier.VERIFIED
    if agent_card.trust_level == TrustLevel.SELF_DECLARED:
        return SkuTier.DECLARED
    return SkuTier.UNKNOWN


def _short_hash(agent_id: str) -> str:
    return hashlib.sha256(agent_id.encode()).hexdigest()[:4]


def generate_sku(agent_card) -> "AgentSKU":
    """
    Deterministically generate an AgentSKU from an AgentCard.
    """
    category = _detect_category(agent_card)
    subcategory = _make_subcategory(agent_card)
    tier = _detect_tier(agent_card)
    sh = _short_hash(agent_card.agent_id)

    sku_code = f"{category.value}-{subcategory}-{sh}"

    # Tags: union of input_types + output_types, category, tier
    tags_set: set[str] = set()
    for skill in agent_card.skills:
        for t in skill.input_types:
            tags_set.add(t.lower())
        for t in skill.output_types:
            tags_set.add(t.lower())
    tags_set.add(category.value.lower())
    tags_set.add(tier.value.lower())
    tags = sorted(tags_set)

    # avg_success_rate: mean of non-zero success_rates across skills
    rates = [s.success_rate for s in agent_card.skills if s.success_rate > 0.0]
    avg_success_rate = sum(rates) / len(rates) if rates else 0.0

    now = datetime.now(timezone.utc)

    return AgentSKU(
        sku_code=sku_code,
        agent_id=agent_card.agent_id,
        category=category,
        subcategory=subcategory,
        tier=tier,
        short_hash=sh,
        listed_at=now,
        last_updated=now,
        active=True,
        superseded_by_sku=None,
        tags=tags,
        avg_success_rate=avg_success_rate,
        capability_count=len(agent_card.skills),
        provider=agent_card.provider,
    )


class SKURegistry:
    """
    Maintains the mapping agent_id <-> AgentSKU.
    Syncs with the main agent registry.
    """
    def __init__(self):
        self._skus: dict[str, AgentSKU] = {}    # sku_code -> AgentSKU
        self._by_agent: dict[str, str] = {}     # agent_id -> sku_code
        self._aliases: dict[str, str] = {}      # old sku_code -> current sku_code

    def register(self, agent_card) -> AgentSKU:
        """Generate and store SKU for agent. If agent already has SKU, update it
        in place — the code only changes if category/subcategory changed (or the
        old entry used the legacy tier-in-code format), in which case the old
        code is kept as an alias."""
        new_sku = generate_sku(agent_card)

        existing_sku_code = self._by_agent.get(agent_card.agent_id)
        if existing_sku_code is not None:
            existing = self._skus.get(existing_sku_code)
            if existing is not None:
                # Preserve original listed_at; update fields
                new_sku.listed_at = existing.listed_at
                new_sku.last_updated = datetime.now(timezone.utc)
                if existing_sku_code != new_sku.sku_code:
                    # Keep the old code resolvable forever
                    del self._skus[existing_sku_code]
                    self._aliases[existing_sku_code] = new_sku.sku_code
                    # Re-point any aliases that targeted the old code
                    for alias, target in self._aliases.items():
                        if target == existing_sku_code:
                            self._aliases[alias] = new_sku.sku_code

        self._skus[new_sku.sku_code] = new_sku
        self._by_agent[agent_card.agent_id] = new_sku.sku_code
        return new_sku

    def load_state(self, skus: list[AgentSKU], aliases: dict[str, str]) -> None:
        """Hydrate the registry from persisted state (replaces current content)."""
        self._skus = {s.sku_code: s for s in skus}
        self._by_agent = {s.agent_id: s.sku_code for s in skus}
        self._aliases = dict(aliases)

    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def resolve(self, sku_code: str) -> tuple[Optional[AgentSKU], Optional[str]]:
        """Look up a SKU by code, following aliases. Returns (sku, resolved_from)
        where resolved_from is the requested code if it was an alias, else None."""
        sku = self._skus.get(sku_code)
        if sku is not None:
            return sku, None
        target = self._aliases.get(sku_code)
        if target is not None:
            return self._skus.get(target), sku_code
        return None, None

    def deactivate(self, agent_id: str, superseded_by_sku: Optional[str] = None) -> None:
        """Mark SKU as inactive when agent is removed."""
        sku_code = self._by_agent.get(agent_id)
        if sku_code is None:
            return
        sku = self._skus.get(sku_code)
        if sku is not None:
            sku.active = False
            sku.superseded_by_sku = superseded_by_sku
            sku.last_updated = datetime.now(timezone.utc)

    def get_by_sku(self, sku_code: str) -> Optional[AgentSKU]:
        sku, _ = self.resolve(sku_code)
        return sku

    def get_by_agent(self, agent_id: str) -> Optional[AgentSKU]:
        sku_code = self._by_agent.get(agent_id)
        if sku_code is None:
            return None
        return self._skus.get(sku_code)

    def list_active(self) -> list[AgentSKU]:
        return [s for s in self._skus.values() if s.active]

    def list_all(self) -> list[AgentSKU]:
        return list(self._skus.values())

    def search(
        self,
        query: str = "",
        category: str = "",
        tier: str = "",
        active_only: bool = True,
    ) -> list[AgentSKU]:
        """
        Filter SKUs by:
        - query: substring match against sku_code, agent_id, provider, subcategory, or any tag
        - category: SkuCategory.value match (case-insensitive)
        - tier: SkuTier.value match (case-insensitive)
        - active_only: exclude deactivated SKUs
        """
        results: list[AgentSKU] = []
        query_lower = query.lower()
        category_lower = category.lower()
        tier_lower = tier.lower()

        for sku in self._skus.values():
            if active_only and not sku.active:
                continue
            if category_lower and sku.category.value.lower() != category_lower:
                continue
            if tier_lower and sku.tier.value.lower() != tier_lower:
                continue
            if query_lower:
                searchable = " ".join([
                    sku.sku_code,
                    sku.agent_id,
                    sku.provider,
                    sku.subcategory,
                ] + sku.tags).lower()
                if query_lower not in searchable:
                    continue
            results.append(sku)

        return results

    def to_catalog(self) -> dict:
        """Return full catalog as JSON-serializable dict."""
        skus = self.list_all()
        active_count = sum(1 for s in skus if s.active)
        return {
            "meta": {
                "total": len(skus),
                "active": active_count,
                "inactive": len(skus) - active_count,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "skus": [s.to_dict() for s in skus],
        }
