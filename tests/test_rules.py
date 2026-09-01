from datetime import date

from recon.domain.models import BankTxn, SettlementRow, SettlementRowType, TxnDirection
from recon.matching.rules import (
    match_aggregated_payouts,
    match_by_amount_and_date_window,
    match_by_exact_utr,
)

SETTLED_ON = date(2026, 7, 10)


def _row(
    row_id: str,
    net: int,
    utr: str | None,
    settled_on: date = SETTLED_ON,
    settlement_id: str | None = None,
):
    return SettlementRow(
        settlement_row_id=row_id,
        settlement_id=settlement_id or f"batch_{row_id}",
        payment_id=f"pay_{row_id}",
        order_id=f"order_{row_id}",
        row_type=SettlementRowType.PAYMENT,
        gross_paise=net + 236,
        fee_paise=200,
        tax_paise=36,
        net_paise=net,
        settled_on=settled_on,
        utr=utr,
    )


def _credit(txn_id: str, amount: int, utr: str | None, value_date: date = SETTLED_ON):
    return BankTxn(
        bank_txn_id=txn_id,
        utr=utr,
        amount_paise=amount,
        direction=TxnDirection.CREDIT,
        value_date=value_date,
        description="NEFT",
    )


def test_exact_utr_matches_when_reference_and_amount_agree():
    rows = (_row("s1", 10_000, "UTR1"),)
    txns = (_credit("b1", 10_000, "UTR1"),)

    proposals = match_by_exact_utr(rows, txns)

    assert len(proposals) == 1
    assert proposals[0].settlement_row_ids == frozenset({"s1"})
    assert proposals[0].bank_txn_ids == frozenset({"b1"})


def test_exact_utr_abstains_when_amount_disagrees():
    rows = (_row("s1", 10_000, "UTR1"),)
    txns = (_credit("b1", 9_993, "UTR1"),)

    assert match_by_exact_utr(rows, txns) == ()


def test_exact_utr_abstains_when_the_reference_is_reused():
    rows = (_row("s1", 10_000, "DUP"), _row("s2", 20_000, "DUP"))
    txns = (_credit("b1", 10_000, "DUP"), _credit("b2", 20_000, "DUP"))

    assert match_by_exact_utr(rows, txns) == ()


def test_exact_utr_ignores_debits():
    rows = (_row("s1", 10_000, "UTR1"),)
    debit = BankTxn("b1", "UTR1", 10_000, TxnDirection.DEBIT, SETTLED_ON, "CHARGEBACK")

    assert match_by_exact_utr(rows, (debit,)) == ()


def test_amount_window_matches_a_late_credit_inside_the_window():
    rows = (_row("s1", 10_000, None),)
    txns = (_credit("b1", 10_000, None, value_date=date(2026, 7, 13)),)

    proposals = match_by_amount_and_date_window(rows, txns)

    assert len(proposals) == 1


def test_amount_window_abstains_for_a_credit_outside_the_window():
    rows = (_row("s1", 10_000, None),)
    txns = (_credit("b1", 10_000, None, value_date=date(2026, 7, 20)),)

    assert match_by_amount_and_date_window(rows, txns) == ()


def test_amount_window_abstains_when_two_credits_are_equally_plausible():
    rows = (_row("s1", 10_000, None),)
    txns = (_credit("b1", 10_000, None), _credit("b2", 10_000, None))

    assert match_by_amount_and_date_window(rows, txns) == ()


def test_aggregated_payout_matches_a_whole_declared_batch():
    rows = (
        _row("s1", 10_000, None, settlement_id="B1"),
        _row("s2", 20_000, None, settlement_id="B1"),
    )
    txns = (_credit("b1", 30_000, None),)

    proposals = match_aggregated_payouts(rows, txns)

    assert len(proposals) == 1
    assert proposals[0].settlement_row_ids == frozenset({"s1", "s2"})


def test_aggregated_payout_ignores_rows_from_other_batches():
    # s3 would complete a tempting sum, but it belongs to a different payout.
    rows = (
        _row("s1", 10_000, None, settlement_id="B1"),
        _row("s2", 20_000, None, settlement_id="B1"),
        _row("s3", 45_000, None, settlement_id="B2"),
    )
    txns = (_credit("b1", 30_000, None),)

    proposals = match_aggregated_payouts(rows, txns)

    assert len(proposals) == 1
    assert proposals[0].settlement_row_ids == frozenset({"s1", "s2"})


def test_aggregated_payout_matches_a_partially_paid_batch():
    rows = (
        _row("s1", 10_000, None, settlement_id="B1"),
        _row("s2", 20_000, None, settlement_id="B1"),
        _row("s3", 33_333, None, settlement_id="B1"),
    )
    txns = (_credit("b1", 30_000, None),)

    proposals = match_aggregated_payouts(rows, txns)

    assert len(proposals) == 1
    assert proposals[0].settlement_row_ids == frozenset({"s1", "s2"})


def test_aggregated_payout_abstains_when_two_subsets_both_explain_the_credit():
    # s1+s2 and s3+s4 both sum to 30_000: no defensible single answer.
    rows = (
        _row("s1", 10_000, None, settlement_id="B1"),
        _row("s2", 20_000, None, settlement_id="B1"),
        _row("s3", 15_000, None, settlement_id="B1"),
        _row("s4", 15_000, None, settlement_id="B1"),
    )
    txns = (_credit("b1", 30_000, None),)

    assert match_aggregated_payouts(rows, txns) == ()


def test_aggregated_payout_skips_single_row_batches():
    rows = (_row("s1", 30_000, None, settlement_id="B1"),)
    txns = (_credit("b1", 30_000, None),)

    assert match_aggregated_payouts(rows, txns) == ()
