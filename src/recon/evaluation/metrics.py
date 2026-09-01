"""Score matcher output against the generated answer key.

The number that matters most here is `incorrect_matches`. A missed match
costs an analyst a few minutes; a confidently wrong match posts a bad
journal entry and can take weeks to unwind. This harness reports them
separately and never blends them into one accuracy figure.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from recon.domain.break_types import BreakType
from recon.domain.models import Dataset, GroundTruthLink
from recon.matching.result import MatchProposal, ReconOutcome


@dataclass(frozen=True, slots=True)
class BreakTypeScore:
    break_type: BreakType
    total_cases: int
    correctly_matched: int
    incorrectly_matched: int

    @property
    def recall(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.correctly_matched / self.total_cases


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    total_cases: int
    total_settlement_rows: int
    total_bank_txns: int
    proposals_made: int
    correct_matches: int
    incorrect_matches: int
    exception_queue_size: int
    by_break_type: tuple[BreakTypeScore, ...]
    exception_queue_composition: tuple[tuple[BreakType, int], ...]

    @property
    def precision(self) -> float:
        """Share of asserted matches that were right."""
        if self.proposals_made == 0:
            return 0.0
        return self.correct_matches / self.proposals_made

    @property
    def auto_match_rate(self) -> float:
        """Share of all cases cleared with no human or model involvement."""
        if self.total_cases == 0:
            return 0.0
        return self.correct_matches / self.total_cases

    @property
    def deterministic_ceiling(self) -> float:
        """Share of cases a rules engine could resolve even in principle."""
        matchable = sum(
            s.total_cases
            for s in self.by_break_type
            if s.break_type in _deterministic_types()
        )
        if self.total_cases == 0:
            return 0.0
        return matchable / self.total_cases


def _deterministic_types() -> frozenset[BreakType]:
    from recon.domain.break_types import DETERMINISTICALLY_MATCHABLE

    return DETERMINISTICALLY_MATCHABLE


def _signature(link: GroundTruthLink) -> tuple[frozenset[str], frozenset[str]]:
    return frozenset(link.settlement_row_ids), frozenset(link.bank_txn_ids)


def _proposal_signature(p: MatchProposal) -> tuple[frozenset[str], frozenset[str]]:
    return p.settlement_row_ids, p.bank_txn_ids


def evaluate(dataset: Dataset, outcome: ReconOutcome) -> EvaluationReport:
    """Compare proposals to ground truth, exactly — partial credit is not useful."""
    truth_by_signature = {_signature(link): link for link in dataset.ground_truth}
    row_to_case = {
        row_id: link
        for link in dataset.ground_truth
        for row_id in link.settlement_row_ids
    }
    txn_to_case = {
        txn_id: link for link in dataset.ground_truth for txn_id in link.bank_txn_ids
    }

    correct_by_type: Counter[BreakType] = Counter()
    incorrect_by_type: Counter[BreakType] = Counter()
    correct = incorrect = 0

    for proposal in outcome.matches:
        matched_link = truth_by_signature.get(_proposal_signature(proposal))
        if matched_link is not None:
            correct += 1
            correct_by_type[matched_link.break_type] += 1
            continue
        incorrect += 1
        # Attribute the error to whichever case the proposal touched first.
        any_row = next(iter(proposal.settlement_row_ids), None)
        origin = row_to_case.get(any_row) if any_row else None
        if origin is not None:
            incorrect_by_type[origin.break_type] += 1

    totals: Counter[BreakType] = Counter(
        link.break_type for link in dataset.ground_truth
    )
    by_break_type = tuple(
        BreakTypeScore(
            break_type=bt,
            total_cases=totals[bt],
            correctly_matched=correct_by_type[bt],
            incorrectly_matched=incorrect_by_type[bt],
        )
        for bt in sorted(totals, key=lambda b: (-totals[b], b.value))
    )

    queue: Counter[BreakType] = Counter()
    for row_id in outcome.unmatched_settlement_row_ids:
        link = row_to_case.get(row_id)
        if link is not None:
            queue[link.break_type] += 1
    for txn_id in outcome.unmatched_bank_txn_ids:
        link = txn_to_case.get(txn_id)
        if link is not None:
            queue[link.break_type] += 1

    return EvaluationReport(
        total_cases=len(dataset.ground_truth),
        total_settlement_rows=len(dataset.settlement_rows),
        total_bank_txns=len(dataset.bank_txns),
        proposals_made=len(outcome.matches),
        correct_matches=correct,
        incorrect_matches=incorrect,
        exception_queue_size=outcome.exception_queue_size,
        by_break_type=by_break_type,
        exception_queue_composition=tuple(queue.most_common()),
    )
