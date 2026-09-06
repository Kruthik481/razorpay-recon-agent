"""Deterministic matching rules.

Every rule follows the same contract: propose a link only when the evidence
identifies exactly one counterparty. Ambiguity is never resolved by picking
the first candidate — it is handed to the exception queue, which is the only
safe default when the output posts a journal entry.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from itertools import combinations

from recon.domain.models import BankTxn, SettlementRow, TxnDirection
from recon.domain.money import format_paise
from recon.matching import config
from recon.matching.result import MatchProposal, MatchStage


def _expected_credit_paise(row: SettlementRow) -> int:
    """The bank credit a settlement row should produce, net of fees and tax."""
    return row.net_paise


def match_by_exact_utr(
    rows: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...]
) -> tuple[MatchProposal, ...]:
    """Match on a UTR that is unique on both sides and whose amount agrees."""
    rows_by_utr: dict[str, list[SettlementRow]] = defaultdict(list)
    for row in rows:
        if row.utr:
            rows_by_utr[row.utr].append(row)

    txns_by_utr: dict[str, list[BankTxn]] = defaultdict(list)
    for txn in txns:
        if txn.utr:
            txns_by_utr[txn.utr].append(txn)

    proposals = []
    for utr, candidate_rows in rows_by_utr.items():
        candidate_txns = txns_by_utr.get(utr, [])
        # A reused UTR carries no identifying power; leave it for review.
        if len(candidate_rows) != 1 or len(candidate_txns) != 1:
            continue
        row, txn = candidate_rows[0], candidate_txns[0]
        if txn.direction is not TxnDirection.CREDIT:
            continue
        if txn.amount_paise != _expected_credit_paise(row):
            continue
        proposals.append(
            MatchProposal(
                settlement_row_ids=frozenset({row.settlement_row_id}),
                bank_txn_ids=frozenset({txn.bank_txn_id}),
                stage=MatchStage.EXACT_UTR,
                confidence=config.CONFIDENCE_EXACT_UTR,
                rationale=(
                    f"UTR {utr} unique on both sides; credit {format_paise(txn.amount_paise)} "
                    f"equals net of gross {format_paise(row.gross_paise)} less fee "
                    f"{format_paise(row.fee_paise)} and tax {format_paise(row.tax_paise)}"
                ),
            )
        )
    return tuple(proposals)


def match_by_amount_and_date_window(
    rows: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...]
) -> tuple[MatchProposal, ...]:
    """Match on exact net amount within the settlement window, when unambiguous."""
    credits = [t for t in txns if t.direction is TxnDirection.CREDIT]
    by_amount: dict[int, list[BankTxn]] = defaultdict(list)
    for txn in credits:
        by_amount[txn.amount_paise].append(txn)

    proposals, claimed = [], set()
    for row in rows:
        expected = _expected_credit_paise(row)
        window_end = row.settled_on + timedelta(days=config.AMOUNT_DATE_WINDOW_DAYS)
        candidates = [
            t
            for t in by_amount.get(expected, [])
            if row.settled_on <= t.value_date <= window_end and t.bank_txn_id not in claimed
        ]
        if len(candidates) != 1:
            continue
        txn = candidates[0]
        claimed.add(txn.bank_txn_id)
        proposals.append(
            MatchProposal(
                settlement_row_ids=frozenset({row.settlement_row_id}),
                bank_txn_ids=frozenset({txn.bank_txn_id}),
                stage=MatchStage.AMOUNT_DATE_WINDOW,
                confidence=config.CONFIDENCE_AMOUNT_DATE_WINDOW,
                rationale=(
                    f"no usable UTR; sole credit of {format_paise(expected)} between "
                    f"{row.settled_on} and {window_end}"
                ),
            )
        )
    return tuple(proposals)


def _unique_subset_summing_to(
    pool: tuple[SettlementRow, ...], target: int
) -> tuple[SettlementRow, ...] | None:
    """Find the one subset whose nets sum to target, or None if 0 or 2+ exist.

    Only reached inside a single settlement batch, where the pool is small.
    An ambiguous pool returns None: two valid explanations means no answer.
    """
    found = None
    max_size = min(config.MAX_AGGREGATION_SUBSET_SIZE, len(pool))
    for size in range(2, max_size + 1):
        for subset in combinations(pool, size):
            if sum(r.net_paise for r in subset) != target:
                continue
            if found is not None:
                return None
            found = subset
    return found


def _batch_credit_candidates(
    batch: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...], target: int
) -> list[BankTxn]:
    """Credits that could plausibly be this batch's payout."""
    earliest = min(row.settled_on for row in batch)
    window_end = max(row.settled_on for row in batch) + timedelta(
        days=config.AMOUNT_DATE_WINDOW_DAYS
    )
    return [
        t
        for t in txns
        if t.direction is TxnDirection.CREDIT
        and t.amount_paise == target
        and earliest <= t.value_date <= window_end
    ]


