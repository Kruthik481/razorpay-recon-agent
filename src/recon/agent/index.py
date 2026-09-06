"""Read-only lookup structures over a reconciliation period.

Built once per run and shared by every tool call. Nothing here mutates: the
index is derived from a Dataset and holds only references to frozen records.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from recon.domain.models import BankTxn, Dataset, Order, SettlementRow


@dataclass(frozen=True, slots=True)
class LedgerIndex:
    """Id and key lookups across all three sources.

    The mappings are read-only views. One index is shared by every tool call
    and every case in a run, so an accidental write from one case would
    silently corrupt every case after it; `frozen=True` alone would not stop
    that, since it only blocks rebinding the attribute.
    """

    orders_by_id: Mapping[str, Order]
    rows_by_id: Mapping[str, SettlementRow]
    txns_by_id: Mapping[str, BankTxn]
    rows_by_order: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    rows_by_payment: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    rows_by_utr: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    txns_by_utr: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def order(self, order_id: str | None) -> Order | None:
        return self.orders_by_id.get(order_id) if order_id else None

    def row(self, row_id: str) -> SettlementRow | None:
        return self.rows_by_id.get(row_id)

    def txn(self, txn_id: str) -> BankTxn | None:
        return self.txns_by_id.get(txn_id)


def _group(pairs: list[tuple[str, str]]) -> Mapping[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for key, value in pairs:
        grouped[key].append(value)
    return MappingProxyType({key: tuple(values) for key, values in grouped.items()})


def build_index(dataset: Dataset) -> LedgerIndex:
    """Index a dataset for constant-time lookups by id and by join key."""
    return LedgerIndex(
        orders_by_id=MappingProxyType({o.order_id: o for o in dataset.orders}),
        rows_by_id=MappingProxyType({r.settlement_row_id: r for r in dataset.settlement_rows}),
        txns_by_id=MappingProxyType({t.bank_txn_id: t for t in dataset.bank_txns}),
        rows_by_order=_group(
            [(r.order_id, r.settlement_row_id) for r in dataset.settlement_rows if r.order_id]
        ),
        rows_by_payment=_group(
            [(r.payment_id, r.settlement_row_id) for r in dataset.settlement_rows]
        ),
        rows_by_utr=_group(
            [(r.utr, r.settlement_row_id) for r in dataset.settlement_rows if r.utr]
        ),
        txns_by_utr=_group([(t.utr, t.bank_txn_id) for t in dataset.bank_txns if t.utr]),
    )
