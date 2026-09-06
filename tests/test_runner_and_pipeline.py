"""End-to-end invariants: no rupee is claimed twice, and nothing wrong posts."""

from __future__ import annotations

from collections import Counter

import pytest

from recon.agent.providers.deterministic import DeterministicPolicy
from recon.agent.runner import run_agent
from recon.agent.schema import Disposition
from recon.evaluation.agent_metrics import evaluate_agent
from recon.knowledge.model import Knowledge
from recon.pipeline import run_pipeline


@pytest.fixture(scope="module")
def pipeline():
    return run_pipeline(total_cases=300, seed=3)


def test_the_agent_never_posts_a_wrong_link(pipeline):
    for cycle in (pipeline.before, pipeline.after):
        assert cycle.agent.auto_applied_incorrect == 0
        assert cycle.agent.auto_apply_precision == 1.0


def test_the_matcher_never_posts_a_wrong_link(pipeline):
    assert pipeline.before.matcher.incorrect_matches == 0
    assert pipeline.after.matcher.incorrect_matches == 0


def test_no_record_is_claimed_by_two_cases(pipeline):
    claimed = Counter()
    for gated in pipeline.before.run.gated:
        if gated.violations:
            continue
        claimed.update(gated.verdict.settlement_row_ids)
        claimed.update(gated.verdict.bank_txn_ids)
    assert not [record for record, count in claimed.items() if count > 1]


def test_the_agent_only_touches_records_the_matcher_left_open(pipeline):
    matched = {
        record
        for proposal in pipeline.before.outcome.matches
        for record in (*proposal.settlement_row_ids, *proposal.bank_txn_ids)
    }
    for gated in pipeline.before.run.gated:
        touched = gated.verdict.settlement_row_ids | gated.verdict.bank_txn_ids
        assert not touched & matched


def test_a_review_cycle_shrinks_the_human_queue(pipeline):
    assert pipeline.after.human_cases < pipeline.before.human_cases
    assert pipeline.queue_reduction > 0


def test_a_review_cycle_raises_straight_through_processing(pipeline):
    assert pipeline.after.straight_through_rate > pipeline.before.straight_through_rate


def test_learning_never_costs_accuracy(pipeline):
    assert pipeline.after.incorrect_total == 0


def test_what_remains_is_either_undecidable_or_a_real_cash_difference(pipeline):
    # Two things should survive the loop, and nothing else: cases the data
    # cannot decide, and money that is actually missing or unexplained. The
    # second kind is not a matching problem, so the agent never closes it.
    assert {item.break_type for item in pipeline.after.review} <= {
        "duplicate_utr",
        "missing_in_bank",
        "unknown_credit",
        None,
    }


def test_no_material_cash_difference_is_closed_without_a_person(pipeline):
    from recon.agent import config
    from recon.agent.schema import ResidualReason

    for gated in pipeline.after.run.auto_applied:
        if gated.verdict.residual_reason is ResidualReason.UNRECONCILED_FUNDS:
            assert abs(gated.verdict.residual_paise) <= config.MATERIALITY_PAISE


def test_promotions_are_backed_by_enough_evidence(pipeline):
    from recon.review.promotion import MIN_SUPPORT

    assert pipeline.promotions
    assert all(p.support >= MIN_SUPPORT for p in pipeline.promotions)


def test_the_pipeline_is_reproducible():
    first = run_pipeline(total_cases=120, seed=5)
    second = run_pipeline(total_cases=120, seed=5)
    assert first.before.straight_through_cases == second.before.straight_through_cases
    assert [p.value for p in first.promotions] == [p.value for p in second.promotions]


def test_every_case_reaches_exactly_one_disposition(pipeline):
    counts = Counter(g.disposition for g in pipeline.before.run.gated)
    assert sum(counts.values()) == pipeline.before.agent.cases_worked
    assert set(counts) <= set(Disposition)


def test_an_empty_exception_queue_produces_an_empty_run(dataset, outcome):
    from recon.matching.result import ReconOutcome

    empty = ReconOutcome(
        matches=outcome.matches,
        unmatched_settlement_row_ids=frozenset(),
        unmatched_bank_txn_ids=frozenset(),
    )
    run = run_agent(dataset, empty, DeterministicPolicy(), Knowledge())
    report = evaluate_agent(dataset, run)
    assert run.gated == ()
    assert report.auto_apply_precision == 1.0
    assert report.resolution_rate == 0.0
