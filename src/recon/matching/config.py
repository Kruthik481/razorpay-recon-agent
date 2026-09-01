"""Thresholds for the deterministic matching rules."""

# How many days after settled_on a bank credit may still land.
AMOUNT_DATE_WINDOW_DAYS = 4

# Aggregation works within a declared settlement batch, so the pool is small
# by construction. The subset fallback stays capped anyway: a partially paid
# batch is worth solving, a combinatorial explosion is not.
MAX_AGGREGATION_GROUP_SIZE = 16
MAX_AGGREGATION_SUBSET_SIZE = 5

CONFIDENCE_EXACT_UTR = 1.00
CONFIDENCE_AMOUNT_DATE_WINDOW = 0.90
CONFIDENCE_AGGREGATED_PAYOUT = 0.85
