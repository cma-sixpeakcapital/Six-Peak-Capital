"""API + render tests for per-rock file links (file-backed storage + Flask)."""
from app.storage import Storage

DROPBOX = "https://www.dropbox.com/scl/fo/4owj3md6qz8/PM?rlkey=msoa6djz5a3yu01nj5g8&dl=0"


def _seed_rock(storage: Storage, owner: str = "Chris", title: str = "Ramsgate PM") -> str:
    rock = storage.add_person_rock(owner, {"title": title})
    return rock["id"]


# --- add / edit / remove through the real endpoints ---------------------------

def test_add_file_via_api(client, storage) -> None:
    rid = _seed_rock(storage)
    res = client.post(f"/api/rocks/{rid}/files", json={"url": DROPBOX, "label": "PM Proposals"})
    assert res.status_code == 200
    entry = res.get_json()
    assert entry["label"] == "PM Proposals"
    assert entry["url"] == DROPBOX
    # persisted
    files = storage.load_rocks()["rocks"]["Chris"][0]["files"]
    assert [f["url"] for f in files] == [DROPBOX]


def test_add_file_preserves_query_string_byte_identical(client, storage) -> None:
    rid = _seed_rock(storage)
    client.post(f"/api/rocks/{rid}/files", json={"url": DROPBOX})
    stored = storage.load_rocks()["rocks"]["Chris"][0]["files"][0]["url"]
    assert stored == DROPBOX                     # rlkey + dl=0 intact


def test_add_file_blank_label_derives(client, storage) -> None:
    rid = _seed_rock(storage)
    entry = client.post(f"/api/rocks/{rid}/files", json={"url": DROPBOX}).get_json()
    assert entry["label"] == "Dropbox folder"


def test_edit_file_via_api(client, storage) -> None:
    rid = _seed_rock(storage)
    fid = client.post(f"/api/rocks/{rid}/files", json={"url": DROPBOX, "label": "A"}).get_json()["id"]
    res = client.patch(f"/api/rocks/{rid}/files/{fid}", json={"label": "Renamed"})
    assert res.status_code == 200
    assert res.get_json()["label"] == "Renamed"


def test_remove_file_via_api(client, storage) -> None:
    rid = _seed_rock(storage)
    fid = client.post(f"/api/rocks/{rid}/files", json={"url": DROPBOX}).get_json()["id"]
    assert client.delete(f"/api/rocks/{rid}/files/{fid}").status_code == 200
    assert storage.load_rocks()["rocks"]["Chris"][0].get("files") == []


def test_add_file_rejects_javascript_url(client, storage) -> None:
    rid = _seed_rock(storage)
    res = client.post(f"/api/rocks/{rid}/files", json={"url": "javascript:alert(1)", "label": "x"})
    assert res.status_code == 400


def test_add_file_unknown_rock_404(client) -> None:
    assert client.post("/api/rocks/nope/files", json={"url": DROPBOX}).status_code == 404


# --- archived rocks reject writes ---------------------------------------------

def test_archived_rock_rejects_file_writes(client, storage) -> None:
    rid = _seed_rock(storage)
    data = storage.load_rocks()
    data["rocks"]["Chris"][0]["archived"] = True
    storage.save_rocks(data)
    assert client.post(f"/api/rocks/{rid}/files", json={"url": DROPBOX}).status_code == 403
    assert client.patch(f"/api/rocks/{rid}/files/x", json={"label": "y"}).status_code == 403
    assert client.delete(f"/api/rocks/{rid}/files/x").status_code == 403


# --- render -------------------------------------------------------------------

def test_render_shows_label_not_raw_url(client, storage) -> None:
    rid = _seed_rock(storage)
    storage.add_rock_file(rid, DROPBOX, "PM Proposals")
    html = client.get("/").get_data(as_text=True)
    assert ">PM Proposals</span>" in html or "PM Proposals" in html
    assert 'rel="noopener noreferrer"' in html
    # raw URL only in the href/title attributes, never as visible chip text
    assert f">{DROPBOX}<" not in html


def test_render_escapes_label(client, storage) -> None:
    rid = _seed_rock(storage)
    storage.add_rock_file(rid, "https://x.com/a", "<script>alert(1)</script>")
    html = client.get("/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_files_nodes_not_counted_as_rocks(client, storage) -> None:
    # Two active person rocks; one carries file links. The KPI band counts
    # `.rock` nodes — the chip <li>s must not inflate that count.
    r1 = _seed_rock(storage, owner="Chris", title="Rock One")
    _seed_rock(storage, owner="Dana", title="Rock Two")
    storage.add_rock_file(r1, DROPBOX, "PM")
    storage.add_rock_file(r1, "https://x.com/b", "B")
    html = client.get("/").get_data(as_text=True)
    # Exactly one `class="rock rock-...` per rock, regardless of file chips.
    assert html.count('class="rock rock-') == 2
