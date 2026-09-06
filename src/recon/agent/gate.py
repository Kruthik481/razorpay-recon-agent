"""The confidence gate: what may post without a human.

Confidence alone is never enough. A verdict is auto-applied only when it is
confident, arithmetically clean, and its residual is explained by something
already on file. Anything else is routed to a person. The asymmetry is
deliberate: a missed auto-match costs an analyst a few minutes, a wrong one
posts a journal entry somebody has to unwind.
"""

from __future__ import annotations

from recon.agent import config
from recon.agent.schema import (
    AgentVerdict,
    Disposition,
    GatedVerdict,
    ProposedAction,
    ResidualReason,
)
from recon.agent.tools import ToolContext, implied_fee_bps
from recon.agent.verify import signed_txn_total, verify
from recon.domain.models import SettlementRowType


def _payment_gross(ctx: ToolContext, verdict: AgentVerdict) -> int:
    return sum(
        ctx.index.rows_by_id[r].gross_paise
        for r in verdict.settlement_row_ids
        if ctx.index.rows_by_id[r].row_type is SettlementRowType.PAYMENT
    )


def _fee_variance_blockers(ctx: ToolContext, verdict: AgentVerdict) -> tuple[str, ...]:
    """Re-derive the rate ourselves; a rate we do not hold is not an explanation."""
    gross = _payment_gross(ctx, verdict)
    if gross <= 0:
        return ("fee-rate variance claimed with no payment row to rate",)
    observed_net = signed_txn_total(ctx, verdict.bank_txn_ids)
    implied = implied_fee_bps(ctx, gross_paise=gross, observed_net_paise=observed_net)
    if not implied.get("exact"):
        return ("no whole basis-point rate reproduces the observed payout",)
    bps = implied["fee_bps"]
    if bps not in ctx.knowledge.fee_bps_on_file:
        return (f"implied rate {bps} bps is not on file",)
    return ()


def _residual_blockers(ctx: ToolContext, verdict: AgentVerdict) -> tuple[str, ...]:
    """Is the unexplained money explained by something we already accept?"""
    residual = verdict.residual_paise
    reason = verdict.residual_reason

    if reason is ResidualReason.NONE:
        return () if residual == 0 else ("residual is not zero",)
    # The cap applies to flags as well as links. Raising "this money never
    # arrived" is not a matching problem the agent gets to close on its own;
    # above the limit it is a real cash difference and a person owns it.
    if abs(residual) > config.MATERIALITY_PAISE:
        return (f"residual {residual} paise exceeds the materiality limit",)
    if reason is ResidualReason.UNRECONCILED_FUNDS:
        return ()
    if reason is ResidualReason.FX_ROUNDING:
        if abs(residual) > ctx.knowledge.fx_tolerance_paise:
            return (f"rounding tolerance on file is {ctx.knowledge.fx_tolerance_paise} paise",)
        return ()
    if reason is ResidualReason.FLAT_BANK_CHARGE:
        if residual not in ctx.knowledge.flat_bank_charges_paise:
            return (f"no flat charge of {residual} paise is on file",)
        return ()
    if reason is ResidualReason.FEE_RATE_VARIANCE:
        return _fee_variance_blockers(ctx, verdict)
    return ("residual is unexplained",)


def gate(verdict: AgentVerdict, ctx: ToolContext) -> GatedVerdict:
    """Verify a verdict, then decide how far it is allowed to travel."""
    violations = verify(verdict, ctx)
    if violations:
        return GatedVerdict(verdict, Disposition.ESCALATE, violations, ("failed verification",))

    if verdict.action is ProposedAction.NO_ACTION:
        return GatedVerdict(verdict, Disposition.ESCALATE, (), ("agent asserted nothing",))

    blockers = _residual_blockers(ctx, verdict)
    if verdict.confidence < config.REVIEW_CONFIDENCE:
        return GatedVerdict(
            verdict,
            Disposition.ESCALATE,
            (),
            (f"confidence {verdict.confidence:.2f} below review threshold", *blockers),
        )
    if blockers or verdict.confidence < config.AUTO_APPLY_CONFIDENCE:
        reasons = blockers or (
            f"confidence {verdict.confidence:.2f} below auto-apply threshold",
        )
        return GatedVerdict(verdict, Disposition.NEEDS_REVIEW, (), reasons)

    return GatedVerdict(verdict, Disposition.AUTO_APPLY, (), ())
