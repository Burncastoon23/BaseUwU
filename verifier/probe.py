"""
Capability probe system for the agent registry verifier.

Probes are run against an AgentCard to produce VerificationResults.
Only stdlib is used (asyncio, urllib, json).
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from registry.schema import AgentCard, VerificationResult


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class CapabilityProbe(ABC):
    """Abstract base class for all capability probes."""

    name: str
    description: str

    @abstractmethod
    async def run(self, agent_card: AgentCard) -> VerificationResult:
        """Execute the probe against *agent_card* and return a result."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# HttpProbe
# ---------------------------------------------------------------------------

class HttpProbe(CapabilityProbe):
    """POST a test payload to the agent endpoint and validate the response.

    Parameters
    ----------
    capability_name:
        Name of the capability being verified (used in the result).
    payload:
        JSON-serialisable dict sent as the POST body.
    expected_keys:
        If provided, the response JSON must contain all of these top-level keys
        for the probe to pass.
    timeout:
        HTTP timeout in seconds (default 10).
    """

    name = "http_probe"
    description = (
        "Makes an HTTP POST to the agent endpoint with a test payload and "
        "checks that the response matches the expected schema."
    )

    def __init__(
        self,
        capability_name: str,
        payload: Optional[dict[str, Any]] = None,
        expected_keys: Optional[list[str]] = None,
        timeout: int = 10,
    ) -> None:
        self.capability_name = capability_name
        self.payload = payload or {}
        self.expected_keys = expected_keys or []
        self.timeout = timeout

    async def run(self, agent_card: AgentCard) -> VerificationResult:
        """Send payload to agent_card.endpoint and validate the response."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._do_request, agent_card.endpoint)
            return result
        except Exception as exc:  # pragma: no cover — network errors
            return VerificationResult(
                capability_name=self.capability_name,
                passed=False,
                timestamp=datetime.now(timezone.utc),
                error_msg=f"Unexpected error: {exc}",
            )

    def _do_request(self, endpoint: str) -> VerificationResult:
        """Blocking HTTP call executed in a thread-pool executor."""
        body = json.dumps(self.payload).encode("utf-8")
        req = urllib.request.Request(
            url=endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        ts = datetime.now(timezone.utc)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return VerificationResult(
                capability_name=self.capability_name,
                passed=False,
                timestamp=ts,
                error_msg=f"HTTP {exc.code}: {exc.reason}",
            )
        except urllib.error.URLError as exc:
            return VerificationResult(
                capability_name=self.capability_name,
                passed=False,
                timestamp=ts,
                error_msg=f"URL error: {exc.reason}",
            )
        except OSError as exc:
            return VerificationResult(
                capability_name=self.capability_name,
                passed=False,
                timestamp=ts,
                error_msg=f"OS error: {exc}",
            )

        # Validate response schema
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            return VerificationResult(
                capability_name=self.capability_name,
                passed=False,
                timestamp=ts,
                error_msg=f"Response is not valid JSON: {exc}",
            )

        if self.expected_keys:
            if not isinstance(data, dict):
                return VerificationResult(
                    capability_name=self.capability_name,
                    passed=False,
                    timestamp=ts,
                    error_msg="Response JSON is not an object; cannot check expected_keys.",
                )
            missing = [k for k in self.expected_keys if k not in data]
            if missing:
                return VerificationResult(
                    capability_name=self.capability_name,
                    passed=False,
                    timestamp=ts,
                    error_msg=f"Response missing expected keys: {missing}",
                )

        return VerificationResult(
            capability_name=self.capability_name,
            passed=True,
            timestamp=ts,
        )


# ---------------------------------------------------------------------------
# MockProbe
# ---------------------------------------------------------------------------

class MockProbe(CapabilityProbe):
    """Deterministic probe used for testing.

    Parameters
    ----------
    capability_name:
        Name surfaced in the VerificationResult.
    should_pass:
        When *True* the probe always passes; when *False* it always fails.
    error_msg:
        Message included when the probe is configured to fail.
    """

    name = "mock_probe"
    description = "Deterministic pass/fail probe for unit testing."

    def __init__(
        self,
        capability_name: str,
        should_pass: bool = True,
        error_msg: Optional[str] = None,
    ) -> None:
        self.capability_name = capability_name
        self.should_pass = should_pass
        self._error_msg = error_msg or ("Mock probe configured to fail." if not should_pass else None)

    async def run(self, agent_card: AgentCard) -> VerificationResult:  # noqa: ARG002
        return VerificationResult(
            capability_name=self.capability_name,
            passed=self.should_pass,
            timestamp=datetime.now(timezone.utc),
            error_msg=None if self.should_pass else self._error_msg,
        )


# ---------------------------------------------------------------------------
# EchoProbe
# ---------------------------------------------------------------------------

class EchoProbe(CapabilityProbe):
    """Basic liveness probe: POST a known string, expect it echoed back.

    The request body is ``{"echo": <token>}`` and the probe passes when the
    response contains ``{"echo": <token>}`` (the same value).

    Parameters
    ----------
    capability_name:
        Name surfaced in the VerificationResult.
    token:
        String sent and expected back (default ``"ping"``).
    timeout:
        HTTP timeout in seconds (default 10).
    """

    name = "echo_probe"
    description = (
        "Sends a known string to the agent endpoint and expects it echoed back. "
        "Used for basic liveness verification."
    )

    def __init__(
        self,
        capability_name: str = "liveness",
        token: str = "ping",
        timeout: int = 10,
    ) -> None:
        self.capability_name = capability_name
        self.token = token
        self.timeout = timeout
        # Delegate the HTTP work to an HttpProbe configured for the echo contract.
        self._http_probe = HttpProbe(
            capability_name=capability_name,
            payload={"echo": token},
            expected_keys=["echo"],
            timeout=timeout,
        )

    async def run(self, agent_card: AgentCard) -> VerificationResult:
        result = await self._http_probe.run(agent_card)
        if not result.passed:
            return result

        # Additional check: the echoed value must equal the token we sent.
        loop = asyncio.get_event_loop()
        try:
            actual = await loop.run_in_executor(None, self._fetch_echo_value, agent_card.endpoint)
        except Exception as exc:
            return VerificationResult(
                capability_name=self.capability_name,
                passed=False,
                timestamp=datetime.now(timezone.utc),
                error_msg=f"Echo value check failed: {exc}",
            )
        if actual != self.token:
            return VerificationResult(
                capability_name=self.capability_name,
                passed=False,
                timestamp=datetime.now(timezone.utc),
                error_msg=f"Echo mismatch: sent {self.token!r}, got {actual!r}.",
            )
        return VerificationResult(
            capability_name=self.capability_name,
            passed=True,
            timestamp=datetime.now(timezone.utc),
        )

    def _fetch_echo_value(self, endpoint: str) -> Any:
        """Return the value of the 'echo' key from the agent response."""
        body = json.dumps({"echo": self.token}).encode("utf-8")
        req = urllib.request.Request(
            url=endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("echo")
