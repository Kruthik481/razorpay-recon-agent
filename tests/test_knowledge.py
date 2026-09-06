"""Knowledge is immutable, round-trips through JSON, and rejects junk."""

from __future__ import annotations

import json

import pytest

from recon.knowledge.model import Knowledge, LearnedFact
from recon.knowledge.store import from_dict, load, save, to_dict

FACT = LearnedFact("fee_rate_bps", 275, 5, ("case_a",), "learned in a test")


def test_adding_a_fee_rate_returns_a_new_object():
    # Arrange
    original = Knowledge()

    # Act
    updated = original.with_fee_rate(275, FACT)

    # Assert
    assert original.fee_bps_on_file == (200,)
    assert updated.fee_bps_on_file == (200, 275)
    assert updated.facts == (FACT,)


def test_learning_a_rate_already_on_file_changes_nothing():
    knowledge = Knowledge().with_fee_rate(275, FACT)
    assert knowledge.with_fee_rate(275, FACT) is knowledge


def test_tolerance_only_widens():
    knowledge = Knowledge().with_fx_tolerance(10, FACT)
    assert knowledge.with_fx_tolerance(5, FACT).fx_tolerance_paise == 10


def test_knowledge_round_trips_through_json():
    original = (
        Knowledge()
        .with_fee_rate(275, FACT)
        .with_fx_tolerance(7, FACT)
        .with_flat_charge(1180, FACT)
    )
    assert from_dict(json.loads(json.dumps(to_dict(original)))) == original


def test_missing_file_means_nothing_learned(tmp_path):
    assert load(tmp_path / "absent.json") == Knowledge()


def test_saved_knowledge_reloads(tmp_path):
    path = tmp_path / "nested" / "knowledge.json"
    original = Knowledge().with_flat_charge(1180, FACT)
    save(original, path)
    assert load(path) == original


def test_unknown_schema_version_is_rejected():
    with pytest.raises(ValueError, match="schema version"):
        from_dict({"schema_version": 99})


def test_malformed_payload_is_rejected():
    with pytest.raises(ValueError, match="malformed"):
        from_dict({"schema_version": 1, "fee_bps_on_file": "not a list"})


def test_unreadable_json_is_rejected(tmp_path):
    path = tmp_path / "knowledge.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read"):
        load(path)
