"""Fail the build if anything was posted that the answer key disagrees with.

This is the project's one non-negotiable invariant, checked across several
seeds and sizes so it cannot pass by luck on the documented configuration.
"""

from __future__ import annotations

import sys

from recon.pipeline import run_pipeline

CONFIGURATIONS = ((200, 3), (300, 11), (500, 7), (750, 23), (1000, 41), (1500, 97))


def main() -> int:
    failures = []
    for cases, seed in CONFIGURATIONS:
        result = run_pipeline(total_cases=cases, seed=seed)
        for cycle in (result.before, result.after):
            if cycle.incorrect_total:
                failures.append(
                    f"{cases} cases / seed {seed} / {cycle.label}: "
                    f"{cycle.incorrect_total} incorrect postings"
                )
        print(
            f"  {cases:>4} cases  seed {seed:>3}  "
            f"straight-through {result.before.straight_through_rate:6.1%}"
            f" -> {result.after.straight_through_rate:6.1%}"
            f"  human queue {result.before.human_cases:>3} -> {result.after.human_cases:>3}"
            f"  wrong 0"
        )

    if failures:
        print("\nFAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("\n  no incorrect postings in any configuration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
