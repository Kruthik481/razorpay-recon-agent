"""One builder per break type.

Every builder is a pure function of its context: same context in, same
records out. That determinism is what makes the eval harness meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from random import Random

from recon.domain.break_types import BreakType
from recon.domain.models import (
    BankTxn,
    GroundTruthLink,
    Order,
    SettlementRow,
    SettlementRowType,
    TxnDirection,
)
from recon.domain.money import apply_bps, split_fees
from recon.generator import config


@dataclass(frozen=True, slots=True)
class ScenarioContext:
    """Everything a builder needs, with no shared mutable state."""

    index: int
    rng: Random
    period_start: date
    break_type: BreakType


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    orders: tuple[Order, ...]
    settlement_rows: tuple[SettlementRow, ...]
    bank_txns: tuple[BankTxn, ...]
    link: GroundTruthLink


def _case_id(ctx: ScenarioContext) -> str:
    return f"case_{ctx.index:05d}"


def _utr(ctx: ScenarioContext, suffix: str = "0") -> str:
    return f"UTR{ctx.index:06d}{suffix}"


def _captured_on(ctx: ScenarioContext) -> date:
    offset = ctx.rng.randrange(config.PERIOD_DAYS)
    return ctx.period_start + timedelta(days=offset)


def _gross(ctx: ScenarioContext) -> int:
    return ctx.rng.randrange(config.MIN_ORDER_PAISE, config.MAX_ORDER_PAISE)


def _order(ctx: ScenarioContext, gross_paise: int, captured_on: date, seq: int = 0) -> Order:
    return Order(
        order_id=f"order_{ctx.index:05d}_{seq}",
        merchant_id=config.MERCHANT_ID,
        gross_paise=gross_paise,
        currency=config.CURRENCY,
        created_at=datetime.combine(captured_on, datetime.min.time()),
    )


def _settlement_id(ctx: ScenarioContext, seq: int = 0) -> str:
    """Batch identifier as published in the PSP settlement report."""
    return f"setl_batch_{ctx.index:05d}_{seq}"


def _payment_row(
    ctx: ScenarioContext,
    order: Order,
    settled_on: date,
    *,
    utr: str | None,
    fee_bps: int = config.STANDARD_FEE_BPS,
    seq: int = 0,
    settlement_id: str | None = None,
) -> SettlementRow:
    fees = split_fees(order.gross_paise, fee_bps, config.GST_ON_FEE_BPS)
    return SettlementRow(
        settlement_row_id=f"setl_{ctx.index:05d}_{seq}",
        settlement_id=settlement_id or _settlement_id(ctx, seq),
        payment_id=f"pay_{ctx.index:05d}_{seq}",
        order_id=order.order_id,
        row_type=SettlementRowType.PAYMENT,
        gross_paise=fees.gross_paise,
        fee_paise=fees.fee_paise,
        tax_paise=fees.tax_paise,
        net_paise=fees.net_paise,
        settled_on=settled_on,
        utr=utr,
    )


def _credit(
    ctx: ScenarioContext,
    amount_paise: int,
    value_date: date,
    *,
    utr: str | None,
    seq: int = 0,
    description: str = "NEFT PSP SETTLEMENT",
) -> BankTxn:
    return BankTxn(
        bank_txn_id=f"bank_{ctx.index:05d}_{seq}",
        utr=utr,
        amount_paise=amount_paise,
        direction=TxnDirection.CREDIT,
        value_date=value_date,
        description=description,
    )


def _link(
    ctx: ScenarioContext,
    orders: tuple[Order, ...],
    rows: tuple[SettlementRow, ...],
    txns: tuple[BankTxn, ...],
) -> GroundTruthLink:
    return GroundTruthLink(
        case_id=_case_id(ctx),
        break_type=ctx.break_type,
        settlement_row_ids=tuple(r.settlement_row_id for r in rows),
        bank_txn_ids=tuple(t.bank_txn_id for t in txns),
        order_ids=tuple(o.order_id for o in orders),
    )


def _single(
    ctx: ScenarioContext, order: Order, row: SettlementRow, txns: tuple[BankTxn, ...]
) -> ScenarioResult:
    orders, rows = (order,), (row,)
    return ScenarioResult(orders, rows, txns, _link(ctx, orders, rows, txns))


def _simple_settled(ctx: ScenarioContext, *, lag_days: int, utr: str | None) -> ScenarioResult:
    """Shared shape: one order, one settlement row, one exactly-equal credit."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=lag_days)
    order = _order(ctx, _gross(ctx), captured_on)
    row = _payment_row(ctx, order, settled_on, utr=utr)
    credit = _credit(ctx, row.net_paise, settled_on, utr=utr)
    return _single(ctx, order, row, (credit,))


