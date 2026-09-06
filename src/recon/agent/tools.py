"""The tools the exception agent is allowed to call.

Three properties matter and are enforced here rather than in the prompt:

* **Read-only.** No tool mutates the ledger. The agent proposes; the gate and
  the review queue decide.
* **Bounded.** Every search takes a date range and an amount range and returns
  at most `MAX_TOOL_RESULTS` rows, so prompt size and cost cannot run away.
* **Scoped.** Searches see only records the deterministic matcher left open.
  Already-reconciled money is invisible, so it cannot be double-claimed.

The same functions back the deterministic policy and the real model, which is
what makes the two paths comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from recon.agent import config
from recon.agent.index import LedgerIndex
from recon.domain.models import BankTxn, SettlementRow, TxnDirection
from recon.domain.money import BPS_DIVISOR, split_fees
from recon.generator.config import GST_ON_FEE_BPS
from recon.knowledge.model import Knowledge

# Stand-in for "no upper bound", kept an integer so that no comparison in this
# module ever touches a float. Larger than any amount India will settle.
UNBOUNDED_PAISE = 10**18

# How far either side of the estimate to look for a whole basis-point rate that
# reproduces a payout exactly. Rounding moves the estimate by at most a couple.
BPS_SEARCH_RADIUS = 3


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One recorded invocation, kept for the audit trail."""

    name: str
    arguments: dict[str, Any]
    result_count: int
    summary: str


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a tool may see while working one case."""

    index: LedgerIndex
    visible_row_ids: frozenset[str]
    visible_txn_ids: frozenset[str]
    knowledge: Knowledge


def row_view(row: SettlementRow) -> dict[str, Any]:
    return {
        "settlement_row_id": row.settlement_row_id,
        "settlement_id": row.settlement_id,
        "payment_id": row.payment_id,
        "order_id": row.order_id,
        "row_type": row.row_type.value,
        "gross_paise": row.gross_paise,
        "fee_paise": row.fee_paise,
        "tax_paise": row.tax_paise,
        "net_paise": row.net_paise,
        "settled_on": row.settled_on.isoformat(),
        "utr": row.utr,
    }


def txn_view(txn: BankTxn) -> dict[str, Any]:
    return {
        "bank_txn_id": txn.bank_txn_id,
        "utr": txn.utr,
        "amount_paise": txn.amount_paise,
        "direction": txn.direction.value,
        "value_date": txn.value_date.isoformat(),
        "description": txn.description,
    }


def get_settlement_row(ctx: ToolContext, settlement_row_id: str) -> dict[str, Any]:
    """Fetch one open settlement row."""
    if settlement_row_id not in ctx.visible_row_ids:
        return {"error": "not an open settlement row", "id": settlement_row_id}
    row = ctx.index.row(settlement_row_id)
    return row_view(row) if row else {"error": "unknown id", "id": settlement_row_id}


def get_bank_txn(ctx: ToolContext, bank_txn_id: str) -> dict[str, Any]:
    """Fetch one open bank transaction."""
    if bank_txn_id not in ctx.visible_txn_ids:
        return {"error": "not an open bank transaction", "id": bank_txn_id}
    txn = ctx.index.txn(bank_txn_id)
    return txn_view(txn) if txn else {"error": "unknown id", "id": bank_txn_id}


def _is_reachable(ctx: ToolContext, order_id: str) -> bool:
    """True when an open settlement row points at this order."""
    return any(
        row_id in ctx.visible_row_ids for row_id in ctx.index.rows_by_order.get(order_id, ())
    )


def get_order(ctx: ToolContext, order_id: str) -> dict[str, Any]:
    """Fetch an order behind one of the open settlement rows.

    Scoped like every other lookup: an order with nothing open against it is
    already reconciled and is none of the agent's business.
    """
    order = ctx.index.order(order_id)
    if order is None:
        return {"error": "unknown order", "id": order_id}
    if not _is_reachable(ctx, order_id):
        return {"error": "no open settlement row references this order", "id": order_id}
    return {
        "order_id": order.order_id,
        "merchant_id": order.merchant_id,
        "gross_paise": order.gross_paise,
        "currency": order.currency,
        "created_at": order.created_at.isoformat(),
    }


def find_bank_txns(
    ctx: ToolContext,
    *,
    date_from: str,
    date_to: str,
    direction: str = "credit",
    min_paise: int = 0,
    max_paise: int | None = None,
) -> list[dict[str, Any]]:
    """Search open bank transactions inside a date and amount range."""
    window = _parse_window(date_from, date_to)
    wanted = TxnDirection(direction)
    upper = max_paise if max_paise is not None else UNBOUNDED_PAISE
    hits = [
        ctx.index.txns_by_id[txn_id]
        for txn_id in sorted(ctx.visible_txn_ids)
        if _txn_in_range(ctx.index.txns_by_id[txn_id], window, wanted, min_paise, upper)
    ]
    return [txn_view(t) for t in hits[: config.MAX_TOOL_RESULTS]]


def find_settlement_rows(
    ctx: ToolContext,
    *,
    date_from: str,
    date_to: str,
    min_net_paise: int | None = None,
    max_net_paise: int | None = None,
) -> list[dict[str, Any]]:
    """Search open settlement rows inside a date and net-amount range."""
    window = _parse_window(date_from, date_to)
    lower = min_net_paise if min_net_paise is not None else -UNBOUNDED_PAISE
    upper = max_net_paise if max_net_paise is not None else UNBOUNDED_PAISE
    hits = [
        ctx.index.rows_by_id[row_id]
        for row_id in sorted(ctx.visible_row_ids)
        if window[0] <= ctx.index.rows_by_id[row_id].settled_on <= window[1]
        and lower <= ctx.index.rows_by_id[row_id].net_paise <= upper
    ]
    return [row_view(r) for r in hits[: config.MAX_TOOL_RESULTS]]


def fee_schedule(ctx: ToolContext) -> dict[str, Any]:
    """The rates and tolerances currently on file, and where they came from."""
    return {
        "fee_bps_on_file": list(ctx.knowledge.fee_bps_on_file),
        "gst_on_fee_bps": GST_ON_FEE_BPS,
        "fx_tolerance_paise": ctx.knowledge.fx_tolerance_paise,
        "flat_bank_charges_paise": list(ctx.knowledge.flat_bank_charges_paise),
        "learned_facts": [f.note for f in ctx.knowledge.facts],
    }


def expected_net(_ctx: ToolContext, *, gross_paise: int, fee_bps: int) -> dict[str, Any]:
    """Apply the fee schedule forwards: what should a gross amount pay out?"""
    if gross_paise < 0 or fee_bps < 0:
        return {"error": "gross_paise and fee_bps must be non-negative"}
    split = split_fees(gross_paise, fee_bps, GST_ON_FEE_BPS)
    return {
        "gross_paise": split.gross_paise,
        "fee_bps": fee_bps,
        "fee_paise": split.fee_paise,
        "tax_paise": split.tax_paise,
        "net_paise": split.net_paise,
    }


def implied_fee_bps(
    _ctx: ToolContext, *, gross_paise: int, observed_net_paise: int
) -> dict[str, Any]:
    """Apply the fee schedule backwards: what rate would explain this payout?

    Reported only when a whole basis-point rate reproduces the observed net
    exactly. An approximate answer here would be an invitation to rationalise
    any shortfall as a fee, which is precisely the error to avoid.
    """
    if gross_paise <= 0:
        return {"error": "gross_paise must be positive"}
    shortfall = gross_paise - observed_net_paise
    if shortfall < 0:
        return {"exact": False, "reason": "payout exceeds gross"}

    estimate = (shortfall * BPS_DIVISOR) // (
        gross_paise * (BPS_DIVISOR + GST_ON_FEE_BPS) // BPS_DIVISOR or 1
    )
    for bps in range(max(estimate - BPS_SEARCH_RADIUS, 0), estimate + BPS_SEARCH_RADIUS + 1):
        if split_fees(gross_paise, bps, GST_ON_FEE_BPS).net_paise == observed_net_paise:
            return {"exact": True, "fee_bps": bps, "shortfall_paise": shortfall}
    return {
        "exact": False,
        "nearest_fee_bps": estimate,
        "shortfall_paise": shortfall,
        "reason": "no whole basis-point rate reproduces this net exactly",
    }


def check_sum(
    _ctx: ToolContext, *, amounts_paise: list[int], target_paise: int
) -> dict[str, Any]:
    """Add up amounts and report the gap. The agent never does its own arithmetic."""
    total = sum(amounts_paise)
    return {
        "total_paise": total,
        "target_paise": target_paise,
        "residual_paise": target_paise - total,
        "ties_out": total == target_paise,
    }


def _parse_window(date_from: str, date_to: str) -> tuple[date, date]:
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if end < start:
        raise ValueError(f"date_to {date_to} precedes date_from {date_from}")
    return start, end


def _txn_in_range(
    txn: BankTxn,
    window: tuple[date, date],
    direction: TxnDirection,
    min_paise: int,
    max_paise: int,
) -> bool:
    return (
        txn.direction is direction
        and window[0] <= txn.value_date <= window[1]
        and min_paise <= txn.amount_paise <= max_paise
    )


def default_window(anchor: date) -> tuple[str, str]:
    """The standard search window around a settlement date."""
    start = anchor - timedelta(days=config.SEARCH_WINDOW_BEFORE_DAYS)
    end = anchor + timedelta(days=config.SEARCH_WINDOW_AFTER_DAYS)
    return start.isoformat(), end.isoformat()


TOOLS = {
    "get_settlement_row": get_settlement_row,
    "get_bank_txn": get_bank_txn,
    "get_order": get_order,
    "find_bank_txns": find_bank_txns,
    "find_settlement_rows": find_settlement_rows,
    "fee_schedule": fee_schedule,
    "expected_net": expected_net,
    "implied_fee_bps": implied_fee_bps,
    "check_sum": check_sum,
}
