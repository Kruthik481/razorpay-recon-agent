"""Tunable constants for synthetic dataset generation.

Values are chosen to look like a mid-size Indian merchant settling daily
through a PSP: ~2% MDR, 18% GST on the fee, T+1 settlement.
"""

from recon.domain.break_types import BreakType

STANDARD_FEE_BPS = 200
GST_ON_FEE_BPS = 1_800

# A promotional / renegotiated rate the recon config does not know about.
NON_STANDARD_FEE_BPS = 275

MIN_ORDER_PAISE = 49_900
MAX_ORDER_PAISE = 2_500_000

STANDARD_SETTLEMENT_LAG_DAYS = 1
LATE_SETTLEMENT_LAG_DAYS = 3

PARTIAL_FIRST_TRANCHE_BPS = 6_000
FX_ROUNDING_DRIFT_PAISE = 7
AGGREGATED_BATCH_SIZE = 3
REFUND_FRACTION_BPS = 3_000

PERIOD_DAYS = 28
DEFAULT_CASE_COUNT = 500
DEFAULT_SEED = 7

MERCHANT_ID = "acc_QeF3xKmA91"
CURRENCY = "INR"

# Relative frequency of each break type. Clean dominates, as it does in
# production — the whole point is that the tail is where the cost lives.
BREAK_MIX: dict[BreakType, int] = {
    BreakType.CLEAN: 58,
    BreakType.FEE_NETTING: 12,
    BreakType.SETTLEMENT_LAG: 8,
    BreakType.MISSING_UTR: 5,
    BreakType.AGGREGATED_PAYOUT: 4,
    BreakType.NON_STANDARD_FEE: 3,
    BreakType.PARTIAL_SETTLEMENT: 2,
    BreakType.REFUND_NETTED: 2,
    BreakType.FX_ROUNDING: 2,
    BreakType.CHARGEBACK_DEBIT: 1,
    BreakType.DUPLICATE_UTR: 1,
    BreakType.MISSING_IN_BANK: 1,
    BreakType.UNKNOWN_CREDIT: 1,
}