def build_clean(ctx: ScenarioContext) -> ScenarioResult:
    """UTR present on both sides, amounts agree. The 58% case."""
    return _simple_settled(ctx, lag_days=config.STANDARD_SETTLEMENT_LAG_DAYS, utr=_utr(ctx))


def build_fee_netting(ctx: ScenarioContext) -> ScenarioResult:
    """Bank credit is net of MDR + GST, so it never equals the order gross.

    Trips up anyone matching on gross; trivial once you compare on net.
    """
    return _simple_settled(ctx, lag_days=config.STANDARD_SETTLEMENT_LAG_DAYS, utr=_utr(ctx))


def build_settlement_lag(ctx: ScenarioContext) -> ScenarioResult:
    """Credit lands T+3, crossing the reporting window boundary."""
    return _simple_settled(ctx, lag_days=config.LATE_SETTLEMENT_LAG_DAYS, utr=_utr(ctx))


def build_missing_utr(ctx: ScenarioContext) -> ScenarioResult:
    """PSP report omits the UTR — must fall back to amount plus date window."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    order = _order(ctx, _gross(ctx), captured_on)
    row = _payment_row(ctx, order, settled_on, utr=None)
    credit = _credit(ctx, row.net_paise, settled_on, utr=None)
    return _single(ctx, order, row, (credit,))


def build_aggregated_payout(ctx: ScenarioContext) -> ScenarioResult:
    """N settlement rows paid out as one consolidated bank credit."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    orders = tuple(
        _order(ctx, _gross(ctx), captured_on, seq=seq)
        for seq in range(config.AGGREGATED_BATCH_SIZE)
    )
    batch_id = _settlement_id(ctx)
    rows = tuple(
        _payment_row(ctx, order, settled_on, utr=None, seq=seq, settlement_id=batch_id)
        for seq, order in enumerate(orders)
    )
    total = sum(row.net_paise for row in rows)
    credit = _credit(ctx, total, settled_on, utr=_utr(ctx), description="NEFT PSP PAYOUT BATCH")
    txns = (credit,)
    return ScenarioResult(orders, rows, txns, _link(ctx, orders, rows, txns))


def build_non_standard_fee(ctx: ScenarioContext) -> ScenarioResult:
    """Merchant is on a renegotiated rate the recon config still has as 2%.

    Amounts will not tie out against the expected fee schedule.
    """
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    order = _order(ctx, _gross(ctx), captured_on)
    row = _payment_row(ctx, order, settled_on, utr=None)
    actual = split_fees(order.gross_paise, config.NON_STANDARD_FEE_BPS, config.GST_ON_FEE_BPS)
    credit = _credit(ctx, actual.net_paise, settled_on, utr=None)
    return _single(ctx, order, row, (credit,))


def build_partial_settlement(ctx: ScenarioContext) -> ScenarioResult:
    """One settlement row arrives as two separate bank credits."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    order = _order(ctx, _gross(ctx), captured_on)
    row = _payment_row(ctx, order, settled_on, utr=None)
    first = apply_bps(row.net_paise, config.PARTIAL_FIRST_TRANCHE_BPS)
    txns = (
        _credit(ctx, first, settled_on, utr=None, seq=0),
        _credit(ctx, row.net_paise - first, settled_on + timedelta(days=1), utr=None, seq=1),
    )
    return _single(ctx, order, row, txns)


def build_refund_netted(ctx: ScenarioContext) -> ScenarioResult:
    """A refund is deducted from the same day's payout instead of debited."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    order = _order(ctx, _gross(ctx), captured_on)
    payment = _payment_row(ctx, order, settled_on, utr=None, seq=0)
    refund_amount = apply_bps(order.gross_paise, config.REFUND_FRACTION_BPS)
    refund = SettlementRow(
        settlement_row_id=f"setl_{ctx.index:05d}_1",
        settlement_id=_settlement_id(ctx, 1),
        payment_id=f"pay_{ctx.index:05d}_0",
        order_id=order.order_id,
        row_type=SettlementRowType.REFUND,
        gross_paise=refund_amount,
        fee_paise=0,
        tax_paise=0,
        net_paise=-refund_amount,
        settled_on=settled_on,
        utr=None,
    )
    credit = _credit(ctx, payment.net_paise - refund_amount, settled_on, utr=None)
    orders, rows, txns = (order,), (payment, refund), (credit,)
    return ScenarioResult(orders, rows, txns, _link(ctx, orders, rows, txns))


