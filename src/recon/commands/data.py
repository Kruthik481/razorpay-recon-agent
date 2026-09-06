"""Dataset commands: score the deterministic matcher, or write the period out."""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path

from recon.domain.models import Dataset
from recon.evaluation.metrics import evaluate
from recon.evaluation.report import render
from recon.knowledge.model import Knowledge
from recon.matching.engine import reconcile_dataset

EXPORTS = ("orders", "settlement_rows", "bank_txns", "ground_truth")


def write_csv(path: Path, records: tuple) -> int:
    """Write frozen dataclasses to CSV. Returns the number of rows written."""
    if not records:
        path.write_text("", encoding="utf-8")
        return 0
    header = [f.name for f in fields(records[0])]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))
    return len(records)


def cmd_evaluate(dataset: Dataset, knowledge: Knowledge) -> int:
    """Score the deterministic matcher on its own, with no agent involved."""
    outcome = reconcile_dataset(dataset, knowledge)
    print(render(evaluate(dataset, outcome)))
    return 0


def cmd_export(dataset: Dataset, out_dir: Path) -> int:
    """Write the generated period to CSV so it can be opened in a spreadsheet."""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"cannot create output directory {out_dir}: {exc}")
        return 1

    for name in EXPORTS:
        target = out_dir / f"{name}.csv"
        count = write_csv(target, getattr(dataset, name))
        print(f"  wrote {count:>5} rows -> {target}")
    return 0
