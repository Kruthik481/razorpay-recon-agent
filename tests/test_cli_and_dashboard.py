"""The published surfaces: the command line and the HTML report."""

from __future__ import annotations

import json
from datetime import date

import pytest

from recon.cli import main
from recon.dashboard.render import render_dashboard
from recon.evaluation.pipeline_report import render_pipeline
from recon.pipeline import run_pipeline

SMALL = ["--cases", "120", "--seed", "5"]


@pytest.fixture(scope="module")
def result():
    return run_pipeline(total_cases=120, seed=5)


def test_run_prints_both_passes(capsys):
    assert main(["run", *SMALL]) == 0
    out = capsys.readouterr().out
    assert "RULES + AGENT" in out
    assert "AFTER ONE REVIEW CYCLE" in out
    assert "incorrect postings           0" in out


def test_evaluate_reports_the_matcher_alone(capsys):
    assert main(["evaluate", *SMALL]) == 0
    assert "DETERMINISTIC MATCHER" in capsys.readouterr().out


def test_export_writes_one_csv_per_source(tmp_path, capsys):
    assert main(["export", *SMALL, "--out", str(tmp_path)]) == 0
    written = {p.name for p in tmp_path.glob("*.csv")}
    assert written == {
        "orders.csv",
        "settlement_rows.csv",
        "bank_txns.csv",
        "ground_truth.csv",
    }


def test_export_reports_an_unwritable_directory(tmp_path, capsys):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")
    assert main(["export", *SMALL, "--out", str(blocked / "under")]) == 1


def test_dashboard_writes_a_self_contained_file(tmp_path):
    target = tmp_path / "nested" / "report.html"
    assert main(["dashboard", *SMALL, "--out", str(target)]) == 0
    html = target.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<style>" in html and "src=" not in html


def test_queue_lists_the_open_cases(capsys):
    assert main(["queue", *SMALL]) == 0
    assert "awaiting review" in capsys.readouterr().out


def test_promote_without_a_log_says_so(tmp_path, capsys):
    assert main(["promote", *SMALL, "--decisions", str(tmp_path / "none.jsonl")]) == 0
    assert "no decisions recorded" in capsys.readouterr().out


def test_review_without_a_terminal_stops_cleanly(tmp_path, capsys):
    assert main(["review", *SMALL, "--decisions", str(tmp_path / "d.jsonl")]) == 0
    assert "recorded 0 decisions" in capsys.readouterr().out


def test_promote_writes_knowledge_from_a_log(tmp_path, capsys):
    log = tmp_path / "decisions.jsonl"
    knowledge = tmp_path / "knowledge.json"
    from recon.review.decisions import append
    from recon.review.simulate import simulate_review

    append(simulate_review(run_pipeline(total_cases=120, seed=5).before.run), log)
    assert (
        main(["promote", *SMALL, "--decisions", str(log), "--knowledge", str(knowledge)]) == 0
    )
    assert json.loads(knowledge.read_text(encoding="utf-8"))["fee_bps_on_file"]


def test_an_unusable_knowledge_file_is_ignored_not_fatal(tmp_path, capsys):
    bad = tmp_path / "knowledge.json"
    bad.write_text("{broken", encoding="utf-8")
    assert main(["evaluate", *SMALL, "--knowledge", str(bad)]) == 0
    assert "ignoring unusable knowledge file" in capsys.readouterr().err


def test_an_unknown_resolver_is_rejected():
    with pytest.raises(SystemExit):
        main(["run", "--resolver", "psychic"])


def test_the_dashboard_escapes_untrusted_text(result):
    html = render_dashboard(result, generated_on=date(2026, 9, 6))
    assert "<script>" not in html
    assert "&middot;" in html


def test_the_dashboard_shows_both_passes(result):
    html = render_dashboard(result, generated_on=date(2026, 9, 6))
    assert "rules + agent" in html
    assert "after one review cycle" in html
    assert "straight through" in html


def test_the_terminal_report_is_fixed_width(result):
    lines = render_pipeline(result).splitlines()
    assert max(len(line) for line in lines) <= 110


def test_promote_builds_on_knowledge_already_on_file(tmp_path):
    # Arrange: a rate is already on file, and the decision log no longer holds
    # the confirmations that justified it. Re-running promote must not delete it.
    from recon.knowledge.model import Knowledge, LearnedFact
    from recon.knowledge.store import load, save
    from recon.review.decisions import append
    from recon.review.simulate import simulate_review

    knowledge_path = tmp_path / "knowledge.json"
    log = tmp_path / "decisions.jsonl"
    fact = LearnedFact("fee_rate_bps", 310, 4, ("older_case",), "learned last month")
    save(Knowledge().with_fee_rate(310, fact), knowledge_path)
    append(simulate_review(run_pipeline(total_cases=120, seed=5).before.run), log)

    # Act
    assert (
        main(
            [
                "promote",
                *SMALL,
                "--decisions",
                str(log),
                "--knowledge",
                str(knowledge_path),
            ]
        )
        == 0
    )

    # Assert
    assert 310 in load(knowledge_path).fee_bps_on_file
