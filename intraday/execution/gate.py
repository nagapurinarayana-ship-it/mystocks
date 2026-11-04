"""Fail-closed execution gate.

There is intentionally no broker order-placement implementation in this release.
"""

from dataclasses import dataclass
from enum import Enum


class ExecutionMode(str, Enum):
    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"


class LiveExecutionDisabledError(RuntimeError):
    """Raised whenever code attempts to reach live broker execution."""


@dataclass(frozen=True)
class ExecutionGate:
    mode: ExecutionMode = ExecutionMode.RESEARCH

    @property
    def live_execution_enabled(self) -> bool:
        # This is a hard-coded safety boundary, not a user-configurable switch.
        return False

    def require_paper_mode(self) -> None:
        if self.mode is not ExecutionMode.PAPER:
            raise LiveExecutionDisabledError("Paper execution requires explicit paper mode")

    def require_live_execution(self) -> None:
        raise LiveExecutionDisabledError(
            "Live broker orders are disabled. Broker selection, compliance review, "
            "security review, paper validation and separate explicit authorisation are required."
        )
