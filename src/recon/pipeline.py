"""The whole loop, in one place.

    deterministic rules  ->  exception agent  ->  human review  ->  new rules

Running it twice is the point. The second pass uses the knowledge the first
pass earned, so the cost of a break falls the second time it is seen. Every
stage is measured against the same answer key, and nothing downstream of the
generator is ever allowed to look at it.
"""

from __future__ import annotations

from dataclasses import dataclass

from recon.agent.index import LedgerIndex, build_index
from recon.agent.provider import ExceptionResolver
from recon.agent.providers.deterministic import DeterministicPolicy
from recon.agent.runner import AgentRun, run_agent
from recon.domain.models import Dataset
from recon.evaluation.agent_metrics import AgentReport, evaluate_agent
from recon.evaluation.metrics import EvaluationReport, evaluate
from recon.generator import config as generator_config
from recon.generator.dataset import generate_dataset
from recon.knowledge.model import Knowledge
from recon.matching.engine import reconcile_dataset
from recon.matching.result import ReconOutcome
from recon.review.decisions import ReviewDecision
from recon.review.promotion import Promotion, promote
from recon.review.queue import ReviewItem, build_review_queue
from recon.review.simulate import simulate_review


@dataclass(frozen=True, slots=True)
class Cycle:
    """One full pass of rules plus agent over the same period."""

    label: str
    knowledge: Knowledge
    outcome: ReconOutcome
    matcher: EvaluationReport
    run: AgentRun
    agent: AgentReport
    review: tuple[ReviewItem, ...]

    @property
    def straight_through_cases(self) -> int:
        """Cases closed with no human involved: rules plus auto-applied verdicts."""
        return self.matcher.correct_matches + self.agent.auto_applied_correct

    @property
    def straight_through_rate(self) -> float:
        if self.matcher.total_cases == 0:
            return 0.0
        return self.straight_through_cases / self.matcher.total_cases

    @property
    def human_cases(self) -> int:
        return self.agent.needs_review + self.agent.escalated

    @property
    def incorrect_total(self) -> int:
        return self.matcher.incorrect_matches + self.agent.auto_applied_incorrect


@dataclass(frozen=True, slots=True)
class PipelineResult:
    dataset: Dataset
    index: LedgerIndex
    before: Cycle
    after: Cycle
    decisions: tuple[ReviewDecision, ...]
    promotions: tuple[Promotion, ...]

    @property
    def queue_reduction(self) -> int:
        return self.before.human_cases - self.after.human_cases


def run_cycle(
    dataset: Dataset,
    knowledge: Knowledge,
    resolver: ExceptionResolver,
    label: str,
) -> Cycle:
    """Match, then work whatever the matcher could not explain."""
    outcome = reconcile_dataset(dataset, knowledge)
    run = run_agent(dataset, outcome, resolver, knowledge)
    return Cycle(
        label=label,
        knowledge=knowledge,
        outcome=outcome,
        matcher=evaluate(dataset, outcome),
        run=run,
        agent=evaluate_agent(dataset, run),
        review=build_review_queue(run, build_index(dataset)),
    )


def run_pipeline(
    *,
    total_cases: int = generator_config.DEFAULT_CASE_COUNT,
    seed: int = generator_config.DEFAULT_SEED,
    resolver: ExceptionResolver | None = None,
    knowledge: Knowledge | None = None,
    decisions: tuple[ReviewDecision, ...] | None = None,
) -> PipelineResult:
    """Run the loop twice: once cold, once with what review taught it.

    `decisions` defaults to the scripted analyst in `recon.review.simulate`,
    which never sees the answer key. Pass a real decision log to replay what
    people actually decided.
    """
    engine = resolver or DeterministicPolicy()
    dataset = generate_dataset(total_cases=total_cases, seed=seed)
    index = build_index(dataset)

    before = run_cycle(dataset, knowledge or Knowledge(), engine, "rules + agent")
    reviewed = decisions if decisions is not None else simulate_review(before.run)
    learned, promotions = promote(before.knowledge, reviewed, index)
    after = run_cycle(dataset, learned, engine, "after one review cycle")

    return PipelineResult(
        dataset=dataset,
        index=index,
        before=before,
        after=after,
        decisions=reviewed,
        promotions=promotions,
    )
