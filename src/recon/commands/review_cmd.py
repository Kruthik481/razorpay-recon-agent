"""Review commands: look at the queue, decide on it, promote what was confirmed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from recon.knowledge.model import Knowledge
from recon.knowledge.store import save
from recon.pipeline import PipelineResult
from recon.review.decisions import ReviewDecision, ReviewOutcome, append, load
from recon.review.promotion import promote
from recon.review.queue import ReviewItem

_PROMPTS = {"y": ReviewOutcome.CONFIRMED, "n": ReviewOutcome.REJECTED}


def _show(item: ReviewItem, position: int, total: int) -> None:
    print(f"\n[{position}/{total}] {item.case_ref}  ({item.disposition.value})")
    print(f"  {item.headline}")
    print(f"  {item.rationale}")
    print(f"  unexplained: {item.residual_label}  ({item.residual_reason})")
    print(f"  records: {', '.join((*item.settlement_row_ids, *item.bank_txn_ids))}")
    for blocker in item.blockers:
        print(f"  blocked by: {blocker}")


def _decision(item: ReviewItem, answer: str) -> ReviewDecision:
    return ReviewDecision(
        case_ref=item.case_ref,
        outcome=_PROMPTS[answer],
        reviewer="cli",
        decided_at=datetime.now(UTC),
        note="confirmed at the terminal" if answer == "y" else "rejected at the terminal",
        settlement_row_ids=item.settlement_row_ids,
        bank_txn_ids=item.bank_txn_ids,
        residual_paise=item.residual_paise,
        residual_reason=item.residual_reason,
        break_type=item.break_type,
    )


def cmd_queue(result: PipelineResult) -> int:
    """Print everything still waiting on a person."""
    items = result.before.review
    if not items:
        print("  the review queue is empty")
        return 0
    for position, item in enumerate(items, start=1):
        _show(item, position, len(items))
    print(f"\n  {len(items)} cases awaiting review")
    return 0


def cmd_review(result: PipelineResult, log_path: Path) -> int:
    """Walk the queue and record a decision per case. Answers: y, n, s to skip."""
    items = result.before.review
    decisions: tuple[ReviewDecision, ...] = ()
    for position, item in enumerate(items, start=1):
        _show(item, position, len(items))
        try:
            answer = input("  confirm this link? [y/n/s] ").strip().lower()
        except (EOFError, KeyboardInterrupt, OSError):
            # No terminal attached, or the reviewer walked away. Either way,
            # keep what was decided rather than losing the session.
            print("\n  stopped; recording what was decided so far")
            break
        if answer in _PROMPTS:
            decisions += (_decision(item, answer),)

    if decisions:
        append(decisions, log_path)
    print(f"\n  recorded {len(decisions)} decisions -> {log_path}")
    return 0


def cmd_promote(
    result: PipelineResult, log_path: Path, knowledge_path: Path, known: Knowledge
) -> int:
    """Mine the decision log and write out the rules it justifies.

    Promotion builds on what is already on file. Starting from an empty
    knowledge base would quietly delete any fact whose supporting decisions
    have since been rotated out of the log.
    """
    try:
        decisions = load(log_path)
    except ValueError as exc:
        print(f"  {exc}")
        return 1
    if not decisions:
        print(f"  no decisions recorded in {log_path}")
        return 0

    updated, promotions = promote(known, decisions, result.index)
    if not promotions:
        print("  nothing met the promotion threshold")
        return 0
    for promotion in promotions:
        print(
            f"  learned {promotion.kind} = {promotion.value} "
            f"from {promotion.support} confirmations"
        )
        print(f"    {promotion.note}")
    save(updated, knowledge_path)
    print(f"\n  wrote {knowledge_path}")
    return 0
