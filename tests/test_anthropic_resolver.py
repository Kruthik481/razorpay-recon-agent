"""The model path, exercised against a scripted client. No key, no network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from recon.agent.exceptions import ExceptionCase
from recon.agent.providers.anthropic_resolver import (
    AnthropicResolver,
    build_verdict,
    dispatch,
)
from recon.agent.schema import ProposedAction, ResidualReason
from recon.agent.tools import TOOLS
from recon.agent.toolspec import ALL_SCHEMAS, SUBMIT_VERDICT_SCHEMA
from recon.domain.break_types import BreakType
from tests.conftest import make_context, make_row, make_txn


@dataclass
class FakeBlock:
    name: str
    input: dict[str, Any]
    id: str = "toolu_1"
    type: str = "tool_use"


@dataclass
class FakeUsage:
    input_tokens: int = 1_200
    output_tokens: int = 180
    cache_read_input_tokens: int = 0


@dataclass
class FakeResponse:
    content: list[Any]
    usage: FakeUsage = field(default_factory=FakeUsage)
    stop_reason: str = "tool_use"


class FakeMessages:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.messages = FakeMessages(responses)


VERDICT_PAYLOAD = {
    "action": "link",
    "break_type": "refund_netted",
    "settlement_row_ids": ["setl_1"],
    "bank_txn_ids": ["bank_1"],
    "residual_paise": 0,
    "residual_reason": "none",
    "confidence": 0.93,
    "rationale": "the two rows net to the credit",
    "cited_record_ids": ["setl_1", "bank_1"],
}


def _ctx():
    return make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=976_360),),
    )


def _case():
    return ExceptionCase("exc_1", ("setl_1",), (), "test anchor")


def test_a_submitted_verdict_is_returned():
    client = FakeClient([FakeResponse([FakeBlock("submit_verdict", VERDICT_PAYLOAD)])])
    output = AnthropicResolver(client=client).resolve(_case(), _ctx())
    assert output.verdict.action is ProposedAction.LINK
    assert output.verdict.break_type is BreakType.REFUND_NETTED
    assert output.usage.input_tokens == 1_200


def test_tool_calls_are_executed_and_fed_back():
    # Arrange: one search, then the verdict.
    search = FakeBlock(
        "find_bank_txns",
        {"date_from": "2026-07-01", "date_to": "2026-07-31"},
        id="toolu_search",
    )
    client = FakeClient(
        [
            FakeResponse([search]),
            FakeResponse([FakeBlock("submit_verdict", VERDICT_PAYLOAD)]),
        ]
    )

    # Act
    output = AnthropicResolver(client=client).resolve(_case(), _ctx())

    # Assert
    assert [c.name for c in output.tool_calls] == ["find_bank_txns"]
    second_call = client.messages.calls[1]
    assert second_call["messages"][-1]["content"][0]["type"] == "tool_result"


def test_a_model_that_never_answers_abstains():
    client = FakeClient([FakeResponse([])])
    output = AnthropicResolver(client=client).resolve(_case(), _ctx())
    assert output.verdict.action is ProposedAction.NO_ACTION
    assert "never submitted" in output.verdict.rationale


def test_the_tool_call_budget_is_enforced():
    search = FakeBlock("fee_schedule", {})
    client = FakeClient([FakeResponse([search]) for _ in range(5)])
    output = AnthropicResolver(client=client, max_tool_calls=4).resolve(_case(), _ctx())
    assert output.verdict.action is ProposedAction.NO_ACTION
    assert len(client.messages.calls) == 5


def test_a_malformed_verdict_becomes_an_abstention_not_a_crash():
    verdict = build_verdict("exc_1", {"action": "not a real action"})
    assert verdict.action is ProposedAction.NO_ACTION
    assert "unusable verdict" in verdict.rationale


def test_a_verdict_missing_required_fields_becomes_an_abstention():
    assert build_verdict("exc_1", {}).confidence == 0.0


def test_a_well_formed_payload_keeps_its_citations():
    verdict = build_verdict("exc_1", VERDICT_PAYLOAD)
    assert {e.ref for e in verdict.evidence} == {"setl_1", "bank_1"}
    assert verdict.residual_reason is ResidualReason.NONE


def test_an_unknown_tool_name_is_reported_to_the_model():
    assert "unknown tool" in dispatch("not_a_tool", {}, _ctx())["error"]


def test_a_bad_tool_argument_is_reported_rather_than_raised():
    result = dispatch("find_bank_txns", {"date_from": "nonsense", "date_to": "x"}, _ctx())
    assert "error" in result


def test_every_tool_has_a_schema_and_every_schema_has_a_tool():
    schema_names = {s["name"] for s in ALL_SCHEMAS} - {SUBMIT_VERDICT_SCHEMA["name"]}
    assert schema_names == set(TOOLS)


def test_missing_sdk_raises_a_useful_message(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fail(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no module named anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail)
    resolver = AnthropicResolver()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        _ = resolver.client
