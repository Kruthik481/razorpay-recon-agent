"""Shared fixtures. One generated period, reused across the agent tests."""

from __future__ import annotations

from datetime import date

import pytest

from recon.agent.index import build_index
from recon.agent.tools import ToolContext
from recon.domain.models import (
    BankTxn,
    Dataset,
    Order,
    SettlementRow,
    SettlementRowType,
    TxnDirection,
)
from recon.generator.dataset import generate_dataset
from recon.knowledge.model import Knowledge
from recon.matching.engine import reconcile_dataset

SETTLED_ON = date(2026, 7, 2)


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate_dataset(total_cases=200, seed=11)


@pytest.fixture(scope="session")
def outcome(dataset: Dataset):
    return reconcile_dataset(dataset)


@pytest.fixture
def index(dataset: Dataset):
    return build_index(dataset)


def make_order(order_id: str = "order_x", gross_paise: int = 1_000_000) -> Order:
    from datetime import datetime

    return Order(
        order_id=order_id,
        merchant_id="acc_test",
        gross_paise=gross_paise,
        currency="INR",
        created_at=datetime(2026, 7, 1, 12, 0),
    )


def make_row(
    row_id: str = "setl_x",
    *,
    net_paise: int = 976_360,
    gross_paise: int = 1_000_000,
    utr: str | None = None,
    settlement_id: str = "batch_x",
    row_type: SettlementRowType = SettlementRowType.PAYMENT,
    order_id: str | None = "order_x",
    settled_on: date = SETTLED_ON,
) -> SettlementRow:
    return SettlementRow(
        settlement_row_id=row_id,
        settlement_id=settlement_id,
        payment_id=f"pay_{row_id}",
        order_id=order_id,
        row_type=row_type,
        gross_paise=gross_paise,
        fee_paise=20_000,
        tax_paise=3_600,
        net_paise=net_paise,
        settled_on=settled_on,
        utr=utr,
    )


def make_txn(
    txn_id: str = "bank_x",
    *,
    amount_paise: int = 976_360,
    utr: str | None = None,
    direction: TxnDirection = TxnDirection.CREDIT,
    value_date: date = SETTLED_ON,
) -> BankTxn:
    return BankTxn(
        bank_txn_id=txn_id,
        utr=utr,
        amount_paise=amount_paise,
        direction=direction,
        value_date=value_date,
        description="TEST",
    )


def make_context(
    rows: tuple[SettlementRow, ...] = (),
    txns: tuple[BankTxn, ...] = (),
    orders: tuple[Order, ...] = (),
    knowledge: Knowledge | None = None,
) -> ToolContext:
    """A tool context over a hand-built ledger, with everything open."""
    built = build_index(
        Dataset(orders=orders, settlement_rows=rows, bank_txns=txns, ground_truth=())
    )
    return ToolContext(
        index=built,
        visible_row_ids=frozenset(r.settlement_row_id for r in rows),
        visible_txn_ids=frozenset(t.bank_txn_id for t in txns),
        knowledge=knowledge or Knowledge(),
    )
