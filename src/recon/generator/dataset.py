"""Assemble a full reconciliation period from the scenario builders."""

from __future__ import annotations

from datetime import date
from random import Random

from recon.domain.break_types import BreakType
from recon.domain.models import Dataset
from recon.generator import config
from recon.generator.scenarios import SCENARIO_BUILDERS, ScenarioContext

DEFAULT_PERIOD_START = date(2026, 7, 1)


def allocate_case_counts(total_cases: int, mix: dict[BreakType, int]) -> dict[BreakType, int]:
    """Turn relative weights into exact integer counts using largest remainder.

    Exact counts (rather than sampling) keep the break mix identical across
    runs, so a metric change always reflects a code change.
    """
    if total_cases <= 0:
        raise ValueError(f"total_cases must be positive, got {total_cases}")
    if not mix:
        raise ValueError("break mix must not be empty")

    weight_total = sum(mix.values())
    if weight_total <= 0:
        raise ValueError("break mix weights must sum to a positive number")

    exact = {bt: total_cases * w / weight_total for bt, w in mix.items()}
    counts = {bt: int(value) for bt, value in exact.items()}

    shortfall = total_cases - sum(counts.values())
    by_remainder = sorted(exact, key=lambda bt: exact[bt] - counts[bt], reverse=True)
    for bt in by_remainder[:shortfall]:
        counts = {**counts, bt: counts[bt] + 1}
    return counts


def _ordered_break_types(counts: dict[BreakType, int], rng: Random) -> list[BreakType]:
    sequence = [bt for bt, count in counts.items() for _ in range(count)]
    rng.shuffle(sequence)
    return sequence


def generate_dataset(
    *,
    total_cases: int = config.DEFAULT_CASE_COUNT,
    seed: int = config.DEFAULT_SEED,
    period_start: date = DEFAULT_PERIOD_START,
    mix: dict[BreakType, int] | None = None,
) -> Dataset:
    """Build a deterministic dataset with a ground-truth link per case."""
    rng = Random(seed)
    counts = allocate_case_counts(total_cases, mix or config.BREAK_MIX)

    orders, rows, txns, links = [], [], [], []
    for index, break_type in enumerate(_ordered_break_types(counts, rng)):
        builder = SCENARIO_BUILDERS.get(break_type)
        if builder is None:
            raise KeyError(f"no scenario builder registered for {break_type}")
        result = builder(
            ScenarioContext(
                index=index, rng=rng, period_start=period_start, break_type=break_type
            )
        )
        orders.extend(result.orders)
        rows.extend(result.settlement_rows)
        txns.extend(result.bank_txns)
        links.append(result.link)

    return Dataset(
        orders=tuple(orders),
        settlement_rows=tuple(rows),
        bank_txns=tuple(txns),
        ground_truth=tuple(links),
    )
