"""Resolve exception cases with a live Claude model.

The model gets the same tools as the deterministic policy and answers in the
same shape, so the two are scored by the same harness. Nothing the model says
is trusted directly: the verdict it submits still goes through verification
and the confidence gate before anything is applied.

The SDK is imported lazily and the client can be injected, so this module is
importable — and testable — with no `anthropic` package and no API key.
"""

from __future__ import annotations

import json
import time
from typing import Any

from recon.agent import config
from recon.agent.cost import TokenUsage
from recon.agent.exceptions import ExceptionCase
from recon.agent.prompts import SYSTEM_PROMPT, render_case
from recon.agent.provider import ResolverOutput
from recon.agent.schema import (
    AgentVerdict,
    Evidence,
    ProposedAction,
    ResidualReason,
    abstention,
    break_type_from_name,
)
from recon.agent.tools import TOOLS, ToolCall, ToolContext
from recon.agent.toolspec import ALL_SCHEMAS

DEFAULT_MODEL = "claude-sonnet-5"
MAX_OUTPUT_TOKENS = 1_500
SUBMIT = "submit_verdict"


def _load_client() -> Any:
    """Import the SDK only when a live run is actually attempted."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "the anthropic package is required for live runs: "
            "pip install -e '.[llm]', and set ANTHROPIC_API_KEY"
        ) from exc
    return anthropic.Anthropic()


def dispatch(name: str, arguments: dict[str, Any], ctx: ToolContext) -> Any:
    """Run one tool call, turning any failure into a result the model can read."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return tool(ctx, **arguments)
    except (TypeError, ValueError, KeyError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _evidence(payload: dict[str, Any]) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(kind="record", ref=str(ref), detail="cited by the model")
        for ref in payload.get("cited_record_ids", ())
    )


def build_verdict(case_ref: str, payload: dict[str, Any]) -> AgentVerdict:
    """Convert a submit_verdict payload into a verdict, or an abstention.

    Anything malformed becomes an abstention rather than an exception: a model
    that answers incoherently should lose the case, not stop the run.
    """
    try:
        return AgentVerdict(
            case_ref=case_ref,
            action=ProposedAction(payload["action"]),
            break_type=break_type_from_name(payload.get("break_type")),
            settlement_row_ids=frozenset(payload.get("settlement_row_ids", ())),
            bank_txn_ids=frozenset(payload.get("bank_txn_ids", ())),
            residual_paise=int(payload["residual_paise"]),
            residual_reason=ResidualReason(payload["residual_reason"]),
            confidence=float(payload["confidence"]),
            rationale=str(payload["rationale"]),
            evidence=_evidence(payload),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return abstention(case_ref, f"unusable verdict from the model: {exc}")


def _usage_of(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )


class AnthropicResolver:
    """A tool-calling loop over one exception case."""

    name = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
        max_tool_calls: int = config.MAX_TOOL_CALLS_PER_CASE,
    ) -> None:
        self.model = model
        self._client = client
        self._max_tool_calls = max_tool_calls

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _load_client()
        return self._client

    def resolve(self, case: ExceptionCase, ctx: ToolContext) -> ResolverOutput:
        started = time.perf_counter()
        messages: list[dict[str, Any]] = [{"role": "user", "content": render_case(case, ctx)}]
        calls: tuple[ToolCall, ...] = ()
        usage = TokenUsage()

        for _ in range(self._max_tool_calls + 1):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                tools=list(ALL_SCHEMAS),
                messages=messages,
            )
            usage = usage + _usage_of(response)
            requests = [b for b in response.content if getattr(b, "type", "") == "tool_use"]

            final = next((b for b in requests if b.name == SUBMIT), None)
            if final is not None:
                verdict = build_verdict(case.case_ref, dict(final.input))
                return ResolverOutput(verdict, calls, usage, _elapsed(started))
            if not requests:
                break

            results, calls = self._run_tools(requests, ctx, calls)
            messages = [
                *messages,
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": results},
            ]

        return ResolverOutput(
            abstention(case.case_ref, "the model never submitted a verdict"),
            calls,
            usage,
            _elapsed(started),
        )

    def _run_tools(
        self, requests: list[Any], ctx: ToolContext, calls: tuple[ToolCall, ...]
    ) -> tuple[list[dict[str, Any]], tuple[ToolCall, ...]]:
        results = []
        for block in requests:
            arguments = dict(block.input)
            result = dispatch(block.name, arguments, ctx)
            calls += (
                ToolCall(
                    name=block.name,
                    arguments=arguments,
                    result_count=len(result) if isinstance(result, list) else 1,
                    summary=_summarise(result),
                ),
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                }
            )
        return results, calls


def _summarise(result: Any) -> str:
    if isinstance(result, list):
        return f"{len(result)} records"
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"
    return "1 record"


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
