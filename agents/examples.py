"""
Example AgentCard instances representing realistic agents.
"""

from datetime import datetime, timezone

from registry.schema import AgentCapability, AgentCard, TrustLevel

_VERIFICATION_DATE = datetime(2026, 6, 15, tzinfo=timezone.utc)
_TTL = 86400

CODE_AGENT = AgentCard(
    agent_id="code-agent-v1",
    name="Code Assistant",
    version="1.0.0",
    description="A coding assistant that can write, review, and debug code across multiple languages.",
    provider="DevTools Inc.",
    endpoint="http://localhost:8001",
    trust_level=TrustLevel.VERIFIED,
    verification_date=_VERIFICATION_DATE,
    ttl_seconds=_TTL,
    skills=[
        AgentCapability(
            name="write_code",
            description="Generate well-structured, idiomatic code from natural language descriptions.",
            input_types=["text", "spec"],
            output_types=["code", "text"],
            verified=True,
            last_verified=_VERIFICATION_DATE,
            success_rate=0.94,
        ),
        AgentCapability(
            name="review_pr",
            description="Review pull requests for correctness, style, and potential bugs.",
            input_types=["diff", "text"],
            output_types=["text", "json"],
            verified=False,
            last_verified=None,
            success_rate=0.71,
        ),
        AgentCapability(
            name="debug_trace",
            description="Analyze stack traces and error logs to identify root causes.",
            input_types=["text", "log"],
            output_types=["text"],
            verified=False,
            last_verified=None,
            success_rate=0.0,
        ),
    ],
)

SEARCH_AGENT = AgentCard(
    agent_id="search-agent-v1",
    name="Web Search Agent",
    version="2.0.0",
    description="Web search and summarization agent capable of retrieving and condensing online information.",
    provider="SearchOps LLC",
    endpoint="http://localhost:8002",
    trust_level=TrustLevel.VERIFIED,
    verification_date=_VERIFICATION_DATE,
    ttl_seconds=_TTL,
    skills=[
        AgentCapability(
            name="web_search",
            description="Search the web and retrieve relevant results for a given query.",
            input_types=["text"],
            output_types=["json", "text"],
            verified=True,
            last_verified=_VERIFICATION_DATE,
            success_rate=0.88,
        ),
        AgentCapability(
            name="summarize",
            description="Summarize long documents or search result sets into concise insights.",
            input_types=["text", "html"],
            output_types=["text"],
            verified=True,
            last_verified=_VERIFICATION_DATE,
            success_rate=0.92,
        ),
    ],
)

FINANCE_AGENT = AgentCard(
    agent_id="finance-agent-v1",
    name="Finance Analysis Agent",
    version="1.3.0",
    description="Financial analysis agent for portfolio management, risk assessment, and report generation.",
    provider="FinSight AI",
    endpoint="http://localhost:8003",
    trust_level=TrustLevel.SELF_DECLARED,
    verification_date=None,
    ttl_seconds=_TTL,
    skills=[
        AgentCapability(
            name="portfolio_analysis",
            description="Analyze investment portfolios for performance, allocation, and optimization.",
            input_types=["json", "csv"],
            output_types=["json", "text"],
            verified=False,
            last_verified=None,
            success_rate=0.61,
        ),
        AgentCapability(
            name="risk_assessment",
            description="Assess market and portfolio risk using statistical models.",
            input_types=["json"],
            output_types=["json", "text"],
            verified=False,
            last_verified=None,
            success_rate=0.0,
        ),
        AgentCapability(
            name="report_generation",
            description="Generate structured financial reports in PDF or markdown format.",
            input_types=["json", "text"],
            output_types=["pdf", "markdown"],
            verified=False,
            last_verified=None,
            success_rate=0.55,
        ),
    ],
)
