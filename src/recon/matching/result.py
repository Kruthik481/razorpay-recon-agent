"""Types describing what the deterministic matcher concluded."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MatchStage(StrEnum):
    """Which rule produced a match. Ordered from strongest to weakest evidence."""

    EXACT_UTR = "exact_utr"
    AMOUNT_DATE_WINDOW = "amount_date_window"
    AGGREGATED_PAYOUT = "aggregated_payout"
    LEARNED = "learned"


@dataclass(frozen=True, slots=True)
class MatchProposal:
    """A settlement-to-bank linkage the matcher is willing to assert."""

    settlement_row_ids: frozenset[str]
    bank_txn_ids: frozenset[str]
    stage: MatchStage
    confidence: float
    rationale: str


@dataclass(frozen=True, slots=True)
class ReconOutcome:
    """Everything the matcher resolved, plus the queue it could not."""

    matches: tuple[MatchProposal, ...]
    unmatched_settlement_row_ids: frozenset[str]
    unmatched_bank_txn_ids: frozenset[str]

    @property
    def exception_queue_size(self) -> int:
        return len(self.unmatched_settlement_row_ids) + len(self.unmatched_bank_txn_ids)
