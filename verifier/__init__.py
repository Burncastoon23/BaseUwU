"""
verifier — continuous capability verification layer for the agent registry.

Public surface
--------------
Probes
    CapabilityProbe   abstract base class
    HttpProbe         HTTP POST probe with schema validation
    MockProbe         deterministic pass/fail for testing
    EchoProbe         liveness probe (send string, expect echo)

Suite
    VerificationSuite run probes, track history, derive trust levels

Scheduler
    VerificationScheduler  TTL-based re-verification scheduler
"""

from verifier.probe import (
    CapabilityProbe,
    EchoProbe,
    HttpProbe,
    MockProbe,
)
from verifier.suite import VerificationSuite
from verifier.scheduler import VerificationScheduler

__all__ = [
    "CapabilityProbe",
    "EchoProbe",
    "HttpProbe",
    "MockProbe",
    "VerificationSuite",
    "VerificationScheduler",
]
