"""The contract every resolver implements.

A resolver takes one exception case and returns a verdict, the tool calls it
made getting there, and what it cost. The deterministic policy and a live
model are interchangeable behind this interface, which is the only reason the
two can be compared on the same eval harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from recon.agent.cost import TokenUsage
from recon.agent.exceptions import ExceptionCase
from recon.agent.schema import AgentVerdict
from recon.agent.tools import ToolCall, ToolContext


@dataclass(frozen=True, slots=True)
class ResolverOutput:
    """Everything one case produced."""

    verdict: AgentVerdict
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0


@runtime_checkable
class ExceptionResolver(Protocol):
    """Anything that can work one case of the exception queue."""

    name: str
    model: str

    def resolve(self, case: ExceptionCase, ctx: ToolContext) -> ResolverOutput: ...
