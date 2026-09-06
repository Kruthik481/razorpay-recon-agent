"""The deterministic policy proposes only what the evidence identifies."""

from __future__ import annotations

from datetime import timedelta

from recon.agent.exceptions import ExceptionCase
from recon.agent.providers.deterministic import DeterministicPolicy
from recon.agent.schema import ProposedAction, ResidualReason
from recon.domain.break_types import BreakType
from recon.domain.models import SettlementRowType, TxnDirection
from recon.domain.money import split_fees
from recon.knowledge.model import Knowledge, LearnedFact
from tests.conftest import SETTLED_ON, make_context, make_order, make_row, make_txn

POLICY = DeterministicPolicy()
FACT = LearnedFact("fee_rate_bps", 275, 5, ("c",), "note")


def _case(rows=(), txns=()) -> ExceptionCase:
    return ExceptionCase("exc_t", rows, txns, "test anchor")


def test_a_refund_netted_against_a_payout_ties_out_exactly():
    # Arrange: payment less refund equals the single credit.
    payment = make_row("setl_pay", net_paise=976_360)
    refund = make_row("setl_ref", net_paise=-300_000, row_type=SettlementRowType.REFUND)
    credit = make_txn("bank_1", amount_paise=676_360)
    ctx = make_context(rows=(payment, refund), txns=(credit,))

    # Act
    output = POLICY.resolve(_case(("setl_pay", "setl_ref")), ctx)

    # Assert
    assert output.verdict.action is ProposedAction.LINK
    assert output.verdict.break_type is BreakType.REFUND_NETTED
    assert output.verdict.residual_paise == 0
    assert output.verdict.bank_txn_ids == frozenset({"bank_1"})


def test_two_credits_that_uniquely_sum_to_the_payout_are_a_split():
    row = make_row("setl_1", net_paise=1_000_000)
    ctx = make_context(
        rows=(row,),
        txns=(
            make_txn("bank_a", amount_paise=600_000),
            make_txn("bank_b", amount_paise=400_000, value_date=SETTLED_ON + timedelta(days=1)),
        ),
    )
    verdict = POLICY.resolve(_case(("setl_1",)), ctx).verdict
    assert verdict.break_type is BreakType.PARTIAL_SETTLEMENT
    assert verdict.bank_txn_ids == frozenset({"bank_a", "bank_b"})


def test_a_chargeback_is_answered_by_a_debit_of_the_same_size():
    row = make_row("setl_cb", net_paise=-500_000, row_type=SettlementRowType.CHARGEBACK)
    ctx = make_context(
        rows=(row,),
        txns=(make_txn("bank_d", amount_paise=500_000, direction=TxnDirection.DEBIT),),
    )
    verdict = POLICY.resolve(_case(("setl_cb",)), ctx).verdict
    assert verdict.break_type is BreakType.CHARGEBACK_DEBIT
    assert verdict.residual_paise == 0


def test_an_unfamiliar_fee_rate_is_proposed_but_flagged_as_not_on_file():
    gross = 1_000_000
    row = make_row(
        "setl_1", gross_paise=gross, net_paise=split_fees(gross, 200, 1_800).net_paise
    )
    credit = make_txn("bank_1", amount_paise=split_fees(gross, 275, 1_800).net_paise)
    ctx = make_context(rows=(row,), txns=(credit,), orders=(make_order(),))

    verdict = POLICY.resolve(_case(("setl_1",)), ctx).verdict

    assert verdict.break_type is BreakType.NON_STANDARD_FEE
    assert verdict.residual_reason is ResidualReason.FEE_RATE_VARIANCE
    assert verdict.confidence < 0.85
    assert "not on file" in verdict.rationale


def test_a_learned_fee_rate_raises_the_policy_confidence():
    gross = 1_000_000
    row = make_row(
        "setl_1", gross_paise=gross, net_paise=split_fees(gross, 200, 1_800).net_paise
    )
    credit = make_txn("bank_1", amount_paise=split_fees(gross, 275, 1_800).net_paise)
    ctx = make_context(
        rows=(row,), txns=(credit,), knowledge=Knowledge().with_fee_rate(275, FACT)
    )
    assert POLICY.resolve(_case(("setl_1",)), ctx).verdict.confidence >= 0.85


def test_a_few_paise_short_is_proposed_as_a_rounding_difference():
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=976_353),),
    )
    verdict = POLICY.resolve(_case(("setl_1",)), ctx).verdict
    assert verdict.break_type is BreakType.FX_ROUNDING
    assert verdict.residual_paise == 7


