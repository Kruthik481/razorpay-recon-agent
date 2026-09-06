"""Thresholds for the exception agent, its tools and its safety gate.

Every number here is a control. They are gathered in one file so a finance
controller can read the whole risk posture of the system on one screen.
"""

# --- retrieval bounds -------------------------------------------------------
# A tool call must never be able to return the whole ledger: unbounded results
# blow up prompt cost and let a model pick a plausible-looking stranger.
MAX_TOOL_RESULTS = 25
MAX_TOOL_CALLS_PER_CASE = 12

# How far around a settlement date a counterparty may be looked for.
SEARCH_WINDOW_BEFORE_DAYS = 1
SEARCH_WINDOW_AFTER_DAYS = 4

# --- gate -------------------------------------------------------------------
AUTO_APPLY_CONFIDENCE = 0.85
REVIEW_CONFIDENCE = 0.50

# No automatic posting or automatic write-off above this residual, at any
# confidence and whatever the explanation. Rs 500.
MATERIALITY_PAISE = 50_000

# Plausible bounds for any merchant discount rate. Outside this band the
# arithmetic is coincidence, not a fee.
MIN_PLAUSIBLE_FEE_BPS = 100
MAX_PLAUSIBLE_FEE_BPS = 500

# The most anyone could plausibly hold back from a payout before it stops being
# a deduction and starts being a different transaction. Used when asking the
# opposite question: could *any* open settlement row explain this credit?
MAX_DEDUCTION_BPS = 500

# --- policy confidences -----------------------------------------------------
# Set per evidence class, not per case, so they can be argued about directly.
CONFIDENCE_EXACT_TIE_OUT = 0.95
CONFIDENCE_KNOWN_FEE_RATE = 0.92
CONFIDENCE_UNIQUE_SPLIT = 0.90
CONFIDENCE_EXACT_DEBIT = 0.93
CONFIDENCE_KNOWN_TOLERANCE = 0.88
CONFIDENCE_ORPHAN_FLAG = 0.90
CONFIDENCE_UNKNOWN_FEE_RATE = 0.55
CONFIDENCE_COLLECTIVE_TIE_OUT = 0.75
CONFIDENCE_UNEXPLAINED = 0.30
