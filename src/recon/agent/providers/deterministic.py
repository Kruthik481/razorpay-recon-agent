"""A hand-written policy that works the exception queue with no model.

This exists for three reasons.

1. **It is the control.** Every claim of the form "the model adds X" is only
   meaningful against a serious non-model baseline. This is that baseline: the
   best "just write more rules" answer, written by someone who knows the
   dataset.
2. **It keeps the repo runnable.** Cloning this project and typing one command
   gives real numbers with no API key and no network.
3. **It shows where hand-written policy stops.** It covers eight break types.
   The ninth, a flat bank charge, it escalates rather than guesses, because
   nothing in it generalises to a deduction it was not told about.

It reaches its answers through the same tools a model would call, so the two
paths are directly comparable.
"""

from __future__ import annotations

from recon.agent.cost import TokenUsage
from recon.agent.exceptions import ExceptionCase
from recon.agent.provider import ResolverOutput
from recon.agent.providers.policy_probes import ROW_PROBES, TXN_PROBES
from recon.agent.providers.policy_support import Session
from recon.agent.schema import abstention
from recon.agent.tools import ToolCall, ToolContext


class DeterministicPolicy:
    """Runs the probes in order and returns the first answer one of them gives."""

    name = "deterministic-policy"
    model = "none"

    def resolve(self, case: ExceptionCase, ctx: ToolContext) -> ResolverOutput:
        session = Session(
            ctx=ctx,
            case=case,
            rows=tuple(ctx.index.rows_by_id[r] for r in case.settlement_row_ids),
            anchored_txns=tuple(ctx.index.txns_by_id[t] for t in case.bank_txn_ids),
        )
        probes = ROW_PROBES if session.rows else TXN_PROBES
        calls: tuple[ToolCall, ...] = ()
        for probe in probes:
            verdict, probe_calls = probe(session)
            calls += probe_calls
            if verdict is not None:
                return ResolverOutput(verdict, calls, TokenUsage(), 0)
        return ResolverOutput(
            abstention(case.case_ref, "no probe could explain this case"),
            calls,
            TokenUsage(),
            0,
        )
