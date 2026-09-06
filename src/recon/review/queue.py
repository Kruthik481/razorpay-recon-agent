"""What a person actually sees when they open the review queue.

Every item is self-contained: the proposal, the money that does not tie out,
the reason the gate refused to apply it automatically, and the records to look
at. A reviewer should never have to go and find context themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from recon.agent.index import LedgerIndex
from recon.agent.runner import AgentRun
from recon.agent.schema import Disposition, GatedVerdict
from recon.domain.models import TxnDirection
from recon.domain.money import format_paise


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One question for a human, in the order a human would ask it."""

    case_ref: str
    disposition: Disposition
    headline: str
    rationale: str
    blockers: tuple[str, ...]
    residual_paise: int
    residual_reason: str
    settlement_row_ids: tuple[str, ...]
    bank_txn_ids: tuple[str, ...]
    break_type: str | None
    confidence: float

    @property
    def residual_label(self) -> str:
        """The unexplained amount, with the direction spelled out.

        A bare negative number in a money column is a puzzle. Whether the bank
        moved too little or too much is the first thing a reviewer needs.
        """
        if self.residual_paise == 0:
            return "-"
        amount = format_paise(abs(self.residual_paise))
        return f"{amount} short" if self.residual_paise > 0 else f"{amount} unaccounted"


def _headline(gated: GatedVerdict, index: LedgerIndex) -> str:
    verdict = gated.verdict
    rows = len(verdict.settlement_row_ids)
    credits = sum(
        1 for t in verdict.bank_txn_ids if index.txns_by_id[t].direction is TxnDirection.CREDIT
    )
    debits = len(verdict.bank_txn_ids) - credits
    parts = [f"{rows} settlement row{'s' if rows != 1 else ''}"]
    if credits:
        parts.append(f"{credits} credit{'s' if credits != 1 else ''}")
    if debits:
        parts.append(f"{debits} debit{'s' if debits != 1 else ''}")
    return f"{verdict.action.value.replace('_', ' ')}: " + ", ".join(parts)


def build_review_queue(run: AgentRun, index: LedgerIndex) -> tuple[ReviewItem, ...]:
    """Everything the gate refused to apply, worst-understood first."""
    items = [
        ReviewItem(
            case_ref=g.verdict.case_ref,
            disposition=g.disposition,
            headline=_headline(g, index),
            rationale=g.verdict.rationale,
            blockers=g.gate_reasons + g.violations,
            residual_paise=g.verdict.residual_paise,
            residual_reason=g.verdict.residual_reason.value,
            settlement_row_ids=tuple(sorted(g.verdict.settlement_row_ids)),
            bank_txn_ids=tuple(sorted(g.verdict.bank_txn_ids)),
            break_type=g.verdict.break_type.value if g.verdict.break_type else None,
            confidence=g.verdict.confidence,
        )
        for g in run.gated
        if g.disposition is not Disposition.AUTO_APPLY
    ]
    # Escalations first: they are the cases nobody has an explanation for.
    return tuple(
        sorted(items, key=lambda i: (i.disposition is not Disposition.ESCALATE, i.case_ref))
    )
