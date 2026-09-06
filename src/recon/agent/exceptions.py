"""Turn the matcher's leftovers into cases an investigator can work.

A case is an *anchor*: the records that hard join keys prove belong together
(a shared payment id, a shared UTR). It is deliberately not the answer — the
counterparty still has to be found with tools. Grouping never consults the
answer key or any id the generator assigned by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from recon.agent.index import LedgerIndex
from recon.domain.models import BankTxn, SettlementRow
from recon.matching.result import ReconOutcome


@dataclass(frozen=True, slots=True)
class ExceptionCase:
    """One unit of investigation."""

    case_ref: str
    settlement_row_ids: tuple[str, ...]
    bank_txn_ids: tuple[str, ...]
    anchor_reason: str

    @property
    def record_count(self) -> int:
        return len(self.settlement_row_ids) + len(self.bank_txn_ids)


class _Union:
    """Minimal union-find over record keys."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        self._parent.setdefault(key, key)

    def find(self, key: str) -> str:
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parent[max(left_root, right_root)] = min(left_root, right_root)

    def groups(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for key in sorted(self._parent):
            grouped.setdefault(self.find(key), []).append(key)
        return grouped


def _link_hard_keys(
    union: _Union, rows: tuple[SettlementRow, ...], txns: tuple[BankTxn, ...]
) -> None:
    """Join only on keys a real report actually publishes."""
    by_payment: dict[str, str] = {}
    by_order: dict[str, str] = {}
    by_utr: dict[str, str] = {}

    for row in rows:
        key = f"row:{row.settlement_row_id}"
        union.add(key)
        for bucket, value in (
            (by_payment, row.payment_id),
            (by_order, row.order_id),
            (by_utr, row.utr),
        ):
            if not value:
                continue
            if value in bucket:
                union.union(bucket[value], key)
            else:
                bucket[value] = key

    for txn in txns:
        key = f"txn:{txn.bank_txn_id}"
        union.add(key)
        if txn.utr and txn.utr in by_utr:
            union.union(by_utr[txn.utr], key)
        elif txn.utr:
            by_utr[txn.utr] = key


def _anchor_reason(row_ids: tuple[str, ...], txn_ids: tuple[str, ...]) -> str:
    if len(row_ids) + len(txn_ids) == 1:
        return "single unmatched record; counterparty unknown"
    return "records share a payment id, order id or UTR"


def build_exception_queue(
    outcome: ReconOutcome, index: LedgerIndex
) -> tuple[ExceptionCase, ...]:
    """Cluster unmatched records into cases, in a stable, reproducible order."""
    rows = tuple(
        sorted(
            (index.rows_by_id[r] for r in outcome.unmatched_settlement_row_ids),
            key=lambda r: r.settlement_row_id,
        )
    )
    txns = tuple(
        sorted(
            (index.txns_by_id[t] for t in outcome.unmatched_bank_txn_ids),
            key=lambda t: t.bank_txn_id,
        )
    )

    union = _Union()
    _link_hard_keys(union, rows, txns)

    cases = []
    for members in union.groups().values():
        row_ids = tuple(m.removeprefix("row:") for m in members if m.startswith("row:"))
        txn_ids = tuple(m.removeprefix("txn:") for m in members if m.startswith("txn:"))
        cases.append(
            ExceptionCase(
                case_ref=f"exc_{min(members)}",
                settlement_row_ids=row_ids,
                bank_txn_ids=txn_ids,
                anchor_reason=_anchor_reason(row_ids, txn_ids),
            )
        )

    # Cases carrying settlement rows come first: they have an order and a fee
    # schedule behind them, so they are cheaper to resolve and their resolution
    # removes bank credits that would otherwise look orphaned.
    return tuple(sorted(cases, key=lambda c: (not c.settlement_row_ids, c.case_ref)))
