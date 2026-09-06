"""Shared machinery for the deterministic policy's probes.

A probe is a small, total function: it either produces a verdict or hands the
case to the next probe, and it records every tool call it made either way.
Keeping the plumbing here lets each probe read as the single question it asks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from recon.agent import config, tools
from recon.agent.exceptions import ExceptionCase
from recon.agent.schema import AgentVerdict, Evidence, ProposedAction, ResidualReason
from recon.agent.tools import ToolCall, ToolContext
from recon.domain.break_types import BreakType
from recon.domain.models import BankTxn, SettlementRow, SettlementRowType
from recon.domain.money import apply_bps

# A drift this small is arithmetic noise worth proposing as a rounding
# difference. Anything larger is a deduction, and deductions need a name.
FX_PROBE_PAISE = 100
MAX_SPLIT_PARTS = 3

Probe = Callable[["Session"], "Outcome"]
Outcome = tuple[AgentVerdict | None, tuple[ToolCall, ...]]


@dataclass(frozen=True, slots=True)
class Session:
    """Immutable working set for one case."""

    ctx: ToolContext
    case: ExceptionCase
    rows: tuple[SettlementRow, ...]
    anchored_txns: tuple[BankTxn, ...]

    @property
    def expected_paise(self) -> int:
        return sum(r.net_paise for r in self.rows)

    @property
    def window(self) -> tuple[str, str]:
        return tools.default_window(min(r.settled_on for r in self.rows))

    @property
    def has_refund(self) -> bool:
        return any(r.row_type is SettlementRowType.REFUND for r in self.rows)


def record_call(name: str, arguments: dict[str, Any], result: Any, summary: str) -> ToolCall:
    count = len(result) if isinstance(result, list) else 1
    return ToolCall(name=name, arguments=arguments, result_count=count, summary=summary)


def search_credits(
    session: Session, *, min_paise: int, max_paise: int | None
) -> tuple[list[dict], ToolCall]:
    date_from, date_to = session.window
    args = {
        "date_from": date_from,
        "date_to": date_to,
        "direction": "credit",
        "min_paise": min_paise,
        "max_paise": max_paise,
    }
    hits = tools.find_bank_txns(session.ctx, **args)
    return hits, record_call(
        "find_bank_txns", args, hits, f"{len(hits)} open credits in window"
    )


def link_verdict(
    session: Session,
    *,
    txn_ids: frozenset[str],
    break_type: BreakType | None,
    residual: int,
    reason: ResidualReason,
    confidence: float,
    rationale: str,
    evidence: tuple[Evidence, ...] = (),
) -> AgentVerdict:
    return AgentVerdict(
        case_ref=session.case.case_ref,
        action=ProposedAction.LINK,
        break_type=break_type,
        settlement_row_ids=frozenset(r.settlement_row_id for r in session.rows),
        bank_txn_ids=txn_ids,
        residual_paise=residual,
        residual_reason=reason,
        confidence=confidence,
        rationale=rationale,
        evidence=evidence,
    )


def cite(*ids: str) -> tuple[Evidence, ...]:
    return tuple(Evidence(kind="record", ref=i, detail="cited in tie-out") for i in ids)


def fee_band(gross: int) -> tuple[int, int]:
    """Net amounts consistent with any plausible merchant discount rate."""
    lower = tools.expected_net(None, gross_paise=gross, fee_bps=config.MAX_PLAUSIBLE_FEE_BPS)
    upper = tools.expected_net(None, gross_paise=gross, fee_bps=config.MIN_PLAUSIBLE_FEE_BPS)
    return lower["net_paise"], upper["net_paise"]


def plausible_sources(session: Session) -> tuple[list[dict], ToolCall]:
    """Open settlement rows that could have produced this credit.

    The question is deliberately loose. A row whose net is *higher* than the
    credit is still a candidate, because something may have been held back on
    the way to the bank. Asking only for an exact match would let any deduction
    at all masquerade as an unidentified receipt.
    """
    txn = session.anchored_txns[0]
    date_from, date_to = tools.default_window(txn.value_date)
    ceiling = (
        txn.amount_paise
        + apply_bps(txn.amount_paise, config.MAX_DEDUCTION_BPS)
        + config.MATERIALITY_PAISE
    )
    args = {
        "date_from": date_from,
        "date_to": date_to,
        "min_net_paise": txn.amount_paise,
        "max_net_paise": ceiling,
    }
    hits = tools.find_settlement_rows(session.ctx, **args)
    return hits, record_call(
        "find_settlement_rows", args, hits, f"{len(hits)} possible sources"
    )
