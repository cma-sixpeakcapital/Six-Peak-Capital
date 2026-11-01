"""API + render tests for per-to-do file links (file-backed storage + Flask).

To-dos reuse the rock-files rules (app/rock_files.py): http(s) only, URL stored
verbatim, label derived when blank, capped per item.
"""
from app.rock_files import MAX_FILES_PER_ROCK
from app.storage import Storage

DROPBOX = "https://www.dropbox.com/scl/fi/abc123/Review.xlsx?rlkey=zz9&dl=0"


def _seed_todo(storage: Storage, task: str = "Review the LIHTC checklist") -> str:
    return storage.add_todo({"owner": "Chris Aiello", "task": task, "due": "2026-11-03"})["id"]


def _files(storage: Storage, tid: str) -> list[dict]:
    return next(t for t in storage.load_rocks()["todos"] if t["id"] == tid).get("files") or []


def test_add_todo_file_via_api(client, storage) -> None:
    tid = _seed_todo(storage)
    res = client.post(f"/api/todos/{tid}/files", json={"url": DROPBOX, "label": "CMA review"})
    assert res.status_code == 200
    assert res.get_json()["label"] == "CMA review"
    assert [f["url"] for f in _files(storage, tid)] == [DROPBOX]   # query string intact


def test_add_todo_file_blank_label_derives_filename(client, storage) -> None:
    tid = _seed_todo(storage)
    entry = client.post(f"/api/todos/{tid}/files", json={"url": DROPBOX}).get_json()
    assert entry["label"] == "Review.xlsx"


def test_edit_and_remove_todo_file(client, storage) -> None:
    tid = _seed_todo(storage)
    fid = client.post(f"/api/todos/{tid}/files", json={"url": DROPBOX}).get_json()["id"]
    res = client.patch(f"/api/todos/{tid}/files/{fid}", json={"label": "Renamed"})
    assert res.status_code == 200 and res.get_json()["label"] == "Renamed"
    assert client.delete(f"/api/todos/{tid}/files/{fid}").status_code == 200
    assert _files(storage, tid) == []
    assert client.delete(f"/api/todos/{tid}/files/{fid}").status_code == 404


def test_todo_file_rejects_bad_url_and_unknown_todo(client, storage) -> None:
    tid = _seed_todo(storage)
    assert client.post(f"/api/todos/{tid}/files", json={"url": "javascript:alert(1)"}).status_code == 400
    assert client.post("/api/todos/td_nope/files", json={"url": DROPBOX}).status_code == 404


def test_todo_file_cap(client, storage) -> None:
    tid = _seed_todo(storage)
    for i in range(MAX_FILES_PER_ROCK):
        assert client.post(f"/api/todos/{tid}/files", json={"url": f"https://x.com/{i}"}).status_code == 200
    assert client.post(f"/api/todos/{tid}/files", json={"url": "https://x.com/over"}).status_code == 400


def test_files_survive_todo_edit_and_toggle(client, storage) -> None:
    tid = _seed_todo(storage)
    client.post(f"/api/todos/{tid}/files", json={"url": DROPBOX})
    client.patch(f"/api/todos/{tid}", json={"task": "Edited", "owners": ["Chris Aiello"], "due": "2026-11-04"})
    client.post(f"/api/todos/{tid}/toggle")
    assert [f["url"] for f in _files(storage, tid)] == [DROPBOX]


def test_render_todo_file_chip_and_add_control(client, storage) -> None:
    tid = _seed_todo(storage)
    storage.add_todo_file(tid, DROPBOX, "<b>CMA</b> review")
    html = client.get("/").get_data(as_text=True)
    assert f'data-files-base="/api/todos/{tid}/files"' in html
    assert f'class="file-add-btn" data-todo-id="{tid}"' in html
    assert "&lt;b&gt;CMA&lt;/b&gt; review" in html          # label escaped
    assert f">{DROPBOX}<" not in html                       # raw URL never visible text
