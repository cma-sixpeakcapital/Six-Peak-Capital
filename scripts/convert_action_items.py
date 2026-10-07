"""One-time: turn the action items still sitting on the latest L10 meeting into
to-dos (Chris, 10/7/2026). New meetings do this automatically at ingest.

Dry-run by default (prints what would be created, changes nothing).
Run from the Render service shell, where $L10_DATABASE_URL is set:

    python scripts/convert_action_items.py            # dry-run
    python scripts/convert_action_items.py --apply    # write

A snapshot of the rocks document (which holds the to-dos) is written to
scripts/snapshots/ before any write. Re-running is safe: items already
linked to a to-do are skipped.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "work_portal" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import make_storage  # noqa: E402
from app.config import Config  # noqa: E402
from app import todos as todo_lib  # noqa: E402
from app.storage import _roster  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--meeting-id", help="default: the latest meeting")
    ap.add_argument("--snapshot-dir", default=str(Path(__file__).parent / "snapshots"))
    args = ap.parse_args()

    st = make_storage(Config.from_env("L10_"))
    print("storage:", type(st).__name__)
    meeting = st.get_meeting(args.meeting_id) if args.meeting_id else st.latest_meeting()
    if not meeting:
        print("no meeting found")
        return 1
    print(f"meeting: {meeting.get('id')} · {meeting.get('date')} · {meeting.get('title')}")
    print(f"action items on it: {len(meeting.get('action_items') or [])}")

    # Plan on copies so the dry-run touches nothing.
    data = st.load_rocks()
    plan = todo_lib.todos_from_action_items(copy.deepcopy(meeting), copy.deepcopy(data), _roster())
    for t in plan:
        print(f"  + {', '.join(t.get('owners') or []) or 'Unassigned'} | due {t['due']} | {t['task']}")
    print(f"{len(plan)} to-do(s) would be created")
    if not args.apply or not plan:
        print("dry-run only" if not args.apply else "nothing to do")
        return 0

    snap_dir = Path(args.snapshot_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = snap_dir / f"rocks_doc_pre_action_items_{stamp}.json"
    snap.write_text(json.dumps(data, indent=1, default=str))
    print("snapshot:", snap)

    created = st.convert_action_items(meeting)
    st.save_meeting(meeting)
    print(f"created {len(created)} to-do(s): {[t['id'] for t in created]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
