"""Recover in-window meetings that were *only* consumed by a dry-run/test.

Background
----------
Before the claim-ordering fix (see app/jobs/send_followups.py and
send_reminders.py), a dry-run or manual test called ``claim_followup`` /
``claim_reminder`` BEFORE the ``if dry_run:`` branch, permanently stamping
``followup_sent_at`` / ``reminder_sent_at`` and consuming the meeting — so it
could never send a real email afterward. This script clears that stamp for the
in-window rows that were only ever touched by a dry run, so the next hourly
cron can send them for real.

Safety
------
- READ-ONLY by default: prints the exact rows that WOULD change and exits.
  Pass ``--apply`` to actually run the UPDATE (inside one transaction).
- NEVER resets a row whose log shows ``dry_run: false`` — that recap/reminder
  already went out to real attendees. Only rows with NO log or an explicit
  ``dry_run: true`` log are eligible.
- Scoped to the recap window (saved_at 24h-7d ago) for follow-ups and to each
  portal's reminder window for reminders. Out-of-window rows are never touched.

Usage
-----
Prefer running this from the Render service shell so the DSN never leaves
Render. Otherwise pass the portal's ``*_DATABASE_URL`` explicitly.

    # Preview (no writes) — what a recovery WOULD reset:
    python scripts/reset_followup_claims.py --portal l10 --dsn "$L10_DATABASE_URL"

    # Apply, follow-ups only:
    python scripts/reset_followup_claims.py --portal finance --dsn "$FINANCE_DATABASE_URL" --kind followup --apply

    # Apply both follow-up and reminder recovery:
    python scripts/reset_followup_claims.py --portal lvexec --dsn "$LVEXEC_DATABASE_URL" --apply

``--dsn`` defaults to the ``DATABASE_URL`` env var if present (which is what the
Render service shell exposes for the service's own database).

Reminder windows (days since meeting date): l10 3-10, lvexec 7-14, finance
14-21. IC has no reminder job, so ``--kind reminder`` is rejected for ic.
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg

# Per-portal table name + reminder window. The recap (follow-up) window is the
# same for every portal (saved_at 24h-7d ago); only the reminder window varies.
PORTALS: dict[str, dict] = {
    "l10":     {"table": "meetings",         "reminder": (3, 10)},
    "lvexec":  {"table": "lv_meetings",      "reminder": (7, 14)},
    "finance": {"table": "finance_meetings", "reminder": (14, 21)},
    "ic":      {"table": "ic_meetings",      "reminder": None},  # no reminder job
}


def _eligible_followup_where() -> str:
    # In the recap window AND only ever touched by a dry run (no real send).
    return (
        "followup_sent_at IS NOT NULL\n"
        "       AND (now() - (data->>'saved_at')::timestamptz) "
        "BETWEEN interval '24 hours' AND interval '7 days'\n"
        "       AND (followup_log IS NULL OR (followup_log->>'dry_run')::boolean IS TRUE)"
    )


def _eligible_reminder_where(min_days: int, max_days: int) -> str:
    return (
        "reminder_sent_at IS NOT NULL\n"
        f"       AND (current_date - (data->>'date')::date) BETWEEN {min_days} AND {max_days}\n"
        "       AND (reminder_log IS NULL OR (reminder_log->>'dry_run')::boolean IS TRUE)"
    )


def _preview(cur, table: str, kind: str, where: str) -> list[tuple]:
    sent_col = "followup_sent_at" if kind == "followup" else "reminder_sent_at"
    log_col = "followup_log" if kind == "followup" else "reminder_log"
    cur.execute(
        f"""
        SELECT id,
               data->>'date'      AS date,
               data->>'saved_at'  AS saved_at,
               {sent_col}         AS sent_at,
               ({log_col} IS NULL) AS log_is_null,
               {log_col}->>'dry_run' AS log_dry_run,
               {log_col}->'recipients' AS log_recipients
          FROM {table}
         WHERE {where}
         ORDER BY date
        """
    )
    return cur.fetchall()


def _run_kind(cur, table: str, kind: str, where: str, apply: bool) -> int:
    rows = _preview(cur, table, kind, where)
    print(f"\n=== {kind.upper()} recovery on {table} — {len(rows)} eligible row(s) ===")
    if not rows:
        print("  (nothing in window was consumed by a dry run only)")
        return 0
    for r in rows:
        mid, mdate, saved_at, sent_at, log_null, dry, recips = r
        log_state = "no log" if log_null else f"dry_run={dry}"
        print(f"  - id={mid}  date={mdate}  saved_at={saved_at}")
        print(f"      {kind}_sent_at={sent_at}  log: {log_state}  recipients={recips}")
    if not apply:
        print("  >> preview only — re-run with --apply to clear these claims.")
        return 0
    sent_col = "followup_sent_at" if kind == "followup" else "reminder_sent_at"
    log_col = "followup_log" if kind == "followup" else "reminder_log"
    cur.execute(
        f"UPDATE {table} SET {sent_col} = NULL, {log_col} = NULL WHERE {where}"
    )
    print(f"  >> APPLIED: cleared {cur.rowcount} {kind} claim(s).")
    return cur.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--portal", required=True, choices=sorted(PORTALS),
                        help="which portal's DB (selects table + reminder window)")
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"),
                        help="Postgres DSN; defaults to $DATABASE_URL")
    parser.add_argument("--kind", choices=["followup", "reminder", "both"], default="both",
                        help="which claim(s) to recover (default: both)")
    parser.add_argument("--apply", action="store_true",
                        help="actually run the UPDATE; without it, preview only")
    args = parser.parse_args()

    if not args.dsn:
        parser.error("no DSN: pass --dsn or set DATABASE_URL")

    portal = PORTALS[args.portal]
    table = portal["table"]
    reminder_window = portal["reminder"]

    do_followup = args.kind in ("followup", "both")
    do_reminder = args.kind in ("reminder", "both")
    if do_reminder and reminder_window is None:
        if args.kind == "reminder":
            parser.error(f"portal '{args.portal}' has no reminder job")
        do_reminder = False  # 'both' on ic → just follow-ups

    mode = "APPLY" if args.apply else "PREVIEW (read-only)"
    print(f"reset_followup_claims: portal={args.portal} table={table} mode={mode}")

    total = 0
    # One transaction: psycopg autocommits off by default, so a preview run
    # makes no writes and an --apply run commits atomically at the end.
    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            if do_followup:
                total += _run_kind(cur, table, "followup", _eligible_followup_where(), args.apply)
            if do_reminder:
                lo, hi = reminder_window
                total += _run_kind(cur, table, "reminder", _eligible_reminder_where(lo, hi), args.apply)
        if args.apply:
            conn.commit()
            print(f"\nCommitted. Total claims cleared: {total}.")
        else:
            conn.rollback()
            print("\nNo changes made (preview). Re-run with --apply to clear the claims above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
