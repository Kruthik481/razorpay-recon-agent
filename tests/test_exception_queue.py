"""Clustering uses only keys a real settlement report publishes."""

from __future__ import annotations

from recon.agent.exceptions import build_exception_queue
from recon.agent.index import build_index
from recon.domain.models import Dataset
from recon.matching.result import ReconOutcome
from tests.conftest import make_row, make_txn


def _queue(rows, txns):
    dataset = Dataset(orders=(), settlement_rows=rows, bank_txns=txns, ground_truth=())
    outcome = ReconOutcome(
        matches=(),
        unmatched_settlement_row_ids=frozenset(r.settlement_row_id for r in rows),
        unmatched_bank_txn_ids=frozenset(t.bank_txn_id for t in txns),
    )
    return build_exception_queue(outcome, build_index(dataset))


def test_unrelated_records_become_separate_cases():
    cases = _queue(
        (make_row("setl_1", order_id="order_1"), make_row("setl_2", order_id="order_2")),
        (),
    )
    assert len(cases) == 2


def test_rows_sharing_an_order_id_are_one_case():
    cases = _queue(
        (make_row("setl_1", order_id="order_1"), make_row("setl_2", order_id="order_1")),
        (),
    )
    assert len(cases) == 1
    assert set(cases[0].settlement_row_ids) == {"setl_1", "setl_2"}


def test_a_shared_utr_pulls_bank_transactions_into_the_case():
    cases = _queue(
        (make_row("setl_1", utr="UTR1", order_id="order_1"),),
        (make_txn("bank_1", utr="UTR1"),),
    )
    assert cases[0].settlement_row_ids == ("setl_1",)
    assert cases[0].bank_txn_ids == ("bank_1",)


def test_a_credit_with_no_shared_key_stands_alone():
    cases = _queue((make_row("setl_1", order_id="order_1"),), (make_txn("bank_1"),))
    assert len(cases) == 2
    # Cases carrying settlement rows are worked first.
    assert cases[0].settlement_row_ids and not cases[1].settlement_row_ids


def test_case_order_is_stable_across_runs():
    rows = tuple(make_row(f"setl_{i}", order_id=f"order_{i}") for i in range(6))
    assert [c.case_ref for c in _queue(rows, ())] == [c.case_ref for c in _queue(rows, ())]


def test_an_empty_outcome_produces_no_cases():
    assert _queue((), ()) == ()


def test_record_count_covers_both_sides():
    case = _queue((make_row("setl_1", utr="U"),), (make_txn("bank_1", utr="U"),))[0]
    assert case.record_count == 2


def test_the_ledger_index_cannot_be_written_to():
    # One index is shared by every case in a run; a stray write from one case
    # would corrupt every case after it.
    import pytest

    from recon.agent.index import build_index
    from recon.domain.models import Dataset

    index = build_index(Dataset((), (make_row("setl_1"),), (), ()))
    with pytest.raises(TypeError):
        index.rows_by_id["setl_2"] = make_row("setl_2")
