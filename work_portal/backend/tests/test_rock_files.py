"""Unit tests for the pure rock-files helpers (no DB, no Flask)."""
import pytest

from app.rock_files import (
    MAX_FILES_PER_ROCK,
    FileValidationError,
    apply_add_file,
    apply_remove_file,
    apply_update_file,
    build_file_entry,
    clean_label,
    derive_label,
    linkify,
    validate_url,
)

DROPBOX_FOLDER = "https://www.dropbox.com/scl/fo/4owj3md6qz8/PM?rlkey=msoa6djz5a3yu01nj5g8&dl=0"
DROPBOX_FILE = "https://www.dropbox.com/scl/fi/abc123/BidTab.xlsx?rlkey=zzz&dl=0"


# --- label derivation ---------------------------------------------------------

def test_derive_label_dropbox_folder() -> None:
    assert derive_label(DROPBOX_FOLDER) == "Dropbox folder"


def test_derive_label_dropbox_file_uses_filename() -> None:
    assert derive_label(DROPBOX_FILE) == "BidTab.xlsx"


def test_derive_label_generic_filename() -> None:
    assert derive_label("https://example.com/docs/report.pdf?x=1") == "report.pdf"


def test_derive_label_falls_back_to_host() -> None:
    assert derive_label("https://drive.google.com/") == "drive.google.com"
    assert derive_label("https://www.box.com/folder") == "box.com"


def test_derive_label_never_returns_raw_url() -> None:
    assert derive_label(DROPBOX_FOLDER) not in (DROPBOX_FOLDER,)


# --- url validation -----------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "data:text/html,<script>",
    "/relative/path",
    "ftp://host/file",
    "   ",
    "",
])
def test_validate_url_rejects(bad: str) -> None:
    with pytest.raises(FileValidationError):
        validate_url(bad)


def test_validate_url_preserves_query_verbatim() -> None:
    assert validate_url("  " + DROPBOX_FOLDER + "  ") == DROPBOX_FOLDER


def test_clean_label_caps_at_60() -> None:
    long = "x" * 200
    assert len(clean_label(long, DROPBOX_FOLDER)) == 60


def test_clean_label_blank_derives() -> None:
    assert clean_label("", DROPBOX_FOLDER) == "Dropbox folder"
    assert clean_label("   ", DROPBOX_FILE) == "BidTab.xlsx"


# --- entry construction -------------------------------------------------------

def test_build_file_entry_shape_and_verbatim_url() -> None:
    entry = build_file_entry(DROPBOX_FOLDER, "PM Proposals", "Chris Aiello",
                             id_factory=lambda: "fixedid")
    assert entry["id"] == "fixedid"
    assert entry["label"] == "PM Proposals"
    assert entry["url"] == DROPBOX_FOLDER          # byte-identical, rlkey+dl kept
    assert entry["added_by"] == "Chris Aiello"
    assert entry["added_at"].startswith("20") and "T" in entry["added_at"]


def test_build_file_entry_blank_added_by_is_none() -> None:
    assert build_file_entry(DROPBOX_FOLDER, "L")["added_by"] is None


# --- apply_* helpers ----------------------------------------------------------

def test_apply_add_file_round_trips() -> None:
    rock: dict = {"id": "r1"}
    entry = apply_add_file(rock, DROPBOX_FOLDER, "PM")
    assert rock["files"] == [entry]
    assert rock["files"][0]["url"] == DROPBOX_FOLDER


def test_eleventh_link_rejected() -> None:
    rock: dict = {"id": "r1", "files": []}
    for i in range(MAX_FILES_PER_ROCK):
        apply_add_file(rock, f"https://example.com/{i}", f"L{i}")
    assert len(rock["files"]) == MAX_FILES_PER_ROCK
    with pytest.raises(FileValidationError):
        apply_add_file(rock, "https://example.com/over", "too many")


def test_apply_update_file_relabels_and_reurls() -> None:
    rock: dict = {"id": "r1"}
    entry = apply_add_file(rock, "https://example.com/a", "A")
    updated = apply_update_file(rock, entry["id"], url="https://example.com/b", label="B")
    assert updated["url"] == "https://example.com/b"
    assert updated["label"] == "B"


def test_apply_update_file_blank_label_rederives() -> None:
    rock: dict = {"id": "r1"}
    entry = apply_add_file(rock, DROPBOX_FILE, "custom")
    apply_update_file(rock, entry["id"], label="")
    assert rock["files"][0]["label"] == "BidTab.xlsx"


def test_apply_update_file_missing_returns_none() -> None:
    assert apply_update_file({"id": "r1", "files": []}, "nope") is None


def test_apply_remove_file() -> None:
    rock: dict = {"id": "r1"}
    entry = apply_add_file(rock, DROPBOX_FOLDER, "PM")
    assert apply_remove_file(rock, entry["id"]) is True
    assert rock["files"] == []
    assert apply_remove_file(rock, entry["id"]) is False


# --- linkify (render-time safety net) -----------------------------------------

def test_linkify_wraps_and_truncates() -> None:
    from markupsafe import escape
    html = str(linkify(f"See {DROPBOX_FOLDER} now"))
    # href carries the full URL, attribute-escaped (& -> &amp;).
    assert 'href="' + str(escape(DROPBOX_FOLDER)) + '"' in html
    assert 'rel="noopener noreferrer"' in html
    assert 'target="_blank"' in html
    assert "…" in html                    # anchor text truncated
    # The full (long) URL is NOT the visible anchor text.
    assert f">{DROPBOX_FOLDER}<" not in html


def test_linkify_escapes_surrounding_text_and_script() -> None:
    html = str(linkify('<script>alert(1)</script> https://x.com/a'))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_linkify_short_url_shown_whole() -> None:
    html = str(linkify("https://x.co/a"))
    assert ">https://x.co/a<" in html


def test_linkify_empty() -> None:
    assert str(linkify("")) == ""
    assert str(linkify(None)) == ""
