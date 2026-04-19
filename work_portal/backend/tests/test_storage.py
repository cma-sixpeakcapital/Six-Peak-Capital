import pytest

from app.storage import Storage


def test_load_rocks_default(storage: Storage) -> None:
    data = storage.load_rocks()
    assert data == {"team": [], "rocks": {}, "company_rocks": []}


def test_save_and_load_rocks(storage: Storage) -> None:
    storage.save_rocks({"team": [{"name": "Ana", "role": "Eng"}], "rocks": {"Ana": []}})
    assert storage.load_rocks()["team"][0]["name"] == "Ana"


def test_set_person_rocks_validates_status(storage: Storage) -> None:
    with pytest.raises(ValueError):
        storage.set_person_rocks("Ana", [{"title": "t", "status": "bogus"}])


def test_set_person_rocks_adds_to_team(storage: Storage) -> None:
    data = storage.set_person_rocks("Newbie", [{"title": "ship it", "status": "incomplete"}])
    names = {p["name"] for p in data["team"]}
    assert "Newbie" in names
    assert data["rocks"]["Newbie"][0]["title"] == "ship it"


def test_set_company_rocks(storage: Storage) -> None:
    data = storage.set_company_rocks([
        {"id": "c1", "title": "Hit $10M AUM", "status": "incomplete", "due": "2026-06-30"},
        {"id": "c2", "title": "Launch EOS", "status": "complete"},
    ])
    assert len(data["company_rocks"]) == 2
    assert data["company_rocks"][0]["title"] == "Hit $10M AUM"


def test_set_company_rocks_validates_status(storage: Storage) -> None:
    with pytest.raises(ValueError):
        storage.set_company_rocks([{"title": "t", "status": "bogus"}])


def test_toggle_rock_person_incomplete_to_complete(storage: Storage) -> None:
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "incomplete"}])
    rock = storage.toggle_rock("r1")
    assert rock is not None
    assert rock["status"] == "complete"
    assert storage.load_rocks()["rocks"]["Chris"][0]["status"] == "complete"


def test_toggle_rock_person_complete_to_incomplete(storage: Storage) -> None:
    storage.set_person_rocks("Chris", [{"id": "r1", "title": "t", "status": "complete"}])
    rock = storage.toggle_rock("r1")
    assert rock["status"] == "incomplete"


def test_toggle_rock_company(storage: Storage) -> None:
    storage.set_company_rocks([{"id": "c1", "title": "t", "status": "incomplete"}])
    rock = storage.toggle_rock("c1")
    assert rock["status"] == "complete"
    assert storage.load_rocks()["company_rocks"][0]["status"] == "complete"


def test_toggle_rock_not_found(storage: Storage) -> None:
    assert storage.toggle_rock("nope") is None


def test_save_and_get_meeting(storage: Storage) -> None:
    meeting = {"id": "2026-04-14", "date": "2026-04-14", "title": "L10"}
    storage.save_meeting(meeting)
    got = storage.get_meeting("2026-04-14")
    assert got is not None
    assert got["title"] == "L10"
    assert "saved_at" in got


def test_save_meeting_requires_id_and_date(storage: Storage) -> None:
    with pytest.raises(ValueError):
        storage.save_meeting({"title": "no id"})


def test_list_meetings_sorted_desc(storage: Storage) -> None:
    storage.save_meeting({"id": "a", "date": "2026-01-01"})
    storage.save_meeting({"id": "b", "date": "2026-03-01"})
    storage.save_meeting({"id": "c", "date": "2026-02-01"})
    dates = [m["date"] for m in storage.list_meetings()]
    assert dates == ["2026-03-01", "2026-02-01", "2026-01-01"]


def test_latest_meeting(storage: Storage) -> None:
    assert storage.latest_meeting() is None
    storage.save_meeting({"id": "a", "date": "2026-01-01"})
    storage.save_meeting({"id": "b", "date": "2026-02-01"})
    assert storage.latest_meeting()["id"] == "b"
