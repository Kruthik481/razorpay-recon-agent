"""Taxonomy of reconciliation breaks.

The split below is the core thesis of this project: most breaks are
mechanical and belong to a deterministic matcher. Only the ambiguous
remainder is worth spending an LLM call on.
"""

from enum import Enum


class BreakType(str, Enum):
    """Why a settlement row and a bank transaction fail to line up naively."""

    CLEAN = "clean"
    FEE_NETTING = "fee_netting"
    MISSING_UTR = "missing_utr"
    SETTLEMENT_LAG = "settlement_lag"
    AGGREGATED_PAYOUT = "aggregated_payout"

    NON_STANDARD_FEE = "non_standard_fee"
    PARTIAL_SETTLEMENT = "partial_settlement"
    REFUND_NETTED = "refund_netted"
    CHARGEBACK_DEBIT = "chargeback_debit"
    FX_ROUNDING = "fx_rounding"
    DUPLICATE_UTR = "duplicate_utr"
    MISSING_IN_BANK = "missing_in_bank"
    UNKNOWN_CREDIT = "unknown_credit"


# Breaks a rules engine can resolve with full confidence and no model call.
DETERMINISTICALLY_MATCHABLE = frozenset(
    {
        BreakType.CLEAN,
        BreakType.FEE_NETTING,
        BreakType.MISSING_UTR,
        BreakType.SETTLEMENT_LAG,
        BreakType.AGGREGATED_PAYOUT,
    }
)

# Breaks that require judgement: these are the exception queue the agent works.
REQUIRES_INVESTIGATION = frozenset(BreakType) - DETERMINISTICALLY_MATCHABLE
