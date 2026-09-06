"""Turn session state into JSON, and requests into new sessions.

Kept separate from the HTTP plumbing so the whole console is testable without
opening a socket. Every function is pure with respect to the session: it takes
one and returns the next.
"""

from __future__ import annotations

from typing import Any

from recon.agent import config as agent_config
from recon.domain.money import format_paise
from recon.review.decisions import ReviewOutcome, latest
from recon.review.promotion import MIN_SUPPORT
from recon.review.queue import ReviewItem
from recon.server.session import (
    ReviewSession,
    Snapshot,
    promote_session,
    record_decision,
    reset_session,
)

REVIEWER = "console"


def _snapshot_payload(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "straight_through": snapshot.straight_through,
        "total_cases": snapshot.total_cases,
        "rate": round(snapshot.rate * 100, 1),
        "human_queue": snapshot.human_queue,
        "incorrect": snapshot.incorrect,
        "cleared_by_rules": snapshot.cleared_by_rules,
        "cleared_by_agent": snapshot.cleared_by_agent,
    }


def _item_payload(item: ReviewItem, decided: dict[str, str]) -> dict[str, Any]:
    return {
        "case_ref": item.case_ref,
        "disposition": item.disposition.value,
        "break_type": item.break_type or "unclassified",
        "headline": item.headline,
        "rationale": item.rationale,
        "blockers": list(item.blockers),
        "residual": item.residual_label,
        "residual_reason": item.residual_reason,
        "confidence": round(item.confidence, 2),
        "records": [*item.settlement_row_ids, *item.bank_txn_ids],
        "decision": decided.get(item.case_ref),
    }


def _knowledge_payload(session: ReviewSession) -> dict[str, Any]:
    knowledge = session.knowledge
    return {
        "fee_bps_on_file": list(knowledge.fee_bps_on_file),
        "fx_tolerance": format_paise(knowledge.fx_tolerance_paise),
        "flat_charges": [format_paise(c) for c in knowledge.flat_bank_charges_paise],
        "facts": [
            {"kind": f.kind, "support": f.support, "note": f.note} for f in knowledge.facts
        ],
    }


def state_payload(session: ReviewSession) -> dict[str, Any]:
    """Everything the page needs to render itself from scratch."""
    # Standing decisions, not log lines: a confirmation later withdrawn should
    # not still be counted as one.
    standing = latest(session.decisions)
    decided = {d.case_ref: d.outcome.value for d in standing}
    confirmed = sum(1 for d in standing if d.is_confirmed)
    return {
        "baseline": _snapshot_payload(session.baseline),
        "now": _snapshot_payload(session.now),
        "queue": [_item_payload(i, decided) for i in session.queue],
        "knowledge": _knowledge_payload(session),
        "promotions": [
            {"kind": p.kind, "value": p.value, "support": p.support, "note": p.note}
            for p in session.promotions
        ],
        "confirmed": confirmed,
        "rejected": len(standing) - confirmed,
        "min_support": MIN_SUPPORT,
        "materiality": format_paise(agent_config.MATERIALITY_PAISE),
    }


def apply_decision(
    session: ReviewSession, body: dict[str, Any]
) -> tuple[ReviewSession, dict[str, Any]]:
    """Record one confirm or reject. Rejects anything not currently open."""
    case_ref = body.get("case_ref")
    outcome = body.get("outcome")
    if not isinstance(case_ref, str) or outcome not in ("confirmed", "rejected"):
        raise ValueError("a decision needs a case_ref and an outcome")

    updated = record_decision(session, case_ref, ReviewOutcome(outcome), REVIEWER)
    return updated, state_payload(updated)


def apply_promote(session: ReviewSession) -> tuple[ReviewSession, dict[str, Any]]:
    """Mine the decisions so far and re-run the period on what they taught."""
    updated = promote_session(session)
    return updated, state_payload(updated)


def apply_reset(session: ReviewSession) -> tuple[ReviewSession, dict[str, Any]]:
    """Throw away every decision and every learned rule."""
    updated = reset_session(session)
    return updated, state_payload(updated)
