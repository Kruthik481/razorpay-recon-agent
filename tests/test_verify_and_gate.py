"""The verifier catches what a model gets wrong; the gate decides what may post."""

from __future__ import annotations

from recon.agent import config
from recon.agent.gate import gate
from recon.agent.schema import (
    AgentVerdict,
    Disposition,
    Evidence,
    ProposedAction,
    ResidualReason,
    abstention,
    break_type_from_name,
)
from recon.agent.verify import compute_residual, verify
from recon.domain.break_types import BreakType
from recon.domain.models import SettlementRowType, TxnDirection
from recon.domain.money import split_fees
from recon.knowledge.model import Knowledge, LearnedFact
from tests.conftest import make_context, make_order, make_row, make_txn

FACT = LearnedFact("fee_rate_bps", 275, 5, ("c",), "note")


def _link(**overrides) -> AgentVerdict:
    base = {
        "case_ref": "exc_1",
        "action": ProposedAction.LINK,
        "break_type": BreakType.REFUND_NETTED,
        "settlement_row_ids": frozenset({"setl_1"}),
        "bank_txn_ids": frozenset({"bank_1"}),
        "residual_paise": 0,
        "residual_reason": ResidualReason.NONE,
        "confidence": 0.95,
        "rationale": "amounts tie out",
    }
    return AgentVerdict(**{**base, **overrides})


def _clean_context(knowledge: Knowledge | None = None):
    return make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=976_360),),
        orders=(make_order(),),
        knowledge=knowledge,
    )


def test_a_clean_link_passes_verification():
    assert verify(_link(), _clean_context()) == ()


def test_a_hallucinated_record_id_voids_the_verdict():
    # Arrange
    ctx = _clean_context()

    # Act
    violations = verify(_link(bank_txn_ids=frozenset({"bank_invented"})), ctx)

    # Assert
    assert violations == ("bank transaction not open: bank_invented",)


def test_a_misstated_residual_is_caught_against_the_ledger():
    ctx = _clean_context()
    violations = verify(_link(residual_paise=500), ctx)
    assert any("ledger says 0" in v for v in violations)


def test_declaring_a_residual_fully_explained_when_it_is_not_is_caught():
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=900_000),),
    )
    violations = verify(_link(residual_paise=76_360), ctx)
    assert any("declared as fully explained" in v for v in violations)


def test_a_link_must_name_both_sides():
    ctx = _clean_context()
    violations = verify(_link(bank_txn_ids=frozenset()), ctx)
    assert any("at least one settlement row and one bank" in v for v in violations)


def test_a_missing_credit_flag_may_not_cite_a_bank_transaction():
    ctx = _clean_context()
    violations = verify(
        _link(
            action=ProposedAction.FLAG_MISSING_CREDIT,
            residual_paise=0,
            residual_reason=ResidualReason.UNRECONCILED_FUNDS,
        ),
        ctx,
    )
    assert any("no bank transaction" in v for v in violations)


def test_an_unidentified_credit_flag_may_not_cite_a_settlement_row():
    ctx = _clean_context()
    violations = verify(
        _link(
            action=ProposedAction.FLAG_UNIDENTIFIED_CREDIT,
            residual_reason=ResidualReason.UNRECONCILED_FUNDS,
        ),
        ctx,
    )
    assert any("no settlement row" in v for v in violations)


def test_an_evidence_citation_to_a_nonexistent_record_is_caught():
    ctx = _clean_context()
    violations = verify(_link(evidence=(Evidence("record", "setl_ghost", "d"),)), ctx)
    assert any("unknown record" in v for v in violations)


def test_confidence_outside_zero_to_one_is_caught():
    assert any(
        "confidence out of range" in v for v in verify(_link(confidence=1.4), _clean_context())
    )


def test_a_debit_reduces_the_bank_side_of_the_residual():
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=-500_000, row_type=SettlementRowType.CHARGEBACK),),
        txns=(make_txn("bank_1", amount_paise=500_000, direction=TxnDirection.DEBIT),),
    )
    assert compute_residual(ctx, _link()) == 0


def test_a_clean_confident_link_auto_applies():
    decision = gate(_link(), _clean_context())
    assert decision.disposition is Disposition.AUTO_APPLY
    assert decision.is_auto_applied


def test_a_confident_link_that_fails_verification_is_escalated():
    decision = gate(_link(residual_paise=99), _clean_context())
    assert decision.disposition is Disposition.ESCALATE
    assert decision.violations


