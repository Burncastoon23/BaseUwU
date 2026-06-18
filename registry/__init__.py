"""
registry — Agent capability registry for NANDA/A2A/MCP agent manifests.
"""

from .schema import (
    AgentCapability,
    AgentCard,
    TrustLevel,
    VerificationResult,
)
from .renderer import (
    render_card_text,
    render_card_html,
    render_registry_index,
)

__all__ = [
    # schema
    "AgentCapability",
    "AgentCard",
    "TrustLevel",
    "VerificationResult",
    # renderers
    "render_card_text",
    "render_card_html",
    "render_registry_index",
]
