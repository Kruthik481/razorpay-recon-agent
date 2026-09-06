"""Deterministic rules built from facts the system was taught.

These are ordinary matching rules. What makes them interesting is where they
come from: each one is parameterised by a fact a human confirmed in the review
queue, so the matcher gets stronger every time somebody works the queue, and
the same break stops costing a model call the second time it is seen.

They run after the built-in rules and before anything reaches the agent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from recon.domain.models import BankTxn, SettlementRow, SettlementRowType, TxnDirection
from recon.domain.money import format_paise, split_fees
from recon.generator.config import GST_ON_FEE_BPS
from recon.knowledge.model import Knowledge
from recon.matching import config
from recon.matching.result import MatchProposal, MatchStage

MatchRule = Callable[
    [tuple[SettlementRow, ...], tuple[BankTxn, ...]], tuple[MatchProposal, ...]
]


def _sole_credit(
    txns: tuple[BankTxn, ...], row: SettlementRow, target: int, claimed: set[str]
) -> BankTxn | None:
    """The one open credit of `target` paise inside the row's settlement window."""
    window_end = row.settled_on + timedelta(days=config.AMOUNT_DATE_WINDOW_DAYS)
    hits = [
        t
        for t in txns
        if t.direction is TxnDirection.CREDIT
        and t.amount_paise == target
        and row.settled_on <= t.value_date <= window_end
        and t.bank_txn_id not in claimed
    ]
    return hits[0] if len(hits) == 1 else None


def _payments(rows: tuple[SettlementRow, ...]) -> tuple[SettlementRow, ...]:
    return tuple(r for r in rows if r.row_type is SettlementRowType.PAYMENT)


def _sole_explanation(
    row: SettlementRow,
    txns: tuple[BankTxn, ...],
    targets: dict[int, int],
    claimed: set[str],
) -> tuple[tuple[int, ...], BankTxn] | None:
    """The one credit explained by the facts on file, if exactly one exists.

    Uniqueness has to hold *across* facts, not just within one. Two learned
    rates can each pick out a different credit for the same row, and taking
    whichever was checked first would be exactly the coin-flip the rest of the
    system refuses to make. Several facts landing on the *same* credit is not
    ambiguity: the link is identical, only the label differs.
    """
    hits: dict[str, tuple[list[int], BankTxn]] = {}
    for value, target in sorted(targets.items()):
        txn = _sole_credit(txns, row, target, claimed)
        if txn is None:
            continue
        values, _ = hits.setdefault(txn.bank_txn_id, ([], txn))
        values.append(value)

    if len(hits) != 1:
        return None
    values, txn = next(iter(hits.values()))
    return tuple(values), txn


def _propose(row: SettlementRow, txn: BankTxn, rationale: str) -> MatchProposal:
    return MatchProposal(
        settlement_row_ids=frozenset({row.settlement_row_id}),
        bank_txn_ids=frozenset({txn.bank_txn_id}),
        stage=MatchStage.LEARNED,
        confidence=config.CONFIDENCE_LEARNED_RULE,
        rationale=rationale,
    )


def match_by_learned_fee_rates(
    rows: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...], knowledge: Knowledge
) -> tuple[MatchProposal, ...]:
    """Settle rows at any merchant discount rate the system has been taught."""
    learned = tuple(b for b in knowledge.fee_bps_on_file if b != config.STANDARD_FEE_BPS)
    if not learned:
        return ()

    proposals, claimed = [], set()
    for row in _payments(rows):
        targets = {
            bps: split_fees(row.gross_paise, bps, GST_ON_FEE_BPS).net_paise for bps in learned
        }
        explanation = _sole_explanation(row, txns, targets, claimed)
        if explanation is None:
            continue
        rates, txn = explanation
        claimed.add(txn.bank_txn_id)
        proposals.append(
            _propose(
                row,
                txn,
                f"gross {format_paise(row.gross_paise)} less a learned "
                f"{'/'.join(str(r) for r in rates)} bps fee and GST is "
                f"{format_paise(txn.amount_paise)}, matching the sole credit in the window",
            )
        )
    return tuple(proposals)


def match_within_learned_tolerance(
    rows: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...], knowledge: Knowledge
) -> tuple[MatchProposal, ...]:
    """Absorb rounding drift up to the tolerance a controller signed off on."""
    tolerance = knowledge.fx_tolerance_paise
    if tolerance <= 0:
        return ()

    proposals, claimed = [], set()
    for row in _payments(rows):
        window_end = row.settled_on + timedelta(days=config.AMOUNT_DATE_WINDOW_DAYS)
        hits = [
            t
            for t in txns
            if t.direction is TxnDirection.CREDIT
            and abs(row.net_paise - t.amount_paise) <= tolerance
            and row.settled_on <= t.value_date <= window_end
            and t.bank_txn_id not in claimed
        ]
        if len(hits) != 1:
            continue
        claimed.add(hits[0].bank_txn_id)
        proposals.append(
            _propose(
                row,
                hits[0],
                f"credit is within the approved {format_paise(tolerance)} rounding tolerance "
                f"of the expected {format_paise(row.net_paise)}",
            )
        )
    return tuple(proposals)


def match_less_flat_charges(
    rows: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...], knowledge: Knowledge
) -> tuple[MatchProposal, ...]:
    """Settle rows the bank paid out short by a known flat remittance charge."""
    if not knowledge.flat_bank_charges_paise:
        return ()

    proposals, claimed = [], set()
    for row in _payments(rows):
        targets = {
            charge: row.net_paise - charge for charge in knowledge.flat_bank_charges_paise
        }
        explanation = _sole_explanation(row, txns, targets, claimed)
        if explanation is None:
            continue
        charges, txn = explanation
        claimed.add(txn.bank_txn_id)
        proposals.append(
            _propose(
                row,
                txn,
                f"credit is the expected {format_paise(row.net_paise)} less the known flat "
                f"bank charge of {'/'.join(format_paise(c) for c in charges)}",
            )
        )
    return tuple(proposals)


LEARNED_RULE_FACTORIES = (
    match_by_learned_fee_rates,
    match_within_learned_tolerance,
    match_less_flat_charges,
)


def learned_rules(knowledge: Knowledge) -> tuple[MatchRule, ...]:
    """Bind the learned rules to a knowledge snapshot, strongest evidence first."""
    return tuple(
        (lambda rows, txns, factory=factory: factory(rows, txns, knowledge))
        for factory in LEARNED_RULE_FACTORIES
    )
