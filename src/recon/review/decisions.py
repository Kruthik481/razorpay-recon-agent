"""The human decision log.

Append-only and plain JSON Lines, because this file is the audit trail: it is
what a controller shows when asked why the system started applying a rule it
was never configured with. Decisions are never edited in place; a change of
mind is a new line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class ReviewOutcome(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """One human answer, with a snapshot of exactly what was answered.

    The snapshot matters: promotion must reason about what the reviewer saw,
    not about whatever the verdict looks like after a later re-run.
    """

    case_ref: str
    outcome: ReviewOutcome
    reviewer: str
    decided_at: datetime
    note: str
    settlement_row_ids: tuple[str, ...]
    bank_txn_ids: tuple[str, ...]
    residual_paise: int
    residual_reason: str
    break_type: str | None

    @property
    def is_confirmed(self) -> bool:
        return self.outcome is ReviewOutcome.CONFIRMED


def to_json(decision: ReviewDecision) -> str:
    return json.dumps(
        {
            "case_ref": decision.case_ref,
            "outcome": decision.outcome.value,
            "reviewer": decision.reviewer,
            "decided_at": decision.decided_at.isoformat(),
            "note": decision.note,
            "settlement_row_ids": list(decision.settlement_row_ids),
            "bank_txn_ids": list(decision.bank_txn_ids),
            "residual_paise": decision.residual_paise,
            "residual_reason": decision.residual_reason,
            "break_type": decision.break_type,
        },
        sort_keys=True,
    )


def from_json(line: str) -> ReviewDecision:
    """Parse one log line, rejecting anything that is not a full decision."""
    try:
        payload = json.loads(line)
        return ReviewDecision(
            case_ref=str(payload["case_ref"]),
            outcome=ReviewOutcome(payload["outcome"]),
            reviewer=str(payload["reviewer"]),
            decided_at=datetime.fromisoformat(payload["decided_at"]),
            note=str(payload.get("note", "")),
            settlement_row_ids=tuple(str(r) for r in payload["settlement_row_ids"]),
            bank_txn_ids=tuple(str(t) for t in payload["bank_txn_ids"]),
            residual_paise=int(payload["residual_paise"]),
            residual_reason=str(payload["residual_reason"]),
            break_type=payload.get("break_type"),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed decision line: {exc}") from exc


def append(decisions: tuple[ReviewDecision, ...], path: Path) -> None:
    """Add decisions to the log without rewriting a single existing byte."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for decision in decisions:
            handle.write(to_json(decision) + "\n")


def latest(decisions: tuple[ReviewDecision, ...]) -> tuple[ReviewDecision, ...]:
    """One decision per case: the most recent one.

    The log is append-only, so a reviewer changing their mind writes a second
    line rather than editing the first. Anything reasoning about what people
    decided has to collapse the log this way, or a confirmation that was later
    withdrawn still counts, and a case confirmed twice counts twice.
    """
    by_case = {d.case_ref: d for d in decisions}
    return tuple(by_case.values())


def load(path: Path) -> tuple[ReviewDecision, ...]:
    """Read the whole log. A missing log means nobody has reviewed anything yet."""
    if not path.exists():
        return ()
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read decision log {path}: {exc}") from exc
    return tuple(from_json(line) for line in lines if line.strip())
