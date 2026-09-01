from recon.domain.break_types import DETERMINISTICALLY_MATCHABLE
from recon.evaluation.metrics import evaluate
from recon.generator.dataset import generate_dataset
from recon.matching.engine import reconcile_dataset


def _report(cases: int = 500, seed: int = 7):
    dataset = generate_dataset(total_cases=cases, seed=seed)
    return evaluate(dataset, reconcile_dataset(dataset))


def test_matcher_makes_no_incorrect_matches():
    # The headline safety property: never post a wrong linkage.
    assert _report().incorrect_matches == 0


def test_precision_is_perfect_when_there_are_no_incorrect_matches():
    report = _report()

    assert report.precision == 1.0


def test_deterministic_break_types_are_fully_recalled():
    report = _report()

    for score in report.by_break_type:
        if score.break_type in DETERMINISTICALLY_MATCHABLE:
            assert score.recall == 1.0, f"{score.break_type} recall {score.recall}"


def test_judgement_cases_are_left_for_the_agent():
    report = _report()

    for score in report.by_break_type:
        if score.break_type not in DETERMINISTICALLY_MATCHABLE:
            assert score.correctly_matched == 0, f"{score.break_type} was auto-matched"


def test_exception_queue_is_not_empty():
    assert _report().exception_queue_size > 0


def test_results_are_stable_across_runs():
    assert _report() == _report()