def test_a_settled_reference_the_bank_never_saw_is_flagged_as_missing():
    ctx = make_context(rows=(make_row("setl_1", utr="UTR_ABSENT"),))
    verdict = POLICY.resolve(_case(("setl_1",)), ctx).verdict
    assert verdict.action is ProposedAction.FLAG_MISSING_CREDIT
    assert verdict.break_type is BreakType.MISSING_IN_BANK
    assert verdict.bank_txn_ids == frozenset()


def test_a_credit_no_open_row_explains_is_flagged_as_unidentified():
    ctx = make_context(txns=(make_txn("bank_1", amount_paise=123_456),))
    verdict = POLICY.resolve(_case((), ("bank_1",)), ctx).verdict
    assert verdict.action is ProposedAction.FLAG_UNIDENTIFIED_CREDIT
    assert verdict.break_type is BreakType.UNKNOWN_CREDIT
    assert verdict.residual_paise == -123_456


def test_records_sharing_a_utr_that_balance_as_a_group_are_never_auto_applied():
    rows = (
        make_row("setl_a", net_paise=500_000, utr="UTR_DUP"),
        make_row("setl_b", net_paise=500_000, utr="UTR_DUP"),
    )
    txns = (
        make_txn("bank_a", amount_paise=500_000, utr="UTR_DUP"),
        make_txn("bank_b", amount_paise=500_000, utr="UTR_DUP"),
    )
    ctx = make_context(rows=rows, txns=txns)
    verdict = POLICY.resolve(_case(("setl_a", "setl_b"), ("bank_a", "bank_b")), ctx).verdict
    assert verdict.break_type is BreakType.DUPLICATE_UTR
    assert verdict.residual_paise == 0
    assert verdict.confidence < 0.85


def test_a_deduction_the_policy_cannot_name_is_left_unexplained():
    # A flat charge is not proportional, so no fee rate reasoning reaches it.
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360, gross_paise=1_000_000),),
        txns=(make_txn("bank_1", amount_paise=975_180),),
        orders=(make_order(),),
    )
    verdict = POLICY.resolve(_case(("setl_1",)), ctx).verdict
    assert verdict.residual_reason is ResidualReason.UNEXPLAINED
    assert verdict.residual_paise == 1_180
    assert verdict.confidence < 0.5


def test_two_identical_candidate_credits_produce_no_answer():
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(
            make_txn("bank_a", amount_paise=976_360),
            make_txn("bank_b", amount_paise=976_360),
        ),
    )
    verdict = POLICY.resolve(_case(("setl_1",)), ctx).verdict
    assert verdict.action is ProposedAction.NO_ACTION
    assert verdict.confidence == 0.0


def test_every_answer_carries_its_tool_calls():
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=976_360),),
    )
    output = POLICY.resolve(_case(("setl_1",)), ctx)
    assert output.tool_calls
    assert all(call.name for call in output.tool_calls)


def test_a_credit_short_by_a_deduction_is_not_called_unidentified():
    # Arrange: the only open row could have produced this credit, minus a
    # flat charge. Calling it "money from nowhere" would be a wrong posting.
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=975_180),),
    )

    # Act
    verdict = POLICY.resolve(_case((), ("bank_1",)), ctx).verdict

    # Assert
    assert verdict.action is ProposedAction.LINK
    assert verdict.settlement_row_ids == frozenset({"setl_1"})
    assert verdict.residual_reason is ResidualReason.UNEXPLAINED
    assert verdict.confidence < 0.5


def test_a_credit_no_row_could_have_produced_is_still_flagged():
    # A credit larger than every open row cannot be a shortfall of any of them.
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=10_000),),
        txns=(make_txn("bank_1", amount_paise=9_000_000),),
    )
    verdict = POLICY.resolve(_case((), ("bank_1",)), ctx).verdict
    assert verdict.action is ProposedAction.FLAG_UNIDENTIFIED_CREDIT


def test_two_possible_sources_produce_no_answer_for_an_orphan_credit():
    ctx = make_context(
        rows=(
            make_row("setl_1", net_paise=976_360),
            make_row("setl_2", net_paise=976_400),
        ),
        txns=(make_txn("bank_1", amount_paise=975_180),),
    )
    verdict = POLICY.resolve(_case((), ("bank_1",)), ctx).verdict
    assert verdict.action is ProposedAction.NO_ACTION
