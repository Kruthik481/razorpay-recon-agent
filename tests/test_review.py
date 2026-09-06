"""The decision log is append-only, parseable, and drives the review queue."""

from __future__ import annotations

from datetime import datetime

import pytest

from recon.agent.index import build_index
from recon.agent.schema import Disposition
from recon.pipeline import run_pipeline
from recon.review.decisions import (
    ReviewDecision,
    ReviewOutcome,
    append,
    from_json,
    load,
    to_json,
)
from recon.review.queue import build_review_queue
from recon.review.simulate import simulate_review

DECISION = ReviewDecision(
    case_ref="exc_1",
    outcome=ReviewOutcome.CONFIRMED,
    reviewer="tester",
    decided_at=datetime(2026, 9, 6, 12, 0),
    note="looks right",
    settlement_row_ids=("setl_1",),
    bank_txn_ids=("bank_1",),
    residual_paise=7,
    residual_reason="fx_rounding",
    break_type="fx_rounding",
)


def test_a_decision_round_trips_through_the_log_format():
    assert from_json(to_json(DECISION)) == DECISION


def test_appending_never_rewrites_earlier_lines(tmp_path):
    # Arrange
    path = tmp_path / "log" / "decisions.jsonl"
    append((DECISION,), path)
    first_bytes = path.read_bytes()

    # Act
    append((DECISION,), path)

    # Assert
    assert path.read_bytes().startswith(first_bytes)
    assert len(load(path)) == 2


def test_a_missing_log_means_nothing_was_reviewed(tmp_path):
    assert load(tmp_path / "absent.jsonl") == ()


def test_a_corrupt_line_is_rejected_loudly(tmp_path):
    path = tmp_path / "decisions.jsonl"
    path.write_text('{"case_ref": "x"}\n')
    with pytest.raises(ValueError, match="malformed"):
        load(path)


def test_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "decisions.jsonl"
    path.write_text(to_json(DECISION) + "\n\n")
    assert len(load(path)) == 1


def test_the_queue_holds_everything_the_gate_would_not_apply():
    result = run_pipeline(total_cases=150, seed=9)
    queue = build_review_queue(result.before.run, build_index(result.dataset))
    assert len(queue) == result.before.human_cases
    assert all(i.disposition is not Disposition.AUTO_APPLY for i in queue)


def test_escalations_are_shown_before_reviewable_cases():
    result = run_pipeline(total_cases=150, seed=9)
    dispositions = [i.disposition for i in result.before.review]
    escalations = [i for i, d in enumerate(dispositions) if d is Disposition.ESCALATE]
    reviews = [i for i, d in enumerate(dispositions) if d is Disposition.NEEDS_REVIEW]
    assert not escalations or not reviews or max(escalations) < min(reviews)


def test_every_queue_item_explains_why_a_person_is_needed():
    result = run_pipeline(total_cases=150, seed=9)
    assert all(item.blockers for item in result.before.review)


def test_the_scripted_reviewer_refuses_what_it_cannot_settle():
    # It confirms only single-counterparty links. Anything else — an
    # undecidable group, or a cash difference with no counterparty at all —
    # is left open for a real person.
    result = run_pipeline(total_cases=300, seed=3)
    rejected = [d for d in simulate_review(result.before.run) if not d.is_confirmed]
    confirmed = [d for d in simulate_review(result.before.run) if d.is_confirmed]

    assert rejected and confirmed
    assert all(len(d.bank_txn_ids) == 1 for d in confirmed)
    assert all(
        d.break_type in (None, "duplicate_utr", "missing_in_bank", "unknown_credit")
        for d in rejected
    )


def test_the_scripted_reviewer_answers_every_open_case():
    result = run_pipeline(total_cases=300, seed=3)
    assert len(simulate_review(result.before.run)) == result.before.human_cases


def test_an_unexplained_amount_says_which_way_it_runs():
    # A bare negative number in a money column is a puzzle; a reviewer needs to
    # know whether the bank moved too little or too much.
    result = run_pipeline(total_cases=150, seed=9)
    labels = [item.residual_label for item in result.before.review]

    assert any(label.endswith("short") for label in labels)
    assert any(label.endswith("unaccounted") for label in labels)
    assert all("-" not in label or label == "-" for label in labels)
