"""Loop commands: run the whole pipeline, or render it as HTML."""

from __future__ import annotations

from pathlib import Path

from recon.agent.provider import ExceptionResolver
from recon.dashboard.render import render_dashboard
from recon.evaluation.pipeline_report import render_pipeline
from recon.knowledge.model import Knowledge
from recon.pipeline import PipelineResult, run_pipeline
from recon.review.decisions import ReviewDecision


def build(
    *,
    total_cases: int,
    seed: int,
    resolver: ExceptionResolver,
    knowledge: Knowledge,
    decisions: tuple[ReviewDecision, ...] | None,
) -> PipelineResult:
    return run_pipeline(
        total_cases=total_cases,
        seed=seed,
        resolver=resolver,
        knowledge=knowledge,
        decisions=decisions,
    )


def cmd_run(result: PipelineResult) -> int:
    """Print the before/after story for one reconciliation period."""
    print(render_pipeline(result))
    return 0


def cmd_dashboard(result: PipelineResult, out: Path) -> int:
    """Write the same story as a single self-contained HTML file."""
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_dashboard(result))
    except OSError as exc:
        print(f"cannot write dashboard to {out}: {exc}")
        return 1
    print(f"  wrote {out}")
    return 0