def build_chargeback_debit(ctx: ScenarioContext) -> ScenarioResult:
    """A debit hits the account with no corresponding order in the ledger."""
    settled_on = _captured_on(ctx)
    amount = _gross(ctx)
    row = SettlementRow(
        settlement_row_id=f"setl_{ctx.index:05d}_0",
        settlement_id=_settlement_id(ctx),
        payment_id=f"pay_{ctx.index:05d}_0",
        order_id=None,
        row_type=SettlementRowType.CHARGEBACK,
        gross_paise=amount,
        fee_paise=0,
        tax_paise=0,
        net_paise=-amount,
        settled_on=settled_on,
        utr=None,
    )
    debit = BankTxn(
        bank_txn_id=f"bank_{ctx.index:05d}_0",
        utr=None,
        amount_paise=amount,
        direction=TxnDirection.DEBIT,
        value_date=settled_on,
        description="CHARGEBACK RECOVERY",
    )
    rows, txns = (row,), (debit,)
    return ScenarioResult((), rows, txns, _link(ctx, (), rows, txns))


def build_fx_rounding(ctx: ScenarioContext) -> ScenarioResult:
    """Credit is off by a few paise from cross-currency rounding."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    order = _order(ctx, _gross(ctx), captured_on)
    row = _payment_row(ctx, order, settled_on, utr=None)
    credit = _credit(ctx, row.net_paise - config.FX_ROUNDING_DRIFT_PAISE, settled_on, utr=None)
    return _single(ctx, order, row, (credit,))


def build_duplicate_utr(ctx: ScenarioContext) -> ScenarioResult:
    """Two settlement rows carry the same UTR — the reference is ambiguous."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    shared = _utr(ctx)
    # Identical amounts as well as identical UTR. With differing amounts the
    # rules engine can still separate them, and this stops being a break.
    shared_gross = _gross(ctx)
    orders = tuple(_order(ctx, shared_gross, captured_on, seq=seq) for seq in range(2))
    rows = tuple(
        _payment_row(ctx, order, settled_on, utr=shared, seq=seq)
        for seq, order in enumerate(orders)
    )
    txns = tuple(
        _credit(ctx, row.net_paise, settled_on, utr=shared, seq=seq)
        for seq, row in enumerate(rows)
    )
    return ScenarioResult(orders, rows, txns, _link(ctx, orders, rows, txns))


def build_missing_in_bank(ctx: ScenarioContext) -> ScenarioResult:
    """Settled per the PSP, but the money never arrived. A true break."""
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    order = _order(ctx, _gross(ctx), captured_on)
    row = _payment_row(ctx, order, settled_on, utr=_utr(ctx))
    return _single(ctx, order, row, ())


def build_unknown_credit(ctx: ScenarioContext) -> ScenarioResult:
    """Money arrived with no settlement row to explain it."""
    value_date = _captured_on(ctx)
    credit = _credit(
        ctx, _gross(ctx), value_date, utr=_utr(ctx), description="NEFT INWARD UNIDENTIFIED"
    )
    txns = (credit,)
    return ScenarioResult((), (), txns, _link(ctx, (), (), txns))


def build_bank_charge_netted(ctx: ScenarioContext) -> ScenarioResult:
    """The bank takes a flat remittance charge out of the credit.

    Deliberately not proportional to the amount: a matcher that only knows how
    to reason about fee *rates* cannot explain a constant deduction, so this
    case exercises the escalation path rather than a rule.
    """
    captured_on = _captured_on(ctx)
    settled_on = captured_on + timedelta(days=config.STANDARD_SETTLEMENT_LAG_DAYS)
    order = _order(ctx, _gross(ctx), captured_on)
    row = _payment_row(ctx, order, settled_on, utr=None)
    credit = _credit(
        ctx,
        row.net_paise - config.BANK_REMITTANCE_CHARGE_PAISE,
        settled_on,
        utr=None,
        description="NEFT PSP SETTLEMENT LESS CHARGES",
    )
    return _single(ctx, order, row, (credit,))


SCENARIO_BUILDERS = {
    BreakType.CLEAN: build_clean,
    BreakType.FEE_NETTING: build_fee_netting,
    BreakType.SETTLEMENT_LAG: build_settlement_lag,
    BreakType.MISSING_UTR: build_missing_utr,
    BreakType.AGGREGATED_PAYOUT: build_aggregated_payout,
    BreakType.NON_STANDARD_FEE: build_non_standard_fee,
    BreakType.PARTIAL_SETTLEMENT: build_partial_settlement,
    BreakType.REFUND_NETTED: build_refund_netted,
    BreakType.CHARGEBACK_DEBIT: build_chargeback_debit,
    BreakType.FX_ROUNDING: build_fx_rounding,
    BreakType.DUPLICATE_UTR: build_duplicate_utr,
    BreakType.MISSING_IN_BANK: build_missing_in_bank,
    BreakType.UNKNOWN_CREDIT: build_unknown_credit,
    BreakType.BANK_CHARGE_NETTED: build_bank_charge_netted,
}
