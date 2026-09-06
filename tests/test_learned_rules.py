"""Learned rules behave like every other rule: unique evidence or nothing."""

from __future__ import annotations

from datetime import timedelta

from recon.domain.money import split_fees
from recon.knowledge.model import Knowledge, LearnedFact
from recon.matching.learned import (
    match_by_learned_fee_rates,
    match_less_flat_charges,
    match_within_learned_tolerance,
)
from tests.conftest import SETTLED_ON, make_row, make_txn

FACT = LearnedFact("k", 1, 3, ("c",), "note")
GROSS = 1_000_000
STANDARD_NET = split_fees(GROSS, 200, 1_800).net_paise
ACTUAL_NET = split_fees(GROSS, 275, 1_800).net_paise


def test_a_learned_rate_matches_a_settlement_priced_at_that_rate():
    rows = (make_row("setl_1", gross_paise=GROSS, net_paise=STANDARD_NET),)
    txns = (make_txn("bank_1", amount_paise=ACTUAL_NET),)
    knowledge = Knowledge().with_fee_rate(275, FACT)

    proposals = match_by_learned_fee_rates(rows, txns, knowledge)

    assert len(proposals) == 1
    assert proposals[0].bank_txn_ids == frozenset({"bank_1"})


def test_nothing_is_matched_before_a_rate_is_learned():
    rows = (make_row("setl_1", gross_paise=GROSS, net_paise=STANDARD_NET),)
    txns = (make_txn("bank_1", amount_paise=ACTUAL_NET),)
    assert match_by_learned_fee_rates(rows, txns, Knowledge()) == ()


def test_two_equally_good_candidates_are_left_alone():
    rows = (make_row("setl_1", gross_paise=GROSS, net_paise=STANDARD_NET),)
    txns = (
        make_txn("bank_1", amount_paise=ACTUAL_NET),
        make_txn("bank_2", amount_paise=ACTUAL_NET),
    )
    assert match_by_learned_fee_rates(rows, txns, Knowledge().with_fee_rate(275, FACT)) == ()


def test_a_credit_outside_the_settlement_window_is_not_claimed():
    rows = (make_row("setl_1", gross_paise=GROSS, net_paise=STANDARD_NET),)
    txns = (
        make_txn("bank_1", amount_paise=ACTUAL_NET, value_date=SETTLED_ON + timedelta(days=30)),
    )
    assert match_by_learned_fee_rates(rows, txns, Knowledge().with_fee_rate(275, FACT)) == ()


def test_an_approved_tolerance_absorbs_rounding_drift():
    rows = (make_row("setl_1", net_paise=976_360),)
    txns = (make_txn("bank_1", amount_paise=976_353),)
    assert match_within_learned_tolerance(rows, txns, Knowledge()) == ()
    assert (
        len(match_within_learned_tolerance(rows, txns, Knowledge().with_fx_tolerance(10, FACT)))
        == 1
    )


def test_drift_wider_than_the_tolerance_is_still_a_break():
    rows = (make_row("setl_1", net_paise=976_360),)
    txns = (make_txn("bank_1", amount_paise=976_000),)
    assert (
        match_within_learned_tolerance(rows, txns, Knowledge().with_fx_tolerance(10, FACT))
        == ()
    )


def test_a_known_flat_charge_is_absorbed():
    rows = (make_row("setl_1", net_paise=976_360),)
    txns = (make_txn("bank_1", amount_paise=975_180),)
    assert match_less_flat_charges(rows, txns, Knowledge()) == ()
    assert (
        len(match_less_flat_charges(rows, txns, Knowledge().with_flat_charge(1_180, FACT))) == 1
    )


def test_learned_rules_ignore_refund_and_chargeback_rows():
    from recon.domain.models import SettlementRowType

    rows = (make_row("setl_1", net_paise=-1_000, row_type=SettlementRowType.REFUND),)
    txns = (make_txn("bank_1", amount_paise=1_000),)
    assert match_less_flat_charges(rows, txns, Knowledge().with_flat_charge(1_180, FACT)) == ()


def test_two_learned_rates_pointing_at_different_credits_produce_no_match():
    # Arrange: 150 bps and 300 bps are both on file, and the window holds a
    # credit that exactly fits each. Picking either would be a coin flip.
    knowledge = Knowledge().with_fee_rate(150, FACT).with_fee_rate(300, FACT)
    rows = (make_row("setl_1", gross_paise=GROSS, net_paise=STANDARD_NET),)
    txns = (
        make_txn("bank_slow", amount_paise=split_fees(GROSS, 150, 1_800).net_paise),
        make_txn("bank_fast", amount_paise=split_fees(GROSS, 300, 1_800).net_paise),
    )

    # Act
    proposals = match_by_learned_fee_rates(rows, txns, knowledge)

    # Assert
    assert proposals == ()


def test_two_learned_charges_pointing_at_different_credits_produce_no_match():
    knowledge = Knowledge().with_flat_charge(1_180, FACT).with_flat_charge(2_360, FACT)
    rows = (make_row("setl_1", net_paise=976_360),)
    txns = (
        make_txn("bank_a", amount_paise=976_360 - 1_180),
        make_txn("bank_b", amount_paise=976_360 - 2_360),
    )
    assert match_less_flat_charges(rows, txns, knowledge) == ()


def test_two_facts_landing_on_the_same_credit_is_not_ambiguity():
    # A tiny gross rounds two nearby rates onto an identical payout. The link
    # is the same either way, so there is nothing to be ambiguous about.
    gross = 100
    net_at_200 = split_fees(gross, 200, 1_800).net_paise
    assert net_at_200 == split_fees(gross, 201, 1_800).net_paise
    knowledge = Knowledge().with_fee_rate(200, FACT).with_fee_rate(201, FACT)
    rows = (make_row("setl_1", gross_paise=gross, net_paise=999_999),)
    txns = (make_txn("bank_1", amount_paise=net_at_200),)

    assert len(match_by_learned_fee_rates(rows, txns, knowledge)) == 1
