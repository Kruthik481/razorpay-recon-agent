"""The review console: its state machine, its JSON, and its front door."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from recon.review.decisions import ReviewOutcome, load
from recon.server.api import apply_decision, apply_promote, apply_reset, state_payload
from recon.server.app import build_server
from recon.server.session import promote_session, record_decision, start_session

CASES, SEED = 200, 3


@pytest.fixture
def session(tmp_path):
    return start_session(
        total_cases=CASES,
        seed=SEED,
        knowledge_path=tmp_path / "knowledge.json",
        decisions_path=tmp_path / "decisions.jsonl",
    )


def _confirm_everything(session):
    """Confirm every open case, one immutable session at a time."""
    for item in session.queue:
        session = record_decision(session, item.case_ref, ReviewOutcome.CONFIRMED, "test")
    return session


# --- session ---------------------------------------------------------------


def test_a_fresh_session_opens_with_a_queue_and_nothing_learned(session):
    assert session.queue
    assert session.knowledge.facts == ()
    assert session.now == session.baseline
    assert session.cycle.incorrect_total == 0


def test_recording_a_decision_leaves_the_original_session_untouched(session):
    # Arrange
    case_ref = session.queue[0].case_ref

    # Act
    updated = record_decision(session, case_ref, ReviewOutcome.CONFIRMED, "test")

    # Assert
    assert session.decisions == ()
    assert updated.decisions[0].case_ref == case_ref
    assert updated.decided == {case_ref}


def test_a_decision_is_written_to_the_log_immediately(session):
    case_ref = session.queue[0].case_ref
    record_decision(session, case_ref, ReviewOutcome.REJECTED, "test")

    written = load(session.decisions_path)

    assert [d.case_ref for d in written] == [case_ref]
    assert written[0].outcome is ReviewOutcome.REJECTED


def test_deciding_a_case_that_is_not_open_is_refused(session):
    with pytest.raises(ValueError, match="no open case"):
        record_decision(session, "exc_not_a_case", ReviewOutcome.CONFIRMED, "test")


def test_promotion_shrinks_the_queue_and_leaves_nothing_wrong(session):
    # Arrange
    reviewed = _confirm_everything(session)

    # Act
    promoted = promote_session(reviewed)

    # Assert
    assert promoted.promotions
    assert promoted.now.human_queue < promoted.baseline.human_queue
    assert promoted.now.straight_through > promoted.baseline.straight_through
    assert promoted.now.incorrect == 0


def test_promotion_writes_the_knowledge_file(session):
    promoted = promote_session(_confirm_everything(session))
    assert promoted.knowledge_path.exists()
    assert json.loads(promoted.knowledge_path.read_text(encoding="utf-8"))["facts"]


def test_promoting_nothing_changes_nothing(session):
    unchanged = promote_session(session)
    assert unchanged.promotions == ()
    assert unchanged.now == session.baseline


def test_reset_clears_the_log_and_the_learned_rules(session):
    promoted = promote_session(_confirm_everything(session))
    assert promoted.knowledge.facts

    fresh = apply_reset(promoted)[0]

    assert fresh.decisions == ()
    assert fresh.knowledge.facts == ()
    assert not fresh.decisions_path.exists()
    assert fresh.now == session.baseline


# --- api -------------------------------------------------------------------


def test_the_state_payload_carries_what_the_page_renders(session):
    payload = state_payload(session)
    assert set(payload) == {
        "baseline",
        "now",
        "queue",
        "knowledge",
        "promotions",
        "confirmed",
        "rejected",
        "min_support",
        "materiality",
    }
    assert payload["queue"][0]["decision"] is None
    assert payload["now"]["incorrect"] == 0


def test_the_state_payload_is_json_serialisable(session):
    assert json.loads(json.dumps(state_payload(session)))["queue"]


def test_a_decision_shows_up_in_the_next_payload(session):
    case_ref = session.queue[0].case_ref
    _, payload = apply_decision(session, {"case_ref": case_ref, "outcome": "confirmed"})
    decided = [i for i in payload["queue"] if i["case_ref"] == case_ref]
    assert decided[0]["decision"] == "confirmed"
    assert payload["confirmed"] == 1


@pytest.mark.parametrize(
    "body",
    [{}, {"case_ref": "x"}, {"outcome": "confirmed"}, {"case_ref": 1, "outcome": "confirmed"}],
)
def test_a_malformed_decision_is_refused(session, body):
    with pytest.raises(ValueError):
        apply_decision(session, body)


def test_an_unknown_outcome_is_refused(session):
    body = {"case_ref": session.queue[0].case_ref, "outcome": "maybe"}
    with pytest.raises(ValueError):
        apply_decision(session, body)


def test_promoting_through_the_api_reports_what_was_learned(session):
    _, payload = apply_promote(_confirm_everything(session))
    assert payload["promotions"]
    assert payload["now"]["human_queue"] < payload["baseline"]["human_queue"]


# --- http ------------------------------------------------------------------


@pytest.fixture
def console(tmp_path):
    """A real server on an ephemeral loopback port."""
    server, url = build_server(
        total_cases=CASES,
        seed=SEED,
        knowledge_path=tmp_path / "knowledge.json",
        decisions_path=tmp_path / "decisions.jsonl",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = re.search(r'data-token="([^"]+)"', _get(url)).group(1)
    try:
        yield url, token
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str, token: str | None = None) -> str:
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-Recon-Token", token)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode()


def _post(url: str, path: str, body: dict, token: str | None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url + path.lstrip("/"),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("X-Recon-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_the_console_binds_to_loopback_only(console):
    url, _ = console
    assert url.startswith("http://127.0.0.1:")


def test_the_page_serves_itself_with_a_token(console):
    url, token = console
    page = _get(url)
    assert "<title>Review console</title>" in page
    assert token in page


def test_state_needs_the_token(console):
    url, token = console
    with pytest.raises(urllib.error.HTTPError) as raised:
        _get(url + "api/state")
    assert raised.value.code == 403
    assert json.loads(_get(url + "api/state", token))["queue"]


def test_every_write_needs_the_token(console):
    url, _ = console
    for path in ("api/decision", "api/promote", "api/reset"):
        status, payload = _post(url, path, {}, None)
        assert status == 403
        assert "token" in payload["error"]


def test_an_unknown_path_is_a_flat_404(console):
    url, token = console
    with pytest.raises(urllib.error.HTTPError) as raised:
        _get(url + "../../etc/passwd", token)
    assert raised.value.code == 404
    assert _post(url, "api/anything", {}, token)[0] == 404


def test_a_bad_case_ref_is_a_400_not_a_crash(console):
    url, token = console
    status, payload = _post(
        url, "api/decision", {"case_ref": "nope", "outcome": "confirmed"}, token
    )
    assert status == 400
    assert "no open case" in payload["error"]


def test_the_whole_loop_works_over_http(console):
    # Arrange
    url, token = console
    state = json.loads(_get(url + "api/state", token))
    before = state["now"]["human_queue"]

    # Act: confirm everything open, then promote.
    for item in state["queue"]:
        status, state = _post(
            url, "api/decision", {"case_ref": item["case_ref"], "outcome": "confirmed"}, token
        )
        assert status == 200
    status, state = _post(url, "api/promote", {}, token)

    # Assert
    assert status == 200
    assert state["promotions"]
    assert state["now"]["human_queue"] < before
    assert state["now"]["incorrect"] == 0


def test_a_withdrawn_confirmation_stops_being_counted(session):
    # Arrange: confirm a case, then change our mind about it.
    case_ref = session.queue[0].case_ref
    confirmed = record_decision(session, case_ref, ReviewOutcome.CONFIRMED, "test")

    # Act
    withdrawn = record_decision(confirmed, case_ref, ReviewOutcome.REJECTED, "test")
    payload = state_payload(withdrawn)

    # Assert: two lines in the log, one standing decision.
    assert len(load(withdrawn.decisions_path)) == 2
    assert (payload["confirmed"], payload["rejected"]) == (0, 1)
    item = next(i for i in payload["queue"] if i["case_ref"] == case_ref)
    assert item["decision"] == "rejected"
