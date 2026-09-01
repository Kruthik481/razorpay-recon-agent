"""Command line entry point.

    python -m recon.cli evaluate --cases 500 --seed 7
    python -m recon.cli export --out data/
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict, fields
from pathlib import Path

from recon.domain.models import Dataset
from recon.evaluation.metrics import evaluate
from recon.evaluation.report import render
from recon.generator import config
from recon.generator.dataset import generate_dataset
from recon.matching.engine import reconcile_dataset

_EXPORTS = ("orders", "settlement_rows", "bank_txns", "ground_truth")


def _write_csv(path: Path, records: tuple) -> int:
    """Write a tuple of frozen dataclasses to CSV. Returns rows written."""
    if not records:
        path.write_text("")
        return 0
    header = [f.name for f in fields(records[0])]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for record in records:
            writer.writerow({k: v for k, v in asdict(record).items()})
    return len(records)


def _export(dataset: Dataset, out_dir: Path) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"cannot create output directory {out_dir}: {exc}") from exc

    for name in _EXPORTS:
        target = out_dir / f"{name}.csv"
        count = _write_csv(target, getattr(dataset, name))
        print(f"  wrote {count:>5} rows -> {target}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recon", description=__doc__)
    parser.add_argument("command", choices=("evaluate", "export"))
    parser.add_argument("--cases", type=int, default=config.DEFAULT_CASE_COUNT)
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=Path("data"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        dataset = generate_dataset(total_cases=args.cases, seed=args.seed)
    except (ValueError, KeyError) as exc:
        print(f"failed to generate dataset: {exc}", file=sys.stderr)
        return 1

    if args.command == "export":
        _export(dataset, args.out)
        return 0

    outcome = reconcile_dataset(dataset)
    print(render(evaluate(dataset, outcome)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
