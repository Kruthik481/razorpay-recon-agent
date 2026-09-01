from recon.generator.dataset import generate_dataset
from recon.matching.engine import reconcile, reconcile_dataset


def test_no_record_is_ever_claimed_by_two_proposals():
    dataset = generate_dataset(total_cases=300, seed=7)

    outcome = reconcile_dataset(dataset)

    seen_rows, seen_txns = set(), set()
    for proposal in outcome.matches:
        assert not (seen_rows & proposal.settlement_row_ids)
        assert not (seen_txns & proposal.bank_txn_ids)
        seen_rows |= proposal.settlement_row_ids
        seen_txns |= proposal.bank_txn_ids


def test_matched_and_unmatched_partition_the_whole_dataset():
    dataset = generate_dataset(total_cases=300, seed=7)

    outcome = reconcile_dataset(dataset)

    matched_rows = {r for p in outcome.matches for r in p.settlement_row_ids}
    matched_txns = {t for p in outcome.matches for t in p.bank_txn_ids}

    assert matched_rows | outcome.unmatched_settlement_row_ids == {
        r.settlement_row_id for r in dataset.settlement_rows
    }
    assert matched_txns | outcome.unmatched_bank_txn_ids == {
        t.bank_txn_id for t in dataset.bank_txns
    }


def test_empty_input_produces_an_empty_outcome():
    outcome = reconcile((), ())

    assert outcome.matches == ()
    assert outcome.exception_queue_size == 0
