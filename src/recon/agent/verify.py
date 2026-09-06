"""Independent verification of whatever the model claimed.

The model proposes; this module disposes. Every number in a verdict is
recomputed from the ledger before anything downstream is allowed to trust it,
and every citation is checked against records that are actually open. A model
that hallucinates an id or misstates a residual fails here, silently and
cheaply, instead of loudly and expensively in the general ledger.
"""

from __future__ import annotations

from recon.agent.schema import AgentVerdict, ProposedAction, ResidualReason
from recon.agent.tools import ToolContext
from recon.domain.models import TxnDirection


def signed_row_total(ctx: ToolContext, row_ids: frozenset[str]) -> int:
    """Settlement value, with refunds and chargebacks already carrying a sign."""
    return sum(ctx.index.rows_by_id[r].net_paise for r in row_ids)


def signed_txn_total(ctx: ToolContext, txn_ids: frozenset[str]) -> int:
    """Bank movement: credits add, debits subtract."""
    total = 0
    for txn_id in txn_ids:
        txn = ctx.index.txns_by_id[txn_id]
        total += txn.amount_paise if txn.direction is TxnDirection.CREDIT else -txn.amount_paise
    return total


def compute_residual(ctx: ToolContext, verdict: AgentVerdict) -> int:
    """Money the proposal does not account for.

    Positive means the settlement report expected more than the bank moved.
    """
    return signed_row_total(ctx, verdict.settlement_row_ids) - signed_txn_total(
        ctx, verdict.bank_txn_ids
    )


def _unknown_ids(verdict: AgentVerdict, ctx: ToolContext) -> tuple[str, ...]:
    bad_rows = tuple(
        f"settlement row not open: {r}"
        for r in sorted(verdict.settlement_row_ids)
        if r not in ctx.visible_row_ids
    )
    bad_txns = tuple(
        f"bank transaction not open: {t}"
        for t in sorted(verdict.bank_txn_ids)
        if t not in ctx.visible_txn_ids
    )
    return bad_rows + bad_txns


def _shape_violations(verdict: AgentVerdict) -> tuple[str, ...]:
    """Each action has a required record shape; anything else is incoherent."""
    rows, txns = verdict.settlement_row_ids, verdict.bank_txn_ids
    if verdict.action is ProposedAction.LINK and not (rows and txns):
        return ("link must cite at least one settlement row and one bank transaction",)
    if verdict.action is ProposedAction.FLAG_MISSING_CREDIT and (txns or not rows):
        return ("missing-credit flag must cite settlement rows and no bank transaction",)
    if verdict.action is ProposedAction.FLAG_UNIDENTIFIED_CREDIT and (rows or not txns):
        return ("unidentified-credit flag must cite bank transactions and no settlement row",)
    return ()


def _citation_violations(verdict: AgentVerdict, ctx: ToolContext) -> tuple[str, ...]:
    known = (
        ctx.index.rows_by_id.keys()
        | ctx.index.txns_by_id.keys()
        | ctx.index.orders_by_id.keys()
    )
    return tuple(
        f"citation references an unknown record: {e.ref}"
        for e in verdict.evidence
        if e.kind == "record" and e.ref not in known
    )


def verify(verdict: AgentVerdict, ctx: ToolContext) -> tuple[str, ...]:
    """Return every reason this verdict cannot be trusted. Empty means clean."""
    violations: tuple[str, ...] = ()

    if not 0.0 <= verdict.confidence <= 1.0:
        violations += (f"confidence out of range: {verdict.confidence}",)

    violations += _unknown_ids(verdict, ctx)
    if violations:
        # Residual arithmetic on unknown records would be meaningless.
        return violations

    violations += _shape_violations(verdict)
    violations += _citation_violations(verdict, ctx)

    actual = compute_residual(ctx, verdict)
    if actual != verdict.residual_paise:
        violations += (
            f"declared residual {verdict.residual_paise} paise but ledger says {actual}",
        )
    if verdict.residual_reason is ResidualReason.NONE and actual != 0:
        violations += (f"residual of {actual} paise declared as fully explained",)

    return violations
