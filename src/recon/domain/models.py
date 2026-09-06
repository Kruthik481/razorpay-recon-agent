"""Immutable records for the three sources being reconciled.

All money is integer paise. Floats never touch an amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from recon.domain.break_types import BreakType


class TxnDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class SettlementRowType(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"
    CHARGEBACK = "chargeback"


@dataclass(frozen=True, slots=True)
class Order:
    """A line from the merchant's own ledger — source of truth for intent."""

    order_id: str
    merchant_id: str
    gross_paise: int
    currency: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SettlementRow:
    """A line from the payment processor's settlement report."""

    settlement_row_id: str
    settlement_id: str
    payment_id: str
    order_id: str | None
    row_type: SettlementRowType
    gross_paise: int
    fee_paise: int
    tax_paise: int
    net_paise: int
    settled_on: date
    utr: str | None


@dataclass(frozen=True, slots=True)
class BankTxn:
    """A line from the bank statement — the only source that means real money."""

    bank_txn_id: str
    utr: str | None
    amount_paise: int
    direction: TxnDirection
    value_date: date
    description: str


@dataclass(frozen=True, slots=True)
class GroundTruthLink:
    """The answer key for one generated case.

    Present only in synthetic data. The matcher never sees this; the
    evaluation harness uses it to score proposals.
    """

    case_id: str
    break_type: BreakType
    settlement_row_ids: tuple[str, ...]
    bank_txn_ids: tuple[str, ...]
    order_ids: tuple[str, ...]

    @property
    def is_deterministically_matchable(self) -> bool:
        from recon.domain.break_types import DETERMINISTICALLY_MATCHABLE

        return self.break_type in DETERMINISTICALLY_MATCHABLE


@dataclass(frozen=True, slots=True)
class Dataset:
    """A generated reconciliation period, with its answer key."""

    orders: tuple[Order, ...]
    settlement_rows: tuple[SettlementRow, ...]
    bank_txns: tuple[BankTxn, ...]
    ground_truth: tuple[GroundTruthLink, ...]
