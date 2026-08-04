"""One-time migration: lift URLs from rock text into per-rock ``files`` links.

Operates on the LIVE L10 ``rocks_doc`` JSON document (single-row JSONB the app
reads). Dry-run by DEFAULT: prints the exact before/after per rock and the file
links it would create, and changes NOTHING. Pass ``--apply`` to write.

Transform logic lives in ``app/rock_files_migration.py`` (unit-tested without a
DB). This script wires the live DB to it, snapshots first, and can roll back.

Usage
-----
Prefer running from the Render service shell so the DSN never leaves Render
(``$L10_DATABASE_URL`` is exposed there). Otherwise pass --dsn explicitly.

    # Dry-run (no writes) — the planned extraction:
    python scripts/migrate_rock_files.py --dsn "$L10_DATABASE_URL"

    # Apply (writes rocks_doc; snapshots the prior doc + a rollback manifest):
    python scripts/migrate_rock_files.py --dsn "$L10_DATABASE_URL" --apply

    # Roll back a specific run (restores text, removes the files it created):
    python scripts/migrate_rock_files.py --dsn "$L10_DATABASE_URL" --rollback 20260804T171233Z

A full JSON snapshot of the pre-migration ``rocks_doc`` is always written (even
on a dry-run) to ``--snapshot-dir``. ``--apply`` also writes a rollback manifest
``rock_files_run_<run-id>.json`` there; ``--rollback <run-id>`` reads it back.
``--apply`` aborts if the snapshot or manifest can't be written.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the work_portal backend importable (app.storage_pg, app.rock_files_*).
BACKEND_DIR = Path(__file__).resolve().parent.parent / "work_portal" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rock_files_migration import (  # noqa: E402
    apply_plan, build_plan, format_plan, rollback,
)


def _counts(data: dict) -> dict:
    from app.storage import iter_all_rocks
    rocks = list(iter_all_rocks(data))
    return {
        "rocks_total": len(rocks),
        "rocks_with_files": len([r for r in rocks if r.get("files")]),
        "file_links_total": sum(len(r.get("files") or []) for r in rocks),
    }


def _write_snapshot(snap_dir: Path, name: str, payload: dict, *, required: bool,
                    parser: argparse.ArgumentParser) -> Path | None:
    try:
        snap_dir.mkdir(parents=True, exist_ok=True)
        path = snap_dir / name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"  wrote     = {path}")
        return path
    except OSError as exc:
        if required:
            parser.error(f"cannot write {name} ({exc}); refusing to proceed")
        print(f"  wrote     = SKIPPED ({exc}) — dry-run, continuing")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", default=os.environ.get("L10_DATABASE_URL")
                        or os.environ.get("DATABASE_URL"),
                        help="Postgres DSN; defaults to $L10_DATABASE_URL or $DATABASE_URL")
    parser.add_argument("--snapshot-dir",
                        default=str(Path(__file__).resolve().parent / "snapshots"),
                        help="where to write the pre-migration snapshot + manifests")
    parser.add_argument("--apply", action="store_true",
                        help="actually write the new rocks_doc; without it, dry-run only")
    parser.add_argument("--rollback", metavar="RUN_ID", default=None,
                        help="undo a prior --apply run using its manifest")
    args = parser.parse_args()

    if not args.dsn:
        parser.error("no DSN: pass --dsn or set L10_DATABASE_URL / DATABASE_URL")

    from app.storage_pg import PostgresStorage  # local import: needs psycopg

    storage = PostgresStorage(dsn=args.dsn)
    snap_dir = Path(args.snapshot_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # ---- Rollback path --------------------------------------------------------
    if args.rollback:
        manifest_path = snap_dir / f"rock_files_run_{args.rollback}.json"
        if not manifest_path.exists():
            parser.error(f"no manifest for run {args.rollback} at {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        print(f"migrate_rock_files: mode=ROLLBACK run={args.rollback}")
        data = storage.load_rocks()
        _write_snapshot(snap_dir, f"rocks_doc_pre_rollback_{stamp}.json", data,
                        required=True, parser=parser)
        touched = rollback(data, manifest)
        storage.save_rocks(data)
        print(f"\n>> ROLLED BACK: restored {touched} rock(s) from run {args.rollback}.")
        return 0

    # ---- Dry-run / apply path -------------------------------------------------
    mode = "APPLY" if args.apply else "DRY-RUN (read-only)"
    print(f"migrate_rock_files: mode={mode}  run={stamp}")

    before = storage.load_rocks()
    _write_snapshot(snap_dir, f"rocks_doc_pre_files_{stamp}.json", before,
                    required=args.apply, parser=parser)

    print("\n--- BEFORE ---")
    print(json.dumps(_counts(before), indent=2))

    # Work on a deep copy so a dry-run never mutates what we'd re-save.
    working = json.loads(json.dumps(before))
    plan = build_plan(working)

    print("\n--- PLANNED CHANGES ---")
    print(format_plan(plan))

    if not args.apply:
        after = json.loads(json.dumps(before))
        apply_plan(after, build_plan(after), stamp)
        print("\n--- AFTER (projected) ---")
        print(json.dumps(_counts(after), indent=2))
        print("\n>> DRY-RUN only — nothing written. Re-run with --apply to commit.")
        return 0

    manifest = apply_plan(working, plan, stamp)
    _write_snapshot(snap_dir, f"rock_files_run_{stamp}.json", manifest,
                    required=True, parser=parser)
    storage.save_rocks(working)
    print("\n--- AFTER ---")
    print(json.dumps(_counts(working), indent=2))
    print(f"\n>> APPLIED: rocks_doc updated. Rollback with --rollback {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
