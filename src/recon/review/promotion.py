"""Turn confirmed human decisions into rules the matcher can apply itself.

This is the part that compounds. Every confirmed exception is a small piece of
evidence about how this merchant's money actually moves; once enough pieces
agree, the pattern becomes a deterministic rule and that break stops costing
anything at all — no model call, no analyst.

Three guards keep this from becoming a way to launder guesses into policy:

* nothing is promoted below `MIN_SUPPORT` independent confirmations;
* every promoted value must fall inside a hard, hand-set bound;
* every promotion records the case references behind it, so it can be audited
  and revoked.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from recon.agent import config as agent_config
from recon.agent.index import LedgerIndex
from recon.agent.schema import ResidualReason
from recon.agent.tools import implied_fee_bps
from recon.domain.models import SettlementRowType
from recon.knowledge.model import Knowledge, LearnedFact
from recon.review.decisions import ReviewDecision

# How many independent confirmations before a pattern becomes policy.
MIN_SUPPORT = 3

# Hard ceilings. A learned value outside these is a bug or an attack, not a fact.
MAX_LEARNABLE_TOLERANCE_PAISE = 100
MAX_LEARNABLE_FLAT_CHARGE_PAISE = 100_000


@dataclass(frozen=True, slots=True)
class Promotion:
    """One rule the system taught itself, and the evidence behind it."""

    kind: str
    value: int
    support: int
    case_refs: tuple[str, ...]
    note: str

    def as_fact(self) -> LearnedFact:
        return LearnedFact(
            kind=self.kind,
            value=self.value,
            support=self.support,
            source_case_refs=self.case_refs,
            note=self.note,
        )


def _confirmed(decisions: tuple[ReviewDecision, ...], reason: ResidualReason):
    return [d for d in decisions if d.is_confirmed and d.residual_reason == reason.value]


def _observed_fee_bps(decision: ReviewDecision, index: LedgerIndex) -> int | None:
    """Re-derive the rate from the ledger; never trust the label on the decision."""
    rows = [index.rows_by_id.get(r) for r in decision.settlement_row_ids]
    payments = [r for r in rows if r and r.row_type is SettlementRowType.PAYMENT]
    txns = [index.txns_by_id.get(t) for t in decision.bank_txn_ids]
    if len(payments) != 1 or len(txns) != 1 or txns[0] is None:
        return None
    implied = implied_fee_bps(
        None, gross_paise=payments[0].gross_paise, observed_net_paise=txns[0].amount_paise
    )
    if not implied.get("exact"):
        return None
    bps = implied["fee_bps"]
    in_band = agent_config.MIN_PLAUSIBLE_FEE_BPS <= bps <= agent_config.MAX_PLAUSIBLE_FEE_BPS
    return bps if in_band else None


def _promote_fee_rates(
    decisions: tuple[ReviewDecision, ...], index: LedgerIndex
) -> tuple[Promotion, ...]:
    by_rate: dict[int, list[str]] = defaultdict(list)
    for decision in _confirmed(decisions, ResidualReason.FEE_RATE_VARIANCE):
        bps = _observed_fee_bps(decision, index)
        if bps is not None:
            by_rate[bps].append(decision.case_ref)

    return tuple(
        Promotion(
            kind="fee_rate_bps",
            value=bps,
            support=len(refs),
            case_refs=tuple(sorted(refs)),
            note=(
                f"{len(refs)} confirmed settlements price at {bps} bps; added to the "
                "fee schedule on file"
            ),
        )
        for bps, refs in sorted(by_rate.items())
        if len(refs) >= MIN_SUPPORT
    )


def _promote_tolerance(decisions: tuple[ReviewDecision, ...]) -> tuple[Promotion, ...]:
    confirmed = _confirmed(decisions, ResidualReason.FX_ROUNDING)
    drifts = [abs(d.residual_paise) for d in confirmed]
    if len(drifts) < MIN_SUPPORT or max(drifts) > MAX_LEARNABLE_TOLERANCE_PAISE:
        return ()
    return (
        Promotion(
            kind="fx_tolerance_paise",
            value=max(drifts),
            support=len(drifts),
            case_refs=tuple(sorted(d.case_ref for d in confirmed)),
            note=(
                f"{len(drifts)} confirmed rounding differences, none larger than "
                f"{max(drifts)} paise; tolerance set to the widest one seen"
            ),
        ),
    )


def _promote_flat_charges(decisions: tuple[ReviewDecision, ...]) -> tuple[Promotion, ...]:
    """Notice a deduction nobody described: the same residual, again and again.

    A proportional fee produces a different shortfall on every amount. A
    constant shortfall across unrelated amounts is a flat charge, and that is
    inferable from the data alone.
    """
    by_amount: dict[int, list[str]] = defaultdict(list)
    for decision in _confirmed(decisions, ResidualReason.UNEXPLAINED):
        if 0 < decision.residual_paise <= MAX_LEARNABLE_FLAT_CHARGE_PAISE:
            by_amount[decision.residual_paise].append(decision.case_ref)

    return tuple(
        Promotion(
            kind="flat_bank_charge_paise",
            value=amount,
            support=len(refs),
            case_refs=tuple(sorted(refs)),
            note=(
                f"{len(refs)} confirmed settlements are short by exactly {amount} paise "
                "regardless of size; recorded as a flat charge"
            ),
        )
        for amount, refs in sorted(by_amount.items())
        if len(refs) >= MIN_SUPPORT
    )


def promote(
    knowledge: Knowledge, decisions: tuple[ReviewDecision, ...], index: LedgerIndex
) -> tuple[Knowledge, tuple[Promotion, ...]]:
    """Apply every promotion the evidence supports, returning new knowledge."""
    promotions = (
        _promote_fee_rates(decisions, index)
        + _promote_tolerance(decisions)
        + _promote_flat_charges(decisions)
    )

    updated = knowledge
    for promotion in promotions:
        fact = promotion.as_fact()
        if promotion.kind == "fee_rate_bps":
            updated = updated.with_fee_rate(promotion.value, fact)
        elif promotion.kind == "fx_tolerance_paise":
            updated = updated.with_fx_tolerance(promotion.value, fact)
        elif promotion.kind == "flat_bank_charge_paise":
            updated = updated.with_flat_charge(promotion.value, fact)
    return updated, promotions
