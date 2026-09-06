"""Render the whole loop as a terminal table.

Stdlib only and fixed width, because this output is what gets recorded for the
demo and pasted into the README. It has to look the same on every machine.
"""

from __future__ import annotations

from recon.pipeline import Cycle, PipelineResult

_WIDTH = 74


def _rule(char: str = "-") -> str:
    return char * _WIDTH


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def _cycle_block(cycle: Cycle) -> list[str]:
    matcher, agent = cycle.matcher, cycle.agent
    return [
        _rule(),
        f"  {cycle.label.upper()}",
        _rule(),
        f"  rules auto-matched      {matcher.correct_matches:>6} / {matcher.total_cases}"
        f"   ({_pct(matcher.auto_match_rate)})",
        f"  agent worked            {agent.cases_worked:>6} cases"
        f"   ({agent.correct} resolved correctly)",
        f"    auto-applied          {agent.auto_applied:>6}"
        f"   precision {_pct(agent.auto_apply_precision)}",
        f"    sent to review        {agent.needs_review:>6}",
        f"    escalated             {agent.escalated:>6}",
        f"    abstained             {agent.abstained:>6}   (declined to answer, not an error)",
        "",
        f"  straight-through        {cycle.straight_through_cases:>6} / {matcher.total_cases}"
        f"   ({_pct(cycle.straight_through_rate)})",
        f"  cases reaching a human  {cycle.human_cases:>6}",
        f"  incorrect postings      {cycle.incorrect_total:>6}   <- must stay at 0",
    ]


def _promotions_block(result: PipelineResult) -> list[str]:
    if not result.promotions:
        return ["", _rule(), "  NOTHING PROMOTED", _rule()]
    lines = ["", _rule(), "  RULES LEARNED FROM CONFIRMED REVIEW DECISIONS", _rule()]
    for promotion in result.promotions:
        lines.append(
            f"  {promotion.kind:<26}{promotion.value:>10}"
            f"   from {promotion.support} confirmations"
        )
        lines.append(f"    {promotion.note}")
    return lines


def _cost_block(result: PipelineResult) -> list[str]:
    before, after = result.before.run.cost, result.after.run.cost
    if before.usage.total_tokens == 0:
        return [
            "",
            _rule(),
            "  MODEL SPEND",
            _rule(),
            "  no model calls in this run (deterministic policy)",
            f"  cases sent to the model would fall from {result.before.agent.cases_worked}"
            f" to {result.after.agent.cases_worked}",
        ]
    return [
        "",
        _rule(),
        "  MODEL SPEND",
        _rule(),
        f"  model                   {before.model}",
        f"  before learning         ${before.usd:.4f}"
        f"   (${before.usd_per_thousand_lines:.4f} per 1k lines)",
        f"  after learning          ${after.usd:.4f}"
        f"   (${after.usd_per_thousand_lines:.4f} per 1k lines)",
        f"  latency per case        {before.ms_per_case:.0f} ms",
    ]


def render_pipeline(result: PipelineResult) -> str:
    """The full before/after story, in one screen."""
    sections = [
        _rule("="),
        "RECONCILIATION LOOP - RULES, AGENT, REVIEW, PROMOTION".center(_WIDTH),
        _rule("="),
        *_cycle_block(result.before),
        "",
        *_cycle_block(result.after),
        *_promotions_block(result),
        *_cost_block(result),
        "",
        _rule(),
        f"  net effect: human queue {result.before.human_cases} -> "
        f"{result.after.human_cases} cases "
        f"({result.queue_reduction} fewer), postings wrong: "
        f"{result.after.incorrect_total}",
        f"  value auto-reconciled   "
        f"{_rupees(sum(r.gross_paise for r in result.dataset.settlement_rows))} gross",
        _rule("="),
        "",
    ]
    return "\n".join(sections)
