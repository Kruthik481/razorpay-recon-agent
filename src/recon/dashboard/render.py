"""Render a reconciliation run as one self-contained HTML file.

No framework, no build step, no network. The whole point of the artefact is
that it survives being emailed to somebody in finance.
"""

from __future__ import annotations

from datetime import date
from html import escape

from recon.dashboard.styles import CSS
from recon.pipeline import Cycle, PipelineResult
from recon.review.queue import ReviewItem


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def _card(label: str, value: str, note: str, tone: str = "") -> str:
    klass = f" {tone}" if tone else ""
    return (
        f'<div class="card"><div class="label">{escape(label)}</div>'
        f'<div class="value{klass}">{escape(value)}</div>'
        f'<div class="note">{escape(note)}</div></div>'
    )


def _kpis(result: PipelineResult) -> str:
    after, before = result.after, result.before
    gross = sum(r.gross_paise for r in result.dataset.settlement_rows)
    tone = "good" if after.incorrect_total == 0 else "bad"
    return "".join(
        (
            _card(
                "straight through",
                _pct(after.straight_through_rate),
                f"{after.straight_through_cases} of {after.matcher.total_cases} cases,"
                " no human",
                "good",
            ),
            _card(
                "incorrect postings",
                str(after.incorrect_total),
                "wrong links applied without review",
                tone,
            ),
            _card(
                "human queue",
                str(after.human_cases),
                f"down from {before.human_cases} before learning",
                "warn" if after.human_cases else "good",
            ),
            _card("value in scope", _rupees(gross), "gross settled in the period"),
        )
    )


def _cycle_row(cycle: Cycle) -> str:
    width = min(100.0, cycle.straight_through_rate * 100)
    return (
        f"<tr><td>{escape(cycle.label)}</td>"
        f'<td class="num">{cycle.matcher.correct_matches}</td>'
        f'<td class="num">{cycle.agent.auto_applied_correct}</td>'
        f'<td class="num">{cycle.human_cases}</td>'
        f'<td class="num">{cycle.incorrect_total}</td>'
        f'<td style="min-width:180px">{_pct(cycle.straight_through_rate)}'
        f'<div class="bar"><span style="width:{width:.1f}%"></span></div></td></tr>'
    )


def _cycles_table(result: PipelineResult) -> str:
    head = (
        "<tr><th>pass</th><th class='num'>cleared by rules</th>"
        "<th class='num'>cleared by agent</th><th class='num'>to a human</th>"
        "<th class='num'>wrong</th><th>straight through</th></tr>"
    )
    body = _cycle_row(result.before) + _cycle_row(result.after)
    return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"


def _promotions_table(result: PipelineResult) -> str:
    if not result.promotions:
        return "<p class='sub'>Nothing met the promotion threshold this run.</p>"
    rows = "".join(
        f"<tr><td class='mono'>{escape(p.kind)}</td>"
        f"<td class='num mono'>{p.value}</td>"
        f"<td class='num'>{p.support}</td>"
        f"<td>{escape(p.note)}"
        f"<div class='reason mono'>{escape(', '.join(p.case_refs[:4]))}"
        f"{'&hellip;' if len(p.case_refs) > 4 else ''}</div></td></tr>"
        for p in result.promotions
    )
    head = (
        "<tr><th>fact</th><th class='num'>value</th>"
        "<th class='num'>confirmations</th><th>evidence</th></tr>"
    )
    return f"<table><thead>{head}</thead><tbody>{rows}</tbody></table>"


def _queue_row(item: ReviewItem) -> str:
    pill = "escalate" if item.disposition.value == "escalate" else "review"
    records = ", ".join((*item.settlement_row_ids, *item.bank_txn_ids))
    return (
        f"<tr><td><span class='pill {pill}'>{escape(item.disposition.value)}</span></td>"
        f"<td>{escape(item.break_type or 'unclassified')}"
        f"<div class='reason'>{escape(item.rationale)}</div>"
        f"<div class='reason mono'>{escape(records)}</div></td>"
        f"<td class='num'>{escape(item.residual_rupees)}</td>"
        f"<td class='num'>{item.confidence:.2f}</td>"
        f"<td>{escape('; '.join(item.blockers))}</td></tr>"
    )


def _queue_table(result: PipelineResult) -> str:
    if not result.after.review:
        return "<p class='sub'>The queue is empty.</p>"
    head = (
        "<tr><th>state</th><th>case</th><th class='num'>unexplained</th>"
        "<th class='num'>confidence</th><th>why a human is needed</th></tr>"
    )
    rows = "".join(_queue_row(i) for i in result.after.review)
    return f"<table><thead>{head}</thead><tbody>{rows}</tbody></table>"


def _breaks_table(result: PipelineResult) -> str:
    head = (
        "<tr><th>break type</th><th class='num'>cases</th>"
        "<th class='num'>cleared by rules</th></tr>"
    )
    rows = "".join(
        f"<tr><td>{escape(s.break_type.value)}</td>"
        f"<td class='num'>{s.total_cases}</td>"
        f"<td class='num'>{s.correctly_matched}</td></tr>"
        for s in result.after.matcher.by_break_type
    )
    return f"<table><thead>{head}</thead><tbody>{rows}</tbody></table>"


def render_dashboard(result: PipelineResult, generated_on: date | None = None) -> str:
    """Build the complete HTML document."""
    stamp = (generated_on or date.today()).isoformat()
    resolver = result.after.run.cost.model
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reconciliation run &mdash; {escape(stamp)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>Reconciliation run</h1>
  <p class="sub">{result.after.matcher.total_cases} cases &middot;
  {result.after.matcher.total_settlement_rows} settlement rows &middot;
  {result.after.matcher.total_bank_txns} bank transactions &middot;
  resolver <span class="mono">{escape(resolver)}</span> &middot; generated {escape(stamp)}</p>
</header>

<div class="cards">{_kpis(result)}</div>

<h2>What each pass cleared</h2>
{_cycles_table(result)}

<h2>Rules the system learned from confirmed decisions</h2>
{_promotions_table(result)}

<h2>Still needs a person</h2>
{_queue_table(result)}

<h2>Coverage by break type</h2>
{_breaks_table(result)}

<footer>
Every number here is scored against a generated answer key the matcher and the
agent never see. Reproduce with <span class="mono">make dashboard</span>.
</footer>
</div></body></html>
"""
