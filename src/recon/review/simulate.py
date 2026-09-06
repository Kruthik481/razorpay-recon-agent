"""A stand-in reviewer, for demonstrations and for CI.

This is **not** part of the product and it never sees the answer key. It is a
scripted analyst: it applies one written-down policy to whatever the agent put
in front of it, so the learning loop can be exercised end to end without a
person in the room. Real deployments replace it with `recon review`.

The policy: confirm a proposal that names exactly one counterparty credit and
whose unexplained amount is immaterial. Refuse everything else, including the
cases that are genuinely undecidable — a scripted analyst that confirms
everything would teach the system nonsense.
"""

from __future__ import annotations

from datetime import datetime

from recon.agent import config
from recon.agent.runner import AgentRun
from recon.agent.schema import Disposition, GatedVerdict, ProposedAction
from recon.review.decisions import ReviewDecision, ReviewOutcome

REVIEWER = "simulated-analyst"


def _decision_for(gated: GatedVerdict, decided_at: datetime) -> ReviewDecision:
    verdict = gated.verdict
    single_counterparty = len(verdict.bank_txn_ids) == 1
    immaterial = abs(verdict.residual_paise) <= config.MATERIALITY_PAISE
    confirmable = (
        verdict.action is ProposedAction.LINK
        and single_counterparty
        and immaterial
        and not gated.violations
    )
    return ReviewDecision(
        case_ref=verdict.case_ref,
        outcome=ReviewOutcome.CONFIRMED if confirmable else ReviewOutcome.REJECTED,
        reviewer=REVIEWER,
        decided_at=decided_at,
        note=(
            "single counterparty and immaterial difference; confirmed"
            if confirmable
            else "counterparty is not uniquely identified; left open"
        ),
        settlement_row_ids=tuple(sorted(verdict.settlement_row_ids)),
        bank_txn_ids=tuple(sorted(verdict.bank_txn_ids)),
        residual_paise=verdict.residual_paise,
        residual_reason=verdict.residual_reason.value,
        break_type=verdict.break_type.value if verdict.break_type else None,
    )


def simulate_review(
    run: AgentRun, decided_at: datetime | None = None
) -> tuple[ReviewDecision, ...]:
    """Produce a decision for every case the gate would not apply on its own."""
    stamp = decided_at or datetime(2026, 9, 6, 10, 0, 0)
    return tuple(
        _decision_for(g, stamp)
        for g in run.gated
        if g.disposition is not Disposition.AUTO_APPLY
    )
