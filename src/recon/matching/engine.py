"""Staged reconciliation pipeline.

Rules run strongest-evidence-first. Each stage sees only what earlier stages
left behind, and nothing is ever re-matched. What survives every stage is the
exception queue — the only place an LLM call is justified.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from recon.domain.models import BankTxn, Dataset, SettlementRow
from recon.knowledge.model import Knowledge
from recon.matching.learned import learned_rules
from recon.matching.result import MatchProposal, ReconOutcome
from recon.matching.rules import (
    match_aggregated_payouts,
    match_by_amount_and_date_window,
    match_by_exact_utr,
)

MatchRule = Callable[
    [tuple[SettlementRow, ...], tuple[BankTxn, ...]], tuple[MatchProposal, ...]
]

DEFAULT_RULES: tuple[MatchRule, ...] = (
    match_by_exact_utr,
    match_by_amount_and_date_window,
    match_aggregated_payouts,
)


def _remaining(
    rows: tuple[SettlementRow, ...],
    txns: tuple[BankTxn, ...],
    proposals: Sequence[MatchProposal],
) -> tuple[tuple[SettlementRow, ...], tuple[BankTxn, ...]]:
    """Return new tuples excluding everything the proposals consumed."""
    used_rows = {rid for p in proposals for rid in p.settlement_row_ids}
    used_txns = {tid for p in proposals for tid in p.bank_txn_ids}
    return (
        tuple(r for r in rows if r.settlement_row_id not in used_rows),
        tuple(t for t in txns if t.bank_txn_id not in used_txns),
    )


def reconcile(
    rows: tuple[SettlementRow, ...],
    txns: tuple[BankTxn, ...],
    rules: tuple[MatchRule, ...] = DEFAULT_RULES,
) -> ReconOutcome:
    """Run every rule in order and collect what none of them could explain."""
    all_proposals: tuple[MatchProposal, ...] = ()
    pending_rows, pending_txns = rows, txns

    for rule in rules:
        proposals = rule(pending_rows, pending_txns)
        if not proposals:
            continue
        all_proposals += proposals
        pending_rows, pending_txns = _remaining(pending_rows, pending_txns, proposals)

    return ReconOutcome(
        matches=all_proposals,
        unmatched_settlement_row_ids=frozenset(r.settlement_row_id for r in pending_rows),
        unmatched_bank_txn_ids=frozenset(t.bank_txn_id for t in pending_txns),
    )


def rules_for(knowledge: Knowledge | None = None) -> tuple[MatchRule, ...]:
    """The built-in rules, followed by any rule the system has been taught."""
    if knowledge is None:
        return DEFAULT_RULES
    return DEFAULT_RULES + learned_rules(knowledge)


def reconcile_dataset(dataset: Dataset, knowledge: Knowledge | None = None) -> ReconOutcome:
    """Convenience wrapper — the matcher never sees dataset.ground_truth."""
    return reconcile(dataset.settlement_rows, dataset.bank_txns, rules_for(knowledge))
