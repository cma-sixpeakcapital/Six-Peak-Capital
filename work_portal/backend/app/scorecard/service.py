"""When the portal reads the Sheet, and which data the Scorecard shows.

- Normal days: the page reuses the latest snapshot for up to 10 minutes, then
  pulls the Sheet again (an "on_view" snapshot). If the Sheet is unreachable the
  last good snapshot is shown with its "data as of" stamp; never a blank card.
- Tuesday from 8:00 a.m. ET (the L10): the page shows the frozen "meeting"
  snapshot, or a later "manual" refresh if someone pressed Refresh. Edits made to
  the Sheet after 8:00 do not change what the meeting sees.
- The freeze itself is taken by POST /api/jobs/ingest_scorecard?kind=meeting,
  called by the hourly GitHub Action. It acts only on Tuesday at/after 8:00 ET
  and only once, so DST and late cron runs don't matter.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .parse import parse_sheet
from .ryg import build_view
from .sheet import SheetFetchError

ET = ZoneInfo("America/New_York")
MEETING_WEEKDAY = 1  # Tuesday
MEETING_FREEZE_HOUR = 8


def meeting_window_start(now_et: datetime) -> datetime | None:
    """Start of today's freeze window (Tuesday 08:00 ET) if we're inside it."""
    if now_et.weekday() == MEETING_WEEKDAY and now_et.hour >= MEETING_FREEZE_HOUR:
        return now_et.replace(hour=MEETING_FREEZE_HOUR, minute=0, second=0, microsecond=0)
    return None


class ScorecardService:
    def __init__(self, storage: Any, fetcher: Callable[[], dict[str, str]] | None,
                 start_week: date, cache_minutes: int = 10,
                 now_fn: Callable[[], datetime] | None = None) -> None:
        self.storage = storage
        self.fetcher = fetcher
        self.start_week = start_week
        self.cache = timedelta(minutes=cache_minutes)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        return self._now_fn()

    # -- writes -------------------------------------------------------------
    def fetch_and_save(self, kind: str, refreshed_by: str = "") -> dict[str, Any]:
        if self.fetcher is None:
            raise SheetFetchError("Sheet link not configured")
        csvs = self.fetcher()
        now = self.now()
        payload = {"csv": csvs, "fetched_at": now.isoformat()}
        return self.storage.save_scorecard_snapshot(kind, payload, refreshed_by, taken_at=now)

    def refresh(self, actor: str = "") -> dict[str, Any]:
        snap = self.fetch_and_save("manual", actor)
        return self._meta(snap)

    def freeze(self, force: bool = False) -> dict[str, Any]:
        now = self.now()
        now_et = now.astimezone(ET)
        ws = meeting_window_start(now_et)
        if not force:
            if ws is None:
                return {"status": "skipped", "reason": "outside the Tuesday 8:00 a.m. ET window",
                        "now_et": now_et.isoformat()}
            existing = self.storage.latest_scorecard_snapshot(
                kinds=("meeting",), since=ws.astimezone(timezone.utc))
            if existing is not None:
                return {"status": "skipped", "reason": "already frozen",
                        "snapshot": self._meta(existing)}
        snap = self.fetch_and_save("meeting", "scheduled freeze" if not force else "forced freeze")
        return {"status": "frozen", "snapshot": self._meta(snap)}

    # -- reads --------------------------------------------------------------
    def current(self) -> dict[str, Any]:
        now = self.now()
        now_et = now.astimezone(ET)
        frozen = False
        fetch_error = None
        snap = None
        ws = meeting_window_start(now_et)
        if ws is not None:
            snap = self.storage.latest_scorecard_snapshot(
                kinds=("meeting", "manual"), since=ws.astimezone(timezone.utc))
            frozen = snap is not None
        if snap is None:
            snap = self.storage.latest_scorecard_snapshot()
            if self.fetcher is not None and (snap is None or now - snap["taken_at"] > self.cache):
                try:
                    snap = self.fetch_and_save("on_view")
                except SheetFetchError as exc:
                    fetch_error = str(exc)
                except Exception as exc:  # never let the Sheet break the page
                    fetch_error = f"{type(exc).__name__}: {exc}"
        if snap is None:
            return {"available": False,
                    "fetch_error": fetch_error or "Sheet link not configured",
                    "start_week": self.start_week}
        model = parse_sheet(snap["payload"].get("csv") or {})
        view = build_view(model, now_et.date(), self.start_week)
        return {"available": True, "view": view, "snapshot": self._meta(snap),
                "frozen": frozen, "fetch_error": fetch_error}

    @staticmethod
    def _meta(snap: dict[str, Any]) -> dict[str, Any]:
        taken = snap["taken_at"]
        taken_et = taken.astimezone(ET)
        return {"id": snap.get("id"), "kind": snap["kind"], "refreshed_by": snap.get("refreshed_by") or "",
                "taken_at": taken.isoformat(),
                "taken_at_display": taken_et.strftime("%a %b ") + str(taken_et.day)
                + taken_et.strftime(", %I:%M %p ET").replace(" 0", " ")}
