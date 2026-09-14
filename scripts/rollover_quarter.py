"""Quarter rollover for l10.sixpeakapps.com (rocks_doc table) — generic.

Operates on the LIVE L10 ``rocks_doc`` JSON document. Dry-run by default:
prints the exact planned writes and the before/after scoreboard and changes
NOTHING. Pass ``--apply`` to write the new document back (one upsert).

The transform lives in ``work_portal/backend/app/quarter_rollover.py`` (unit
tested without a DB). Inputs are the per-quarter JSON pair under
``work_portal/backend/data/<tag>/`` — e.g. ``q4_2026/Q4_rocks_data.json`` +
``Q4_rocks_migration.json``.

Usage (from the Render service shell, where $L10_DATABASE_URL is set):

    # Dry-run — prints the plan, writes a snapshot, changes nothing:
    python scripts/rollover_quarter.py --from "Q3 2026" --to "Q4 2026"

    # Apply:
    python scripts/rollover_quarter.py --from "Q3 2026" --to "Q4 2026" --apply

A JSON snapshot of the pre-migration ``rocks_doc`` is always written to
``--snapshot-dir`` (default ``scripts/snapshots/``) so the change is reversible:

    python scripts/rollover_quarter.py --restore scripts/snapshots/rocks_doc_pre_q4_2026_<stamp>.json --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "work_portal" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.quarter_rollover import apply_rollover, format_plan, load_json  # noqa: E402
from app.scoring import score_quarter  # noqa: E402


def _tag(q: str) -> str:
    """'Q4 2026' -> 'q4_2026'"""
    parts = q.split()
    return f"{parts[0].lower()}_{parts[1]}" if len(parts) == 2 else q.lower().replace(" ", "_")


def _counts(data: dict) -> dict:
    cr = data.get("company_rocks", []) or []
    indiv = [r for rocks in (data.get("rocks", {}) or {}).values() for r in rocks]
    allr = cr + indiv
    return {
        "company_total": len(cr), "company_active": len([r for r in cr if not r.get("archived")]),
        "individual_total": len(indiv),
        "individual_active": len([r for r in indiv if not r.get("archived")]),
        "archived": len([r for r in allr if r.get("archived")]),
        "with_result": len([r for r in allr if r.get("result")]),
        "todos": len(data.get("todos", []) or []),
        "todos_open": len([t for t in (data.get("todos") or []) if not t.get("completed")]),
        "quarters": [q.get("id") for q in (data.get("quarters") or [])],
    }


def _score_line(data: dict, q: str) -> str:
    s = score_quarter(data, q)
    if not s["total"]:
        return f"  {q}: no rocks"
    people = ", ".join(f"{o['owner'].split()[0]} {o['complete']}/{o['owned']}" for o in s["owners"])
    return f"  {q}: {s['complete']}/{s['total']} ({s['pct']}%) · company {s['company_complete']}/{s['company_total']} · {people}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", default=os.environ.get("L10_DATABASE_URL") or os.environ.get("DATABASE_URL"),
                        help="Postgres DSN; defaults to $L10_DATABASE_URL or $DATABASE_URL")
    parser.add_argument("--from", dest="from_q", help='outgoing quarter, e.g. "Q3 2026"')
    parser.add_argument("--to", dest="to_q", help='incoming quarter, e.g. "Q4 2026"')
    parser.add_argument("--data", help="override <to>_rocks_data.json path")
    parser.add_argument("--migration", help="override <to>_rocks_migration.json path")
    parser.add_argument("--snapshot-dir", default=str(Path(__file__).resolve().parent / "snapshots"))
    parser.add_argument("--restore", help="restore rocks_doc from this snapshot file instead of rolling over")
    parser.add_argument("--apply", action="store_true", help="write the result; without it, dry-run only")
    args = parser.parse_args()

    if not args.dsn:
        parser.error("no DSN: pass --dsn or set L10_DATABASE_URL / DATABASE_URL")

    from app.storage_pg import PostgresStorage  # needs psycopg
    storage = PostgresStorage(dsn=args.dsn)
    mode = "APPLY" if args.apply else "DRY-RUN (read-only)"

    if args.restore:
        doc = load_json(args.restore)
        print(f"rollover_quarter: RESTORE from {args.restore}  mode={mode}")
        print(json.dumps(_counts(doc), indent=2))
        if args.apply:
            storage.save_rocks(doc)
            print(">> RESTORED rocks_doc from snapshot.")
        else:
            print(">> DRY-RUN — nothing written.")
        return 0

    if not (args.from_q and args.to_q):
        parser.error("--from and --to are required (or --restore)")
    tag = _tag(args.to_q)
    data_path = args.data or BACKEND_DIR / "data" / tag / f"{args.to_q.split()[0]}_rocks_data.json"
    mig_path = args.migration or BACKEND_DIR / "data" / tag / f"{args.to_q.split()[0]}_rocks_migration.json"
    print(f"rollover_quarter: {args.from_q} -> {args.to_q}  mode={mode}")
    print(f"  data      = {data_path}\n  migration = {mig_path}")

    new = load_json(data_path)
    mig = load_json(mig_path)
    if mig.get("from_quarter") != args.from_q or mig.get("to_quarter") != args.to_q:
        parser.error(f"migration file is {mig.get('from_quarter')} -> {mig.get('to_quarter')}, "
                     f"not {args.from_q} -> {args.to_q}")

    before = storage.load_rocks()
    snap_dir = Path(args.snapshot_dir)
    try:
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap = snap_dir / f"rocks_doc_pre_{tag}_{stamp}.json"
        snap.write_text(json.dumps(before, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  snapshot  = {snap}")
    except OSError as exc:
        if args.apply:
            parser.error(f"cannot write snapshot ({exc}); refusing to --apply")
        print(f"  snapshot  = SKIPPED ({exc}) — dry-run, continuing")

    print("\n--- BEFORE ---")
    print(json.dumps(_counts(before), indent=2))
    print(_score_line(before, args.from_q))

    working = json.loads(json.dumps(before))
    after, plan = apply_rollover(working, mig, new)

    print("\n--- PLANNED WRITES ---")
    print(format_plan(plan))
    print("\n--- AFTER (projected) ---")
    print(json.dumps(_counts(after), indent=2))
    print(_score_line(after, args.from_q))
    print(_score_line(after, args.to_q))
    official = next((q.get("official_score") for q in after.get("quarters", []) if q.get("id") == args.from_q), None)
    if official:
        print(f"  official {args.from_q} score on record: {official.get('complete')}/{official.get('total')} ({official.get('source', '')})")

    problems = plan["closeout_missing"] or plan["closeout_invalid"] or plan["successor_missing"] or plan["fixup_missing"]
    if problems:
        print("\n!! PLAN HAS MISSING/INVALID ITEMS — review above before applying.")
    if not args.apply:
        print("\n>> DRY-RUN only — nothing written. Re-run with --apply to commit.")
        return 0
    if problems:
        print(">> refusing to --apply with missing/invalid items. Fix the migration JSON first.")
        return 2
    storage.save_rocks(after)
    print("\n>> APPLIED: rocks_doc updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
