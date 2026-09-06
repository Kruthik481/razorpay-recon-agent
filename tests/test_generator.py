from recon.domain.break_types import BreakType
from recon.generator.config import BREAK_MIX
from recon.generator.dataset import allocate_case_counts, generate_dataset


def test_allocated_counts_sum_to_requested_total():
    counts = allocate_case_counts(500, BREAK_MIX)

    assert sum(counts.values()) == 500


def test_allocation_covers_every_break_type_in_the_mix():
    counts = allocate_case_counts(500, BREAK_MIX)

    assert set(counts) == set(BREAK_MIX)


def test_allocation_rejects_non_positive_totals():
    try:
        allocate_case_counts(0, BREAK_MIX)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError for zero cases")


def test_same_seed_produces_identical_datasets():
    first = generate_dataset(total_cases=120, seed=42)
    second = generate_dataset(total_cases=120, seed=42)

    assert first == second


def test_different_seeds_produce_different_datasets():
    first = generate_dataset(total_cases=120, seed=1)
    second = generate_dataset(total_cases=120, seed=2)

    assert first != second


def test_every_case_has_exactly_one_ground_truth_link():
    dataset = generate_dataset(total_cases=200, seed=7)

    assert len(dataset.ground_truth) == 200
    assert len({link.case_id for link in dataset.ground_truth}) == 200


def test_missing_in_bank_case_emits_no_bank_transaction():
    dataset = generate_dataset(total_cases=200, seed=7)

    links = [
        link for link in dataset.ground_truth if link.break_type is BreakType.MISSING_IN_BANK
    ]

    assert links, "expected at least one missing_in_bank case"
    assert all(link.bank_txn_ids == () for link in links)


def test_unknown_credit_case_emits_no_settlement_row():
    dataset = generate_dataset(total_cases=200, seed=7)

    links = [
        link for link in dataset.ground_truth if link.break_type is BreakType.UNKNOWN_CREDIT
    ]

    assert links, "expected at least one unknown_credit case"
    assert all(link.settlement_row_ids == () for link in links)


def test_record_ids_are_globally_unique():
    dataset = generate_dataset(total_cases=300, seed=7)

    row_ids = [r.settlement_row_id for r in dataset.settlement_rows]
    txn_ids = [t.bank_txn_id for t in dataset.bank_txns]
    order_ids = [o.order_id for o in dataset.orders]

    assert len(row_ids) == len(set(row_ids))
    assert len(txn_ids) == len(set(txn_ids))
    assert len(order_ids) == len(set(order_ids))
