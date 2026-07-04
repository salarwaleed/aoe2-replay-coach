"""The ownership ledger that attributes anonymous QUEUE production to players
via provable building ownership — and, crucially, never guesses when the
evidence conflicts."""
from pipeline.config import UNATTRIBUTED_PLAYER_ID
from pipeline.replay_parser import (
    _record_ownership_claims,
    _attribute_queue_events,
)


def test_claim_records_object_to_player():
    ledger: dict[int, int] = {}
    conflict = _record_ownership_claims(
        ledger, {"player_id": 1, "object_ids": [4116]}
    )
    assert conflict == 0
    assert ledger == {4116: 1}


def test_payload_without_player_or_objects_is_ignored():
    ledger: dict[int, int] = {}
    assert _record_ownership_claims(ledger, {"object_ids": [10]}) == 0
    assert _record_ownership_claims(ledger, {"player_id": 2, "object_ids": []}) == 0
    assert ledger == {}


def test_conflicting_claim_is_discarded_not_guessed():
    ledger = {4116: 1}
    conflict = _record_ownership_claims(
        ledger, {"player_id": 2, "object_ids": [4116]}
    )
    assert conflict == 1
    # The disputed object is removed entirely — the bot refuses to pick a side.
    assert 4116 not in ledger


def test_queue_event_is_attributed_from_ledger():
    ledger = {4116: 1}
    events = [{
        "action": "QUEUE",
        "player_id": UNATTRIBUTED_PLAYER_ID,
        "extras": {"building_ids": [4116]},
    }]
    _attribute_queue_events(events, ledger)
    assert events[0]["player_id"] == 1
    assert events[0]["extras"]["attributed_via"] == "ownership_ledger"


def test_unknown_building_stays_unattributed():
    ledger = {4116: 1}
    events = [{
        "action": "QUEUE",
        "player_id": UNATTRIBUTED_PLAYER_ID,
        "extras": {"building_ids": [9999]},  # not in the ledger
    }]
    _attribute_queue_events(events, ledger)
    assert events[0]["player_id"] == UNATTRIBUTED_PLAYER_ID
    assert "attributed_via" not in events[0]["extras"]


def test_building_owned_by_two_players_is_not_attributed():
    ledger = {10: 1, 20: 2}
    events = [{
        "action": "QUEUE",
        "player_id": UNATTRIBUTED_PLAYER_ID,
        "extras": {"building_ids": [10, 20]},  # conflicting owners
    }]
    _attribute_queue_events(events, ledger)
    assert events[0]["player_id"] == UNATTRIBUTED_PLAYER_ID
