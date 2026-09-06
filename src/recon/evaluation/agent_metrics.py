"""Score the exception agent against the same answer key as the matcher.

Two numbers carry the argument:

* **auto-apply precision** — of everything the system posted without asking a
  human, how much was right. This is the number that has to be 100%.
* **queue clearance** — how much of the human queue the agent removed. This is
  the number that has to be large enough to matter.

They trade against each other, so neither is reported alone.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from recon.agent.runner import AgentRun
from recon.agent.schema import Disposition, GatedVerdict
from recon.domain.break_types import BreakType
from recon.domain.models import Dataset, GroundTruthLink


@dataclass(frozen=True, slots=True)
class _Tally:
    """Running counts while walking the verdicts."""

    correct: int = 0
    incorrect: int = 0
    abstained: int = 0
    classified: int = 0
    auto: int = 0
    auto_correct: int = 0
    auto_incorrect: int = 0
    review: int = 0
    escalated: int = 0
    failures: int = 0


@dataclass(frozen=True, slots=True)
class AgentReport:
    cases_worked: int
    correct: int
    incorrect: int
    abstained: int
    auto_applied: int
    auto_applied_correct: int
    auto_applied_incorrect: int
    needs_review: int
    escalated: int
    classified_correct: int
    verification_failures: int
    by_break_type: tuple[tuple[BreakType, int, int], ...]

    @property
    def auto_apply_precision(self) -> float:
        if self.auto_applied == 0:
            return 1.0
        return self.auto_applied_correct / self.auto_applied

    @property
    def resolution_rate(self) -> float:
        if self.cases_worked == 0:
            return 0.0
        return self.correct / self.cases_worked

    @property
    def wrong_assertion_rate(self) -> float:
        """Share of worked cases where the agent asserted something untrue.

        Kept apart from `abstained` deliberately. Declining to answer is the
        behaviour this system is built around; counting it as an error would
        report the design as a defect.
        """
        if self.cases_worked == 0:
            return 0.0
        return self.incorrect / self.cases_worked

    @property
    def classification_accuracy(self) -> float:
        if self.correct == 0:
            return 0.0
        return self.classified_correct / self.correct


def _signature(gated: GatedVerdict) -> tuple[frozenset[str], frozenset[str]]:
    return gated.verdict.settlement_row_ids, gated.verdict.bank_txn_ids


def _count_disposition(tally: _Tally, gated: GatedVerdict, is_right: bool) -> _Tally:
    """Fold one verdict's disposition into the running counts."""
    updates: dict[str, int] = {"failures": tally.failures + bool(gated.violations)}
    if gated.disposition is Disposition.NEEDS_REVIEW:
        updates["review"] = tally.review + 1
    elif gated.disposition is Disposition.ESCALATE:
        updates["escalated"] = tally.escalated + 1
    else:
        updates["auto"] = tally.auto + 1
        updates["auto_correct"] = tally.auto_correct + is_right
        updates["auto_incorrect"] = tally.auto_incorrect + (not is_right)
    return replace(tally, **updates)


def _count_outcome(tally: _Tally, gated: GatedVerdict, link: GroundTruthLink | None) -> _Tally:
    """Fold one verdict's correctness into the running counts."""
    if link is not None:
        classified = gated.verdict.break_type is link.break_type
        return replace(
            tally, correct=tally.correct + 1, classified=tally.classified + classified
        )
    if not gated.verdict.touches_records:
        return replace(tally, abstained=tally.abstained + 1)
    return replace(tally, incorrect=tally.incorrect + 1)


def evaluate_agent(dataset: Dataset, run: AgentRun) -> AgentReport:
    """Compare each verdict's record signature to the answer key, exactly."""
    truth = {
        (frozenset(link.settlement_row_ids), frozenset(link.bank_txn_ids)): link
        for link in dataset.ground_truth
    }

    tally = _Tally()
    hits: Counter[BreakType] = Counter()
    totals: Counter[BreakType] = Counter()

    for gated in run.gated:
        link = truth.get(_signature(gated))
        if link is not None and not gated.verdict.touches_records:
            link = None
        tally = _count_disposition(tally, gated, link is not None)
        tally = _count_outcome(tally, gated, link)
        if link is not None:
            totals[link.break_type] += 1
            hits[link.break_type] += gated.verdict.break_type is link.break_type

    return AgentReport(
        cases_worked=len(run.gated),
        correct=tally.correct,
        incorrect=tally.incorrect,
        abstained=tally.abstained,
        auto_applied=tally.auto,
        auto_applied_correct=tally.auto_correct,
        auto_applied_incorrect=tally.auto_incorrect,
        needs_review=tally.review,
        escalated=tally.escalated,
        classified_correct=tally.classified,
        verification_failures=tally.failures,
        by_break_type=tuple(
            (bt, totals[bt], hits[bt]) for bt in sorted(totals, key=lambda b: b.value)
        ),
    )
