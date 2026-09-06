"""Tools are bounded, scoped to open records, and honest about arithmetic."""

from __future__ import annotations

from datetime import date

import pytest

from recon.agent import config, tools
from recon.agent.tools import ToolContext
from recon.domain.models import TxnDirection
from recon.domain.money import split_fees
from recon.knowledge.model import Knowledge, LearnedFact
from tests.conftest import SETTLED_ON, make_context, make_order, make_row, make_txn


def test_a_reconciled_row_is_invisible_to_the_agent():
    # Arrange: the row exists in the ledger but is no longer open.
    ctx = make_context(rows=(make_row("setl_1"),))
    closed = ToolContext(ctx.index, frozenset(), frozenset(), Knowledge())

    # Act
    result = tools.get_settlement_row(closed, "setl_1")

    # Assert
    assert result["error"] == "not an open settlement row"


def test_unknown_ids_return_an_error_rather_than_raising():
    ctx = make_context()
    assert "error" in tools.get_order(ctx, "order_missing")
    assert "error" in tools.get_bank_txn(ctx, "bank_missing")


def test_an_order_is_readable_while_a_row_against_it_is_open():
    ctx = make_context(rows=(make_row("setl_1"),), orders=(make_order(),))
    assert tools.get_order(ctx, "order_x")["gross_paise"] == 1_000_000


def test_an_order_with_nothing_open_against_it_is_out_of_scope():
    # Already reconciled, so none of the agent's business.
    ctx = make_context(orders=(make_order(),))
    assert "error" in tools.get_order(ctx, "order_x")


def test_search_results_are_capped():
    txns = tuple(
        make_txn(f"bank_{i:03d}", amount_paise=1_000 + i)
        for i in range(config.MAX_TOOL_RESULTS + 10)
    )
    ctx = make_context(txns=txns)
    hits = tools.find_bank_txns(ctx, date_from="2026-07-01", date_to="2026-07-31")
    assert len(hits) == config.MAX_TOOL_RESULTS


def test_search_respects_direction_and_amount_range():
    ctx = make_context(
        txns=(
            make_txn("bank_credit", amount_paise=500),
            make_txn("bank_debit", amount_paise=500, direction=TxnDirection.DEBIT),
            make_txn("bank_big", amount_paise=5_000),
        )
    )
    hits = tools.find_bank_txns(
        ctx, date_from="2026-07-01", date_to="2026-07-31", min_paise=100, max_paise=1_000
    )
    assert [h["bank_txn_id"] for h in hits] == ["bank_credit"]


def test_search_rejects_a_backwards_window():
    ctx = make_context()
    with pytest.raises(ValueError, match="precedes"):
        tools.find_bank_txns(ctx, date_from="2026-07-10", date_to="2026-07-01")


def test_settlement_search_filters_on_net_amount():
    ctx = make_context(
        rows=(make_row("setl_small", net_paise=1_000), make_row("setl_big", net_paise=9_000))
    )
    hits = tools.find_settlement_rows(
        ctx, date_from="2026-07-01", date_to="2026-07-31", min_net_paise=5_000
    )
    assert [h["settlement_row_id"] for h in hits] == ["setl_big"]


@pytest.mark.parametrize("bps", [150, 200, 275, 350])
def test_implied_rate_recovers_the_rate_that_produced_the_payout(bps):
    # Arrange
    gross = 1_234_567
    net = split_fees(gross, bps, 1_800).net_paise

    # Act
    result = tools.implied_fee_bps(None, gross_paise=gross, observed_net_paise=net)

    # Assert
    assert result == {"exact": True, "fee_bps": bps, "shortfall_paise": gross - net}


def test_implied_rate_refuses_when_no_whole_rate_fits():
    result = tools.implied_fee_bps(None, gross_paise=1_000_000, observed_net_paise=976_361)
    assert result["exact"] is False


def test_implied_rate_rejects_a_payout_larger_than_gross():
    result = tools.implied_fee_bps(None, gross_paise=1_000, observed_net_paise=2_000)
    assert result["exact"] is False
    assert result["reason"] == "payout exceeds gross"


def test_implied_rate_rejects_a_non_positive_gross():
    assert "error" in tools.implied_fee_bps(None, gross_paise=0, observed_net_paise=0)


def test_expected_net_rejects_negative_inputs():
    assert "error" in tools.expected_net(None, gross_paise=-1, fee_bps=200)


def test_check_sum_reports_the_gap_rather_than_a_verdict():
    result = tools.check_sum(None, amounts_paise=[600, 400], target_paise=1_001)
    assert result == {
        "total_paise": 1_000,
        "target_paise": 1_001,
        "residual_paise": 1,
        "ties_out": False,
    }


def test_fee_schedule_exposes_what_was_learned():
    fact = LearnedFact("fee_rate_bps", 275, 5, ("c",), "note visible to the model")
    ctx = make_context(knowledge=Knowledge().with_fee_rate(275, fact))
    schedule = tools.fee_schedule(ctx)
    assert schedule["fee_bps_on_file"] == [200, 275]
    assert schedule["learned_facts"] == ["note visible to the model"]


def test_default_window_brackets_the_settlement_date():
    start, end = tools.default_window(SETTLED_ON)
    assert date.fromisoformat(start) < SETTLED_ON < date.fromisoformat(end)
