"""The state behind one review sitting.

A session is immutable. Recording a decision or promoting one returns a new
session, so the handler never mutates state another request is reading, and
the baseline the console compares against cannot drift underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from recon.agent.index import LedgerIndex, build_index
from recon.agent.provider import ExceptionResolver
from recon.agent.providers.deterministic import DeterministicPolicy
from recon.domain.models import Dataset
from recon.generator.dataset import generate_dataset
from recon.knowledge.model import Knowledge
from recon.knowledge.store import load as load_knowledge
from recon.knowledge.store import save as save_knowledge
from recon.pipeline import Cycle, run_cycle
from recon.review.decisions import ReviewDecision, ReviewOutcome, append
from recon.review.decisions import load as load_decisions
from recon.review.promotion import Promotion, promote
from recon.review.queue import ReviewItem


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The headline numbers at a point in the sitting."""

    straight_through: int
    total_cases: int
    human_queue: int
    incorrect: int
    cleared_by_rules: int
    cleared_by_agent: int

    @property
    def rate(self) -> float:
        return self.straight_through / self.total_cases if self.total_cases else 0.0


@dataclass(frozen=True, slots=True)
class ReviewSession:
    """Everything one open console needs to answer any request."""

    dataset: Dataset
    index: LedgerIndex
    knowledge: Knowledge
    cycle: Cycle
    decisions: tuple[ReviewDecision, ...]
    baseline: Snapshot
    promotions: tuple[Promotion, ...]
    knowledge_path: Path
    decisions_path: Path
    seed: int

    @property
    def queue(self) -> tuple[ReviewItem, ...]:
        return self.cycle.review

    @property
    def now(self) -> Snapshot:
        return _snapshot(self.cycle)

    def item(self, case_ref: str) -> ReviewItem | None:
        return next((i for i in self.queue if i.case_ref == case_ref), None)

    @property
    def decided(self) -> frozenset[str]:
        return frozenset(d.case_ref for d in self.decisions)


def _snapshot(cycle: Cycle) -> Snapshot:
    return Snapshot(
        straight_through=cycle.straight_through_cases,
        total_cases=cycle.matcher.total_cases,
        human_queue=cycle.human_cases,
        incorrect=cycle.incorrect_total,
        cleared_by_rules=cycle.matcher.correct_matches,
        cleared_by_agent=cycle.agent.auto_applied_correct,
    )


def start_session(
    *,
    total_cases: int,
    seed: int,
    knowledge_path: Path,
    decisions_path: Path,
    resolver: ExceptionResolver | None = None,
) -> ReviewSession:
    """Generate a period, match it, work it, and open the queue for review."""
    engine = resolver or DeterministicPolicy()
    dataset = generate_dataset(total_cases=total_cases, seed=seed)
    knowledge = load_knowledge(knowledge_path)
    cycle = run_cycle(dataset, knowledge, engine, "live review")

    return ReviewSession(
        dataset=dataset,
        index=build_index(dataset),
        knowledge=knowledge,
        cycle=cycle,
        decisions=load_decisions(decisions_path),
        baseline=_snapshot(cycle),
        promotions=(),
        knowledge_path=knowledge_path,
        decisions_path=decisions_path,
        seed=seed,
    )


def record_decision(
    session: ReviewSession, case_ref: str, outcome: ReviewOutcome, reviewer: str
) -> ReviewSession:
    """Append one human answer to the log, snapshotting what was answered."""
    item = session.item(case_ref)
    if item is None:
        raise ValueError(f"no open case {case_ref!r}")

    decision = ReviewDecision(
        case_ref=item.case_ref,
        outcome=outcome,
        reviewer=reviewer,
        decided_at=datetime.now(UTC),
        note=f"{outcome.value} in the review console",
        settlement_row_ids=item.settlement_row_ids,
        bank_txn_ids=item.bank_txn_ids,
        residual_paise=item.residual_paise,
        residual_reason=item.residual_reason,
        break_type=item.break_type,
    )
    append((decision,), session.decisions_path)
    return replace(session, decisions=(*session.decisions, decision))


def promote_session(
    session: ReviewSession, resolver: ExceptionResolver | None = None
) -> ReviewSession:
    """Mine every decision so far, save what it justifies, and re-run the period."""
    knowledge, promotions = promote(session.knowledge, session.decisions, session.index)
    if not promotions:
        return replace(session, promotions=())

    save_knowledge(knowledge, session.knowledge_path)
    cycle = run_cycle(
        session.dataset, knowledge, resolver or DeterministicPolicy(), "after promotion"
    )
    return replace(session, knowledge=knowledge, cycle=cycle, promotions=promotions)


def reset_session(session: ReviewSession) -> ReviewSession:
    """Forget every decision and every learned rule. For running the demo twice."""
    for path in (session.decisions_path, session.knowledge_path):
        path.unlink(missing_ok=True)
    return start_session(
        total_cases=session.cycle.matcher.total_cases,
        seed=session.seed,
        knowledge_path=session.knowledge_path,
        decisions_path=session.decisions_path,
    )
