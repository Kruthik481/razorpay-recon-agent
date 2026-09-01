"""Render an EvaluationReport as a terminal table.

Deliberately stdlib-only: this output goes straight into the demo video,
so it must run on a clean checkout with no extra install step.
"""

from __future__ import annotations

from recon.domain.break_types import DETERMINISTICALLY_MATCHABLE
from recon.evaluation.metrics import EvaluationReport

_WIDTH = 74


def _rule(char: str = "-") -> str:
    return char * _WIDTH


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _headline(report: EvaluationReport) -> list[str]:
    return [
        _rule("="),
        "DETERMINISTIC MATCHER - EVALUATION".center(_WIDTH),
        _rule("="),
        f"  cases                  {report.total_cases:>8}",
        f"  settlement rows        {report.total_settlement_rows:>8}",
        f"  bank transactions      {report.total_bank_txns:>8}",
        "",
        f"  auto-match rate        {_pct(report.auto_match_rate):>8}"
        f"   (ceiling {_pct(report.deterministic_ceiling)})",
        f"  precision              {_pct(report.precision):>8}",
        f"  incorrect matches      {report.incorrect_matches:>8}"
        f"   <- must stay at 0",
        f"  exception queue        {report.exception_queue_size:>8}"
        f"   records for the agent",
    ]


def _per_break_type(report: EvaluationReport) -> list[str]:
    lines = [
        "",
        _rule(),
        f"  {'break type':<24}{'cases':>7}{'matched':>9}{'recall':>9}  scope",
        _rule(),
    ]
    for score in report.by_break_type:
        scope = (
            "rules" if score.break_type in DETERMINISTICALLY_MATCHABLE else "agent"
        )
        lines.append(
            f"  {score.break_type.value:<24}{score.total_cases:>7}"
            f"{score.correctly_matched:>9}{_pct(score.recall):>9}  {scope}"
        )
    return lines


def _queue(report: EvaluationReport) -> list[str]:
    if not report.exception_queue_composition:
        return []
    lines = ["", _rule(), "  EXCEPTION QUEUE COMPOSITION", _rule()]
    lines.extend(
        f"  {break_type.value:<24}{count:>7} records"
        for break_type, count in report.exception_queue_composition
    )
    return lines


def render(report: EvaluationReport) -> str:
    """Build the full report string."""
    sections = _headline(report) + _per_break_type(report) + _queue(report)
    return "\n".join([*sections, _rule("="), ""])
