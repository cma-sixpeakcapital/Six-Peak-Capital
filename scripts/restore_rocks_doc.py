"""Restore the L10 rocks / to-dos document to how it was at a point in time.

Every save of the rocks document keeps the version it replaced (table
``rocks_doc_history``; see app/storage_pg.py). This script finds the version that
was current at ``--at`` and, with ``--apply``, writes it back. The write is a
normal save, so the version being replaced is itself kept: a restore can be
undone the same way.

Dry-run by default: prints what would change and writes nothing.

Usage (Render shell, ~/project/src, where $L10_DATABASE_URL is set):

    python scripts/restore_rocks_doc.py --list                 # recent versions
    python scripts/restore_rocks_doc.py --at "2026-09-29T10:15" # preview (ET unless offset given)
    python scripts/restore_rocks_doc.py --at "2026-09-29T10:15" --apply
    python scripts/restore_rocks_doc.py --id 42 --apply          # a specific saved version
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_DIR = Path(__file__).resolve().parent.parent / "work_portal" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import make_storage  # noqa: E402
from app.audit import diff_items, index_doc  # noqa: E402
from app.config import Config  # noqa: E402

ET = ZoneInfo("America/New_York")


def parse_at(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(timezone.utc)


def version_at(storage, at: datetime) -> dict | None:
    """The document that was current at `at` = the first history row saved
    (i.e. replaced) after `at`. None means the current document already is it."""
    for row in storage.list_rocks_history(limit=None, ascending=True):
        if datetime.fromisoformat(row["saved_at"]) > at:
            return storage.get_rocks_history(row["id"])
    return None


def main(argv: list[str] | None = None, storage=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--at", help="ISO time; ET if no offset (e.g. 2026-09-29T10:15)")
    g.add_argument("--id", help="rocks_doc_history id to restore")
    g.add_argument("--list", action="store_true", help="list recent saved versions")
    ap.add_argument("--apply", action="store_true", help="write the restore (default: preview only)")
    args = ap.parse_args(argv)

    storage = storage or make_storage(Config.from_env("L10_"))  # "L10_" prefix is required

    if args.list:
        for row in storage.list_rocks_history(limit=40):
            print(f"#{row['id']:>6}  replaced at {row['saved_at']}")
        return 0

    if args.id:
        version = storage.get_rocks_history(args.id)
        if version is None:
            print(f"no saved version #{args.id}")
            return 1
    else:
        version = version_at(storage, parse_at(args.at))
        if version is None:
            print("The current document was already in place at that time; nothing to restore.")
            return 0

    current = storage.load_rocks()
    changes = diff_items(index_doc(current), index_doc(version["data"]))
    print(f"Restore target: version #{version['id']} (replaced at {version['saved_at']})")
    print(f"{len(changes)} item(s) would change:")
    for c in changes:
        extra = f" fields={c.get('fields')}" if c["op"] == "changed" else ""
        print(f"  {c['op']:>7}  {c['type']:<12} {c['title'][:70]}{extra}")
    if not args.apply:
        print("\nPreview only. Re-run with --apply to restore.")
        return 0
    storage.save_rocks(version["data"])
    print("\nRestored. The document it replaced was saved to history, so this can be undone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