def match_aggregated_payouts(
    rows: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...]
) -> tuple[MatchProposal, ...]:
    """Match a batch payout: several settlement rows paid as one credit.

    Grouping is driven by the settlement_id the PSP report already publishes,
    not by searching every combination of unmatched rows. An earlier version
    did the latter; see FAILURES.md entry 2 for why that was both slower and
    less accurate.
    """
    batches: dict[str, list[SettlementRow]] = defaultdict(list)
    for row in rows:
        batches[row.settlement_id].append(row)

    proposals, claimed_txns = [], set()
    for settlement_id, group in batches.items():
        if not 1 < len(group) <= config.MAX_AGGREGATION_GROUP_SIZE:
            continue
        batch = tuple(group)
        available = tuple(t for t in txns if t.bank_txn_id not in claimed_txns)

        full_total = sum(row.net_paise for row in batch)
        candidates = _batch_credit_candidates(batch, available, full_total)
        if len(candidates) == 1:
            matched_rows, txn = batch, candidates[0]
            rationale = (
                f"settlement batch {settlement_id} of {len(batch)} rows nets to "
                f"{format_paise(full_total)}, matching a single credit"
            )
        else:
            # The batch may have been paid out only in part.
            matched_rows, txn, rationale = _match_partial_batch(settlement_id, batch, available)
            if matched_rows is None:
                continue

        claimed_txns.add(txn.bank_txn_id)
        proposals.append(
            MatchProposal(
                settlement_row_ids=frozenset(r.settlement_row_id for r in matched_rows),
                bank_txn_ids=frozenset({txn.bank_txn_id}),
                stage=MatchStage.AGGREGATED_PAYOUT,
                confidence=config.CONFIDENCE_AGGREGATED_PAYOUT,
                rationale=rationale,
            )
        )
    return tuple(proposals)


def _match_partial_batch(
    settlement_id: str, batch: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...]
) -> tuple[tuple[SettlementRow, ...] | None, BankTxn | None, str]:
    """Explain a credit with a unique subset of a batch, when one exists."""
    earliest = min(row.settled_on for row in batch)
    window_end = max(row.settled_on for row in batch) + timedelta(
        days=config.AMOUNT_DATE_WINDOW_DAYS
    )
    in_window = [
        t
        for t in txns
        if t.direction is TxnDirection.CREDIT and earliest <= t.value_date <= window_end
    ]

    solutions = []
    for txn in in_window:
        subset = _unique_subset_summing_to(batch, txn.amount_paise)
        if subset is not None:
            solutions.append((subset, txn))

    # More than one credit explainable by this batch is itself ambiguous.
    if len(solutions) != 1:
        return None, None, ""

    subset, txn = solutions[0]
    return (
        subset,
        txn,
        f"settlement batch {settlement_id} paid in part: {len(subset)} of "
        f"{len(batch)} rows net to {format_paise(txn.amount_paise)}",
    )