def test_an_abstention_never_auto_applies():
    decision = gate(abstention("exc_1", "ambiguous"), _clean_context())
    assert decision.disposition is Disposition.ESCALATE
    assert decision.gate_reasons == ("agent asserted nothing",)


def test_a_correct_link_below_the_auto_threshold_goes_to_review():
    decision = gate(_link(confidence=config.AUTO_APPLY_CONFIDENCE - 0.01), _clean_context())
    assert decision.disposition is Disposition.NEEDS_REVIEW


def test_a_rounding_difference_is_blocked_until_a_tolerance_is_on_file():
    # Arrange: seven paise short, and no tolerance approved yet.
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=976_353),),
    )
    verdict = _link(residual_paise=7, residual_reason=ResidualReason.FX_ROUNDING)

    # Act
    blocked = gate(verdict, ctx)
    allowed = gate(
        verdict,
        make_context(
            rows=(make_row("setl_1", net_paise=976_360),),
            txns=(make_txn("bank_1", amount_paise=976_353),),
            knowledge=Knowledge().with_fx_tolerance(10, FACT),
        ),
    )

    # Assert
    assert blocked.disposition is Disposition.NEEDS_REVIEW
    assert allowed.disposition is Disposition.AUTO_APPLY


def test_a_fee_rate_not_on_file_is_never_applied_automatically():
    gross = 1_000_000
    standard = split_fees(gross, 200, 1_800).net_paise
    actual = split_fees(gross, 275, 1_800).net_paise
    rows = (make_row("setl_1", net_paise=standard, gross_paise=gross),)
    txns = (make_txn("bank_1", amount_paise=actual),)
    verdict = _link(
        residual_paise=standard - actual,
        residual_reason=ResidualReason.FEE_RATE_VARIANCE,
        confidence=0.99,
    )

    blocked = gate(verdict, make_context(rows=rows, txns=txns))
    allowed = gate(
        verdict,
        make_context(rows=rows, txns=txns, knowledge=Knowledge().with_fee_rate(275, FACT)),
    )

    assert blocked.disposition is Disposition.NEEDS_REVIEW
    assert "not on file" in blocked.gate_reasons[0]
    assert allowed.disposition is Disposition.AUTO_APPLY


def test_a_large_residual_never_auto_applies_however_confident():
    shortfall = config.MATERIALITY_PAISE + 1
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=976_360 - shortfall),),
        knowledge=Knowledge().with_flat_charge(shortfall, FACT),
    )
    decision = gate(
        _link(
            residual_paise=shortfall,
            residual_reason=ResidualReason.FLAT_BANK_CHARGE,
            confidence=1.0,
        ),
        ctx,
    )
    assert decision.disposition is Disposition.NEEDS_REVIEW
    assert "materiality" in decision.gate_reasons[0]


def test_an_unexplained_shortfall_is_escalated_at_low_confidence():
    ctx = make_context(
        rows=(make_row("setl_1", net_paise=976_360),),
        txns=(make_txn("bank_1", amount_paise=975_180),),
    )
    decision = gate(
        _link(residual_paise=1_180, residual_reason=ResidualReason.UNEXPLAINED, confidence=0.3),
        ctx,
    )
    assert decision.disposition is Disposition.ESCALATE


def test_an_immaterial_unreconciled_flag_may_post():
    ctx = make_context(rows=(make_row("setl_1", net_paise=400_00),))
    decision = gate(
        _link(
            action=ProposedAction.FLAG_MISSING_CREDIT,
            bank_txn_ids=frozenset(),
            residual_paise=400_00,
            residual_reason=ResidualReason.UNRECONCILED_FUNDS,
            confidence=0.9,
        ),
        ctx,
    )
    assert decision.disposition is Disposition.AUTO_APPLY


def test_a_material_missing_credit_always_reaches_a_person():
    # Money that never arrived is not a matching problem the agent gets to
    # close. Above the limit it is a cash difference somebody must chase.
    ctx = make_context(rows=(make_row("setl_1", net_paise=976_360),))
    decision = gate(
        _link(
            action=ProposedAction.FLAG_MISSING_CREDIT,
            bank_txn_ids=frozenset(),
            residual_paise=976_360,
            residual_reason=ResidualReason.UNRECONCILED_FUNDS,
            confidence=1.0,
        ),
        ctx,
    )
    assert decision.disposition is Disposition.NEEDS_REVIEW
    assert "materiality" in decision.gate_reasons[0]


def test_break_type_parsing_tolerates_nonsense():
    assert break_type_from_name("FX_ROUNDING") is BreakType.FX_ROUNDING
    assert break_type_from_name("not a break") is None
    assert break_type_from_name(None) is None
