"""Persist learned knowledge as JSON.

Plain JSON on purpose: a controller has to be able to read, diff and revert
what the system taught itself. A learned rule nobody can audit is a liability.
"""

from __future__ import annotations

import json
from pathlib import Path

from recon.knowledge.model import Knowledge, LearnedFact

SCHEMA_VERSION = 1


def to_dict(knowledge: Knowledge) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "fee_bps_on_file": list(knowledge.fee_bps_on_file),
        "fx_tolerance_paise": knowledge.fx_tolerance_paise,
        "flat_bank_charges_paise": list(knowledge.flat_bank_charges_paise),
        "facts": [
            {
                "kind": f.kind,
                "value": f.value,
                "support": f.support,
                "source_case_refs": list(f.source_case_refs),
                "note": f.note,
            }
            for f in knowledge.facts
        ],
    }


def from_dict(payload: dict) -> Knowledge:
    """Rebuild Knowledge from JSON, rejecting anything malformed."""
    if not isinstance(payload, dict):
        raise ValueError("knowledge file must contain a JSON object")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported knowledge schema version: {version!r}")
    try:
        return Knowledge(
            fee_bps_on_file=tuple(int(b) for b in payload["fee_bps_on_file"]),
            fx_tolerance_paise=int(payload["fx_tolerance_paise"]),
            flat_bank_charges_paise=tuple(
                int(p) for p in payload.get("flat_bank_charges_paise", ())
            ),
            facts=tuple(
                LearnedFact(
                    kind=str(f["kind"]),
                    value=int(f["value"]),
                    support=int(f["support"]),
                    source_case_refs=tuple(str(c) for c in f["source_case_refs"]),
                    note=str(f.get("note", "")),
                )
                for f in payload.get("facts", ())
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed knowledge file: {exc}") from exc


def save(knowledge: Knowledge, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(knowledge), indent=2, sort_keys=True) + "\n")


def load(path: Path) -> Knowledge:
    """Load knowledge from disk; a missing file means we have learned nothing yet."""
    if not path.exists():
        return Knowledge()
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read knowledge file {path}: {exc}") from exc
    return from_dict(payload)
