"""JSON schemas for the tools, as the Messages API expects them.

Kept next to the tools rather than inside the provider so that adding a tool
is one change, not two, and so the schemas can be asserted against the actual
function signatures in tests.
"""

from __future__ import annotations

from typing import Any

from recon.agent import config


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


_DATE = {"type": "string", "description": "ISO date, YYYY-MM-DD"}
_PAISE = {"type": "integer", "description": "amount in integer paise"}

TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_settlement_row",
        "description": "Fetch one open settlement row by id.",
        "input_schema": _obj({"settlement_row_id": {"type": "string"}}, ["settlement_row_id"]),
    },
    {
        "name": "get_bank_txn",
        "description": "Fetch one open bank transaction by id.",
        "input_schema": _obj({"bank_txn_id": {"type": "string"}}, ["bank_txn_id"]),
    },
    {
        "name": "get_order",
        "description": "Fetch an order from the merchant's own ledger.",
        "input_schema": _obj({"order_id": {"type": "string"}}, ["order_id"]),
    },
    {
        "name": "find_bank_txns",
        "description": (
            "Search open bank transactions by date range, direction and amount "
            f"range. Returns at most {config.MAX_TOOL_RESULTS} rows, so narrow "
            "the amount range before calling."
        ),
        "input_schema": _obj(
            {
                "date_from": _DATE,
                "date_to": _DATE,
                "direction": {"type": "string", "enum": ["credit", "debit"]},
                "min_paise": _PAISE,
                "max_paise": _PAISE,
            },
            ["date_from", "date_to"],
        ),
    },
    {
        "name": "find_settlement_rows",
        "description": "Search open settlement rows by date range and net amount range.",
        "input_schema": _obj(
            {
                "date_from": _DATE,
                "date_to": _DATE,
                "min_net_paise": _PAISE,
                "max_net_paise": _PAISE,
            },
            ["date_from", "date_to"],
        ),
    },
    {
        "name": "fee_schedule",
        "description": "The fee rates, rounding tolerance and flat charges on file.",
        "input_schema": _obj({}, []),
    },
    {
        "name": "expected_net",
        "description": "Apply the fee schedule forwards: what a gross amount should pay out.",
        "input_schema": _obj(
            {"gross_paise": _PAISE, "fee_bps": {"type": "integer"}},
            ["gross_paise", "fee_bps"],
        ),
    },
    {
        "name": "implied_fee_bps",
        "description": (
            "Apply the fee schedule backwards: the whole basis-point rate that "
            "reproduces an observed payout exactly, if one exists."
        ),
        "input_schema": _obj(
            {"gross_paise": _PAISE, "observed_net_paise": _PAISE},
            ["gross_paise", "observed_net_paise"],
        ),
    },
    {
        "name": "check_sum",
        "description": "Add amounts and report the difference from a target.",
        "input_schema": _obj(
            {
                "amounts_paise": {"type": "array", "items": {"type": "integer"}},
                "target_paise": _PAISE,
            },
            ["amounts_paise", "target_paise"],
        ),
    },
)

SUBMIT_VERDICT_SCHEMA: dict[str, Any] = {
    "name": "submit_verdict",
    "description": "Record the final answer for this case. Call exactly once.",
    "input_schema": _obj(
        {
            "action": {
                "type": "string",
                "enum": [
                    "link",
                    "flag_missing_credit",
                    "flag_unidentified_credit",
                    "no_action",
                ],
            },
            "break_type": {
                "type": "string",
                "description": "Name of the break, or omit if none of them fit.",
            },
            "settlement_row_ids": {"type": "array", "items": {"type": "string"}},
            "bank_txn_ids": {"type": "array", "items": {"type": "string"}},
            "residual_paise": {
                "type": "integer",
                "description": (
                    "Settlement value minus bank movement, in paise. Positive means "
                    "the bank moved less than the report expected."
                ),
            },
            "residual_reason": {
                "type": "string",
                "enum": [
                    "none",
                    "fee_rate_variance",
                    "fx_rounding",
                    "flat_bank_charge",
                    "unreconciled_funds",
                    "unexplained",
                ],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
            "cited_record_ids": {"type": "array", "items": {"type": "string"}},
        },
        ["action", "residual_paise", "residual_reason", "confidence", "rationale"],
    ),
}

ALL_SCHEMAS: tuple[dict[str, Any], ...] = (*TOOL_SCHEMAS, SUBMIT_VERDICT_SCHEMA)
