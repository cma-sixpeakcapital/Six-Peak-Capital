"""Tests for the URL-out-of-text migration transform (pure, no DB)."""
from datetime import datetime, timezone
from itertools import count

from app.rock_files_migration import (
    apply_plan, build_plan, migrate_text, normalize_url, rollback,
)

RAMSGATE_URL = (
    "https://www.dropbox.com/scl/fo/4owj3md6qz8Ogkf6xyz/PM"
    "?rlkey=msoa6djz5a3yu01nj5g8Ocgkw&dl=0"
)

NOW = datetime(2026, 8, 4, 17, 0, tzinfo=timezone.utc)


def _ids():
    c = count(1)
    return lambda: f"file{next(c):02d}"


def _doc(notes: str, *, rock_id: str = "r1", owner: str = "Tom",
         title: str = "9033 Ramsgate PM Proposals", **extra) -> dict:
    rock = {"id": rock_id, "title": title, "notes": notes}
    rock.update(extra)
    return {"rocks": {owner: [rock]}, "company_rocks": [], "todos": [], "team": []}


# --- migrate_text -------------------------------------------------------------

def test_ramsgate_single_line_url() -> None:
    notes = f"Finalize all proposals and present recommendation to LP\nFINAL MATERIALS:\n{RAMSGATE_URL}"
    cleaned, urls = migrate_text(notes)
    assert urls == [(RAMSGATE_URL, "FINAL MATERIALS")]
    assert RAMSGATE_URL not in cleaned
    assert "FINAL MATERIALS" not in cleaned            # orphaned heading dropped
    assert cleaned == "Finalize all proposals and present recommendation to LP"


def test_ramsgate_soft_wrapped_url_is_stitched() -> None:
    # URL hard-wrapped across lines (as pasted from a soft-wrapping editor).
    notes = (
        "FINAL MATERIALS:\n"
        "https://www.dropbox.com/scl/fo/4owj3md6qz8Ogkf6xyz/PM/\n"
        "?rlkey=msoa6djz5a3yu01nj5g8Ocgkw&dl=0"
    )
    cleaned, urls = migrate_text(notes)
    assert len(urls) == 1
    url, label = urls[0]
    assert label == "FINAL MATERIALS"
    assert url.endswith("rlkey=msoa6djz5a3yu01nj5g8Ocgkw&dl=0")   # tail rejoined
    assert "\n" not in url
    assert cleaned == ""


def test_inline_label_clause_extracted_and_prose_kept() -> None:
    # The real live shape: "sentence. INLINE LABEL:  <url>" on one line.
    notes = (
        "Finalize all proposals and present recommendation to Kinfolk.  "
        "HERE IS THE LINK TO THE FINAL MATERIALS:  " + RAMSGATE_URL
    )
    cleaned, urls = migrate_text(notes)
    assert urls == [(RAMSGATE_URL, "HERE IS THE LINK TO THE FINAL MATERIALS")]
    assert cleaned == "Finalize all proposals and present recommendation to Kinfolk."
    assert "FINAL MATERIALS" not in cleaned      # dangling clause dropped
    assert RAMSGATE_URL not in cleaned


def test_no_url_returns_text_unchanged() -> None:
    text = "Just prose, no links here."
    assert migrate_text(text) == (text, [])


def test_inline_url_keeps_surrounding_prose() -> None:
    cleaned, urls = migrate_text("Ping the board at https://x.com/a before Friday.")
    assert urls == [("https://x.com/a", None)]
    assert "https://x.com/a" not in cleaned
    assert "Ping the board at" in cleaned and "before Friday." in cleaned


# --- build_plan / apply / idempotency / rollback ------------------------------

def test_build_plan_ramsgate_one_entry() -> None:
    data = _doc(f"FINAL MATERIALS:\n{RAMSGATE_URL}")
    plan = build_plan(data, now=NOW, id_factory=_ids())
    assert len(plan) == 1
    change = plan[0]
    assert len(change["new_files"]) == 1
    f = change["new_files"][0]
    assert f["label"] == "FINAL MATERIALS"
    assert f["url"] == RAMSGATE_URL                 # byte-identical
    assert f["added_by"] == "Tom"
    # build_plan must not mutate the source doc
    assert data["rocks"]["Tom"][0]["notes"] == f"FINAL MATERIALS:\n{RAMSGATE_URL}"


def test_apply_then_idempotent() -> None:
    data = _doc(f"FINAL MATERIALS:\n{RAMSGATE_URL}")
    plan = build_plan(data, now=NOW, id_factory=_ids())
    apply_plan(data, plan, "run1")
    rock = data["rocks"]["Tom"][0]
    assert RAMSGATE_URL not in rock["notes"]
    assert len(rock["files"]) == 1
    # Second pass finds nothing to do.
    assert build_plan(data, now=NOW, id_factory=_ids()) == []


def test_rollback_restores_text_exactly() -> None:
    original = f"Finalize proposals\nFINAL MATERIALS:\n{RAMSGATE_URL}"
    data = _doc(original)
    plan = build_plan(data, now=NOW, id_factory=_ids())
    manifest = apply_plan(data, plan, "run1")
    assert data["rocks"]["Tom"][0]["notes"] != original
    rollback(data, manifest)
    rock = data["rocks"]["Tom"][0]
    assert rock["notes"] == original                # restored byte-for-byte
    assert rock.get("files") == []                  # created entry removed


def test_dedup_same_url_twice() -> None:
    data = _doc(f"See {RAMSGATE_URL} and again {RAMSGATE_URL}")
    plan = build_plan(data, now=NOW, id_factory=_ids())
    assert len(plan[0]["new_files"]) == 1


def test_dedup_against_existing_files() -> None:
    data = _doc(
        f"FINAL MATERIALS:\n{RAMSGATE_URL}",
        files=[{"id": "old", "label": "PM", "url": RAMSGATE_URL,
                "added_by": None, "added_at": "2026-01-01T00:00:00+00:00"}],
    )
    plan = build_plan(data, now=NOW, id_factory=_ids())
    # URL already attached → no new file, but the text is still cleaned.
    assert plan[0]["new_files"] == []
    assert "notes" in plan[0]["fields"]


# --- legacy link field --------------------------------------------------------

def test_legacy_url_link_migrated_and_cleared() -> None:
    data = _doc("Plain notes.", link="https://docs.google.com/document/d/abc/edit?usp=sharing")
    plan = build_plan(data, now=NOW, id_factory=_ids())
    change = plan[0]
    assert change["fields"]["link"]["after"] == ""
    assert any("google.com" in f["url"] for f in change["new_files"])


def test_non_url_link_left_untouched() -> None:
    data = _doc("Plain notes.", link="Initial email sent 2/5, follow up on 2/23")
    plan = build_plan(data, now=NOW, id_factory=_ids())
    assert plan == []                                # nothing to migrate


# --- normalize_url ------------------------------------------------------------

def test_normalize_url_keeps_query_distinct() -> None:
    a = "https://www.dropbox.com/scl/fo/x/PM?rlkey=AAA&dl=0"
    b = "https://www.dropbox.com/scl/fo/x/PM?rlkey=BBB&dl=0"
    assert normalize_url(a) != normalize_url(b)      # different rlkey ≠ dup
    # Trailing slash on the PATH is ignored; the query is kept verbatim.
    assert normalize_url("https://x.com/a/") == normalize_url("https://x.com/a")
