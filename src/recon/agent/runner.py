"""Work the exception queue case by case.

Cases are worked in a fixed order and every record a verdict claims is taken
out of circulation before the next case starts, so two cases can never claim
the same rupee. A verdict that fails verification claims nothing: its records
stay open for a human.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from recon.agent.cost import CostReport, TokenUsage
from recon.agent.exceptions import ExceptionCase, build_exception_queue
from recon.agent.gate import gate
from recon.agent.index import build_index
from recon.agent.provider import ExceptionResolver
from recon.agent.schema import Disposition, GatedVerdict
from recon.agent.tools import ToolCall, ToolContext
from recon.domain.models import Dataset
from recon.knowledge.model import Knowledge
from recon.matching.result import ReconOutcome


@dataclass(frozen=True, slots=True)
class CaseTrace:
    """The audit trail for one case: what was asked, and what came back."""

    case_ref: str
    tool_calls: tuple[ToolCall, ...]
    latency_ms: int
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Everything one pass over the exception queue produced."""

    gated: tuple[GatedVerdict, ...]
    traces: tuple[CaseTrace, ...]
    cost: CostReport
    skipped_cases: tuple[str, ...]

    def by_disposition(self, disposition: Disposition) -> tuple[GatedVerdict, ...]:
        return tuple(g for g in self.gated if g.disposition is disposition)

    @property
    def auto_applied(self) -> tuple[GatedVerdict, ...]:
        return self.by_disposition(Disposition.AUTO_APPLY)


def _trim(case: ExceptionCase, rows: frozenset[str], txns: frozenset[str]) -> ExceptionCase:
    """Drop records an earlier case already claimed."""
    return ExceptionCase(
        case_ref=case.case_ref,
        settlement_row_ids=tuple(r for r in case.settlement_row_ids if r in rows),
        bank_txn_ids=tuple(t for t in case.bank_txn_ids if t in txns),
        anchor_reason=case.anchor_reason,
    )


def _work_case(
    case: ExceptionCase, ctx: ToolContext, resolver: ExceptionResolver
) -> tuple[GatedVerdict, CaseTrace]:
    """Resolve one case and gate the answer."""
    output = resolver.resolve(case, ctx)
    decision = gate(output.verdict, ctx)
    trace = CaseTrace(case.case_ref, output.tool_calls, output.latency_ms, output.usage)
    return decision, trace


def _claims(decision: GatedVerdict) -> tuple[frozenset[str], frozenset[str]]:
    """What this verdict takes out of circulation. A failed one takes nothing."""
    if decision.violations or not decision.verdict.touches_records:
        return frozenset(), frozenset()
    return decision.verdict.settlement_row_ids, decision.verdict.bank_txn_ids


def run_agent(
    dataset: Dataset,
    outcome: ReconOutcome,
    resolver: ExceptionResolver,
    knowledge: Knowledge,
) -> AgentRun:
    """Resolve every case the deterministic matcher left open."""
    index = build_index(dataset)
    queue = build_exception_queue(outcome, index)

    open_rows = outcome.unmatched_settlement_row_ids
    open_txns = outcome.unmatched_bank_txn_ids

    gated: tuple[GatedVerdict, ...] = ()
    traces: tuple[CaseTrace, ...] = ()
    skipped: tuple[str, ...] = ()
    usage = TokenUsage()
    started = time.perf_counter()

    for original in queue:
        case = _trim(original, open_rows, open_txns)
        if case.record_count == 0:
            skipped += (case.case_ref,)
            continue

        ctx = ToolContext(index, open_rows, open_txns, knowledge)
        decision, trace = _work_case(case, ctx, resolver)

        gated += (decision,)
        traces += (trace,)
        usage = usage + trace.usage

        claimed_rows, claimed_txns = _claims(decision)
        open_rows = open_rows - claimed_rows
        open_txns = open_txns - claimed_txns

    wall_ms = int((time.perf_counter() - started) * 1000)
    return AgentRun(
        gated=gated,
        traces=traces,
        cost=CostReport(
            model=resolver.model,
            usage=usage,
            cases_resolved=len(gated),
            ledger_lines=len(dataset.settlement_rows) + len(dataset.bank_txns),
            wall_ms=wall_ms,
        ),
        skipped_cases=skipped,
    )
