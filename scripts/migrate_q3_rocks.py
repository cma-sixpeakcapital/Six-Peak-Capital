"""One-time Q3 2026 rock rollover for l10.sixpeakapps.com (rocks_doc table).

Operates on the LIVE L10 ``rocks_doc`` JSON document. Dry-run by default:
prints the exact planned writes and the before/after counts and changes
NOTHING. Pass ``--apply`` to write the new document back (one upsert, the same
single-row JSONB doc the app reads).

The transform logic lives in ``app/q3_migration.py`` (unit-tested without a DB).
This script just wires the live DB to it and prints a reviewable plan.

Usage
-----
Prefer running from the Render service shell so the DSN never leaves Render
(``$L10_DATABASE_URL`` is exposed there). Otherwise pass --dsn explicitly.

    # Dry-run (no writes) — the planned rollover:
    python scripts/migrate_q3_rocks.py --dsn "$L10_DATABASE_URL"

    # Apply (writes the new rocks_doc; snapshots the prior doc first):
    python scripts/migrate_q3_rocks.py --dsn "$L10_DATABASE_URL" --apply

A JSON snapshot of the pre-migration ``rocks_doc`` is always written (even on a
dry-run) to ``--snapshot-dir`` so the change is reversible. ``--apply`` aborts
if the snapshot can't be written.

Rollback: re-load the snapshot file into rocks_doc, or remove the
``quarter="Q3 2026"`` inserts and clear the ``quarter="Q2 2026"`` archive flags.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the work_portal backend importable (app.storage_pg, app.q3_migration).
BACKEND_DIR = Path(__file__).resolve().parent.parent / "work_portal" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.q3_migration import (  # noqa: E402
    Q3_DATA_PATH, Q3_MIGRATION_PATH, apply_migration, format_plan, load_json,
)


def _counts(data: dict) -> dict:
    cr = data.get("company_rocks", []) or []
    indiv = data.get("rocks", {}) or {}
    all_indiv = [r for rocks in indiv.values() for r in rocks]
    return {
        "company_total": len(cr),
        "company_active": len([r for r in cr if not r.get("archived")]),
        "individual_total": len(all_indiv),
        "individual_active": len([r for r in all_indiv if not r.get("archived")]),
        "archived_not_converted": len(
            [r for r in (cr + all_indiv) if r.get("archived") and not r.get("converted")]
        ),
        "converted": len([r for r in (cr + all_indiv) if r.get("converted")]),
        "todos": len(data.get("todos", []) or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", default=os.environ.get("L10_DATABASE_URL")
                        or os.environ.get("DATABASE_URL"),
                        help="Postgres DSN; defaults to $L10_DATABASE_URL or $DATABASE_URL")
    parser.add_argument("--data", default=str(Q3_DATA_PATH), help="Q3_rocks_data.json")
    parser.add_argument("--migration", default=str(Q3_MIGRATION_PATH),
                        help="Q3_rocks_migration.json")
    parser.add_argument("--snapshot-dir", default=str(Path(__file__).resolve().parent / "snapshots"),
                        help="where to write the pre-migration rocks_doc snapshot")
    parser.add_argument("--apply", action="store_true",
                        help="actually write the new rocks_doc; without it, dry-run only")
    args = parser.parse_args()

    if not args.dsn:
        parser.error("no DSN: pass --dsn or set L10_DATABASE_URL / DATABASE_URL")

    from app.storage_pg import PostgresStorage  # local import: needs psycopg

    mode = "APPLY" if args.apply else "DRY-RUN (read-only)"
    print(f"migrate_q3_rocks: mode={mode}")
    print(f"  data      = {args.data}")
    print(f"  migration = {args.migration}")

    q3 = load_json(args.data)
    mig = load_json(args.migration)

    storage = PostgresStorage(dsn=args.dsn)
    before = storage.load_rocks()

    # Snapshot the pre-migration doc (always — our rollback artifact).
    snap_dir = Path(args.snapshot_dir)
    try:
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap_path = snap_dir / f"rocks_doc_pre_q3_{stamp}.json"
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(before, f, indent=2, ensure_ascii=False)
        print(f"  snapshot  = {snap_path}")
    except OSError as exc:
        if args.apply:
            parser.error(f"cannot write snapshot ({exc}); refusing to --apply")
        print(f"  snapshot  = SKIPPED ({exc}) — dry-run, continuing")

    print("\n--- BEFORE ---")
    print(json.dumps(_counts(before), indent=2))

    # Work on a deep copy so a dry-run never mutates what we'd re-save.
    working = json.loads(json.dumps(before))
    after, plan = apply_migration(working, q3, mig)

    print("\n--- PLANNED WRITES ---")
    print(format_plan(plan))

    print("\n--- AFTER (projected) ---")
    print(json.dumps(_counts(after), indent=2))

    if not args.apply:
        print("\n>> DRY-RUN only — nothing written. Re-run with --apply to commit.")
        return 0

    storage.save_rocks(after)
    print("\n>> APPLIED: rocks_doc updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
