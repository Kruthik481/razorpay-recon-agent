"""Promotion turns confirmed decisions into rules, and refuses to over-reach."""

from __future__ import annotations

from datetime import datetime

from recon.agent.index import build_index
from recon.agent.schema import ResidualReason
from recon.domain.models import Dataset
from recon.domain.money import split_fees
from recon.knowledge.model import Knowledge
from recon.review.decisions import ReviewDecision, ReviewOutcome
from recon.review.promotion import MIN_SUPPORT, promote
from tests.conftest import make_row, make_txn

GROSS = 1_000_000
STANDARD_NET = split_fees(GROSS, 200, 1_800).net_paise
ACTUAL_NET = split_fees(GROSS, 275, 1_800).net_paise


def _fee_fixture(count: int):
    rows = tuple(
        make_row(f"setl_{i}", gross_paise=GROSS, net_paise=STANDARD_NET) for i in range(count)
    )
    txns = tuple(make_txn(f"bank_{i}", amount_paise=ACTUAL_NET) for i in range(count))
    index = build_index(Dataset((), rows, txns, ()))
    decisions = tuple(
        _decision(
            f"case_{i}",
            ResidualReason.FEE_RATE_VARIANCE,
            STANDARD_NET - ACTUAL_NET,
            rows=(f"setl_{i}",),
            txns=(f"bank_{i}",),
        )
        for i in range(count)
    )
    return index, decisions


def _decision(
    case_ref: str,
    reason: ResidualReason,
    residual: int,
    *,
    outcome: ReviewOutcome = ReviewOutcome.CONFIRMED,
    rows: tuple[str, ...] = (),
    txns: tuple[str, ...] = (),
) -> ReviewDecision:
    return ReviewDecision(
        case_ref=case_ref,
        outcome=outcome,
        reviewer="test",
        decided_at=datetime(2026, 9, 6, 12, 0),
        note="",
        settlement_row_ids=rows,
        bank_txn_ids=txns,
        residual_paise=residual,
        residual_reason=reason.value,
        break_type=None,
    )


def test_enough_confirmations_promote_a_fee_rate():
    # Arrange
    index, decisions = _fee_fixture(MIN_SUPPORT)

    # Act
    knowledge, promotions = promote(Knowledge(), decisions, index)

    # Assert
    assert knowledge.fee_bps_on_file == (200, 275)
    assert promotions[0].support == MIN_SUPPORT


def test_one_confirmation_short_promotes_nothing():
    index, decisions = _fee_fixture(MIN_SUPPORT - 1)
    knowledge, promotions = promote(Knowledge(), decisions, index)
    assert promotions == ()
    assert knowledge == Knowledge()


def test_rejected_decisions_teach_nothing():
    index, confirmed = _fee_fixture(MIN_SUPPORT)
    rejected = tuple(
        _decision(
            d.case_ref,
            ResidualReason.FEE_RATE_VARIANCE,
            d.residual_paise,
            outcome=ReviewOutcome.REJECTED,
            rows=d.settlement_row_ids,
            txns=d.bank_txn_ids,
        )
        for d in confirmed
    )
    _, promotions = promote(Knowledge(), rejected, index)
    assert promotions == ()


def test_the_rate_is_re_derived_from_the_ledger_not_taken_on_trust():
    # Arrange: the decision claims a variance, but the amounts actually tie out,
    # so no alternative rate exists to learn.
    rows = tuple(
        make_row(f"setl_{i}", gross_paise=GROSS, net_paise=STANDARD_NET) for i in range(5)
    )
    txns = tuple(make_txn(f"bank_{i}", amount_paise=STANDARD_NET) for i in range(5))
    index = build_index(Dataset((), rows, txns, ()))
    decisions = tuple(
        _decision(
            f"c{i}",
            ResidualReason.FEE_RATE_VARIANCE,
            0,
            rows=(f"setl_{i}",),
            txns=(f"bank_{i}",),
        )
        for i in range(5)
    )

    # Act
    knowledge, _ = promote(Knowledge(), decisions, index)

    # Assert: 200 bps is already on file, so nothing new is learned.
    assert knowledge.fee_bps_on_file == (200,)


def test_a_recurring_identical_shortfall_is_learned_as_a_flat_charge():
    index = build_index(Dataset((), (), (), ()))
    decisions = tuple(
        _decision(f"c{i}", ResidualReason.UNEXPLAINED, 1_180) for i in range(MIN_SUPPORT)
    )
    knowledge, promotions = promote(Knowledge(), decisions, index)
    assert knowledge.flat_bank_charges_paise == (1_180,)
    assert "regardless of size" in promotions[0].note


def test_shortfalls_that_differ_are_not_a_flat_charge():
    index = build_index(Dataset((), (), (), ()))
    decisions = tuple(
        _decision(f"c{i}", ResidualReason.UNEXPLAINED, 1_000 + i) for i in range(MIN_SUPPORT)
    )
    _, promotions = promote(Knowledge(), decisions, index)
    assert promotions == ()


def test_rounding_tolerance_is_set_to_the_widest_confirmed_drift():
    index = build_index(Dataset((), (), (), ()))
    decisions = tuple(
        _decision(f"c{i}", ResidualReason.FX_ROUNDING, drift)
        for i, drift in enumerate((3, 7, 5))
    )
    knowledge, _ = promote(Knowledge(), decisions, index)
    assert knowledge.fx_tolerance_paise == 7


def test_an_implausibly_wide_drift_is_never_promoted():
    index = build_index(Dataset((), (), (), ()))
    decisions = tuple(
        _decision(f"c{i}", ResidualReason.FX_ROUNDING, 50_000) for i in range(MIN_SUPPORT)
    )
    _, promotions = promote(Knowledge(), decisions, index)
    assert promotions == ()


def test_every_promotion_names_the_cases_behind_it():
    index, decisions = _fee_fixture(MIN_SUPPORT)
    _, promotions = promote(Knowledge(), decisions, index)
    assert len(promotions[0].case_refs) == MIN_SUPPORT
