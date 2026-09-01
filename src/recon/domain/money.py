"""Integer-only money arithmetic.

Fee and tax are derived, never stored as floats, and always rounded
half-up in paise so that generator and matcher agree exactly.
"""

from __future__ import annotations

from typing import NamedTuple

BPS_DIVISOR = 10_000


class FeeSplit(NamedTuple):
    gross_paise: int
    fee_paise: int
    tax_paise: int
    net_paise: int


def apply_bps(amount_paise: int, bps: int) -> int:
    """Apply a basis-point rate, rounding half-up, using integer math only."""
    if amount_paise < 0:
        raise ValueError(f"amount_paise must be non-negative, got {amount_paise}")
    if bps < 0:
        raise ValueError(f"bps must be non-negative, got {bps}")
    return (amount_paise * bps + BPS_DIVISOR // 2) // BPS_DIVISOR


def split_fees(gross_paise: int, fee_bps: int, tax_on_fee_bps: int) -> FeeSplit:
    """Split a gross amount into processor fee, tax on that fee, and net payout."""
    fee_paise = apply_bps(gross_paise, fee_bps)
    tax_paise = apply_bps(fee_paise, tax_on_fee_bps)
    return FeeSplit(
        gross_paise=gross_paise,
        fee_paise=fee_paise,
        tax_paise=tax_paise,
        net_paise=gross_paise - fee_paise - tax_paise,
    )
