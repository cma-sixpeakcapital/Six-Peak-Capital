"""Weekly Scorecard: parsing, validation, Red/Yellow/Green, glidepaths, the
meeting freeze, and the page/API wiring."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import create_app
from app.scorecard.parse import monday_of, parse_date, parse_number, parse_sheet
from app.scorecard.ryg import GREEN, GREY, RED, YELLOW, build_view, color_for, resolve_target
from app.scorecard.service import ET, ScorecardService
from app.scorecard.sheet import SheetFetchError, make_fetcher, parse_gids
from app.storage import Storage

FIX = Path(__file__).parent / "fixtures" / "scorecard"
START = date(2026, 9, 28)


def load_csvs(actuals_rows: list[str] | None = None) -> dict[str, str]:
    csvs = {t: (FIX / f"{t}.csv").read_text() for t in ("metrics", "actuals", "targets", "people")}
    if actuals_rows:
        csvs["actuals"] = csvs["actuals"].rstrip("\n") + "\n" + "\n".join(actuals_rows) + "\n"
    return csvs


def et(y, mo, d, h=12, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


# ---------------------------------------------------------------- colors ----
@pytest.mark.parametrize("direction,value,target,yellow,expected", [
    ("higher_better", 3.0, 3, 2.5, GREEN),
    ("higher_better", 2.7, 3, 2.5, YELLOW),
    ("higher_better", 2.5, 3, 2.5, YELLOW),
    ("higher_better", 2.4, 3, 2.5, RED),
    ("higher_better", 1, 2, None, RED),        # blank yellow band: green or red
    ("higher_better", -1, 0, -2, YELLOW),      # buyout savings
    ("higher_better", -3, 0, -2, RED),
    ("lower_better", 0, 0, 1, GREEN),
    ("lower_better", 1, 0, 1, YELLOW),
    ("lower_better", 2, 0, 1, RED),
    ("lower_better", 5, 4, 5, YELLOW),         # jobs per PM
    ("lower_better", 6, 4, 5, RED),
    ("binary", 1, 1, None, GREEN),
    ("binary", 0, 1, None, RED),
    ("higher_better", 5, None, None, GREY),    # no target set
])
def test_color_table(direction, value, target, yellow, expected):
    assert color_for(direction, value, target, yellow) == expected


# --------------------------------------------------------------- parsing ----
def test_parse_number_and_dates():
    assert parse_number("$1,250,000") == 1250000
    assert parse_number("95%", "percent") == 95
    assert parse_number("(2)") == -2
    assert parse_number("Yes", "boolean") == 1
    assert parse_number("") is None
    with pytest.raises(ValueError):
        parse_number("about 3")
    assert parse_date("2026-09-28") == date(2026, 9, 28)
    assert parse_date("9/28/2026") == date(2026, 9, 28)
    assert parse_date("9/28/2026 10:05:00") == date(2026, 9, 28)
    assert monday_of(date(2026, 10, 1)) == date(2026, 9, 28)


def test_live_sheet_shape_parses_clean():
    m = parse_sheet(load_csvs())
    assert len(m.metrics) == 14
    assert [e for e in m.errors if e["level"] == "error"] == []
    assert len(m.targets["bd_qualified_pipeline"]) == 4
    assert m.metrics[0]["owner_name"] == "Chris Andresen"


def test_validation_rejects_and_flags_rows():
    m = parse_sheet(load_csvs([
        "not_a_metric,2026-09-28,5,,,",
        "gc_safety,someday,1,,,",
        "gc_safety,2026-09-28,lots,,,",
        "gc_jobs_behind,2026-09-29,1,,,",             # not a Monday -> warning, counted
        "bd_meetings_weekly,2026-09-28,1,,2026-09-28 09:00,",
        "bd_meetings_weekly,2026-09-28,3,,2026-09-28 10:00,",  # duplicate, later wins
        "gc_sub_score,2026-09-28,,,,",                # placeholder, no value: ignored
    ]))
    reasons = " | ".join(e["reason"] for e in m.errors)
    assert "unknown or inactive metric_id 'not_a_metric'" in reasons
    assert "week_of is not a date" in reasons
    assert "'lots' is not a number" in reasons
    assert "not a Monday" in reasons
    assert "entered twice" in reasons
    assert ("gc_safety", date(2026, 9, 28)) not in m.actuals
    assert m.actuals[("gc_jobs_behind", date(2026, 9, 28))]["value"] == 1
    assert m.actuals[("bd_meetings_weekly", date(2026, 9, 28))]["value"] == 3
    assert ("gc_sub_score", date(2026, 9, 28)) not in m.actuals
    rows = {e["row"] for e in m.errors}
    assert 2 in rows  # sheet row numbers are reported (header is row 1)


def test_missing_column_and_bad_owner():
    csvs = load_csvs()
    csvs["metrics"] = csvs["metrics"].replace("tpt@sixpeakcapital.com", "tom@nowhere.com", 1)
    csvs["actuals"] = "metric_id,value\n"
    m = parse_sheet(csvs)
    assert any("not on the people tab" in e["reason"] for e in m.errors)
    assert any(e["tab"] == "actuals" and "missing column" in e["reason"] for e in m.errors)


# ------------------------------------------------------------ glidepaths ----
def test_glidepath_interpolates_and_holds():
    m = parse_sheet(load_csvs())
    metric = next(x for x in m.metrics if x["metric_id"] == "bd_developer_contacts")
    rows = m.targets["bd_developer_contacts"]
    t0, _, g0 = resolve_target(metric, rows, date(2026, 9, 14))
    assert t0 == 0 and g0 is True
    mid, _, _ = resolve_target(metric, rows, date(2026, 12, 13))  # halfway 9/14 -> 3/14
    assert 9.5 < mid < 10.5
    t6, _, _ = resolve_target(metric, rows, date(2027, 3, 14))
    assert t6 == 20
    late, _, glide = resolve_target(metric, rows, date(2029, 1, 1))
    assert late == 30 and glide is False
    before, _, _ = resolve_target(metric, rows, date(2026, 9, 7))
    assert before is None  # before the first target row -> no target


def test_no_target_rows_uses_metrics_target_and_backlog_is_grey():
    m = parse_sheet(load_csvs(["gc_signed_backlog,2026-10-05,45000000,,,"]))
    v = build_view(m, date(2026, 10, 6), START)
    row = next(r for c in v["categories"] for r in c["rows"] if r["metric_id"] == "gc_signed_backlog")
    assert row["current"]["color"] == GREY
    assert row["current"]["target_display"] == "no target set"


# ---------------------------------------------------------------- view ------
def test_pre_launch_is_blank_not_red():
    v = build_view(parse_sheet(load_csvs()), date(2026, 9, 25), START)
    assert v["pre_launch"] is True
    assert v["counts"]["red"] == 0
    assert all(r["current"]["state"] == "pre" for c in v["categories"] for r in c["rows"])


def test_week_one_missing_numbers_are_red_not_reported():
    m = parse_sheet(load_csvs(["gc_safety,2026-09-28,0,,,", "bd_meetings_weekly,2026-09-28,1,,,"]))
    v = build_view(m, date(2026, 9, 29), START)
    assert v["metric_count"] == 14
    rows = {r["metric_id"]: r for c in v["categories"] for r in c["rows"]}
    assert rows["gc_safety"]["current"]["color"] == GREEN
    assert rows["bd_meetings_weekly"]["current"]["color"] == YELLOW
    assert rows["gc_jobs_behind"]["current"]["state"] == "missing"
    assert rows["gc_jobs_behind"]["current"]["color"] == RED
    assert v["counts"]["missing"] == 12
    assert "Grady Lakamp" in v["missing_by_owner"]
    assert [c["name"] for c in v["categories"]][0] == "Liquidity & Overhead"


def test_monthly_carry_forward_and_staleness():
    m = parse_sheet(load_csvs(["fin_runway_months,2026-09-28,3.4,,,"]))
    v = build_view(m, date(2026, 10, 20), START)
    row = next(r for c in v["categories"] for r in c["rows"] if r["metric_id"] == "fin_runway_months")
    assert row["current"]["state"] == "carried" and row["current"]["color"] == GREEN
    v2 = build_view(m, date(2026, 11, 16), START)  # 49 days later
    row2 = next(r for c in v2["categories"] for r in c["rows"] if r["metric_id"] == "fin_runway_months")
    assert row2["current"]["state"] == "stale" and row2["current"]["color"] == RED


def test_three_week_streak_and_trend():
    m = parse_sheet(load_csvs([
        "gc_safety,2026-09-28,3,,,", "gc_safety,2026-10-05,2,,,", "gc_safety,2026-10-12,4,,,",
        "gc_sub_score,2026-09-28,4.8,,,", "gc_sub_score,2026-10-05,4.5,,,", "gc_sub_score,2026-10-12,4.1,,,",
    ]))
    v = build_view(m, date(2026, 10, 13), START)
    rows = {r["metric_id"]: r for c in v["categories"] for r in c["rows"]}
    assert rows["gc_safety"]["streak"] == 3 and rows["gc_safety"]["streak_flag"]
    assert rows["gc_sub_score"]["trend_down"] is True
    assert rows["gc_sub_score"]["current"]["color"] == GREEN


# -------------------------------------------------------------- fetcher -----
class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.encoding = text, status, None


def test_fetcher_builds_urls_and_detects_html():
    calls = []

    def getter(url, params, timeout):
        calls.append((url, params["gid"]))
        return _Resp("a,b\n1,2\n")
    f = make_fetcher("https://docs.google.com/spreadsheets/d/e/XYZ/pubhtml",
                     parse_gids("metrics=1,actuals=2,targets=3,people=4"), getter)
    out = f()
    assert set(out) == {"metrics", "actuals", "targets", "people"}
    assert all(u == "https://docs.google.com/spreadsheets/d/e/XYZ/pub" for u, _ in calls)
    bad = make_fetcher("https://x/pub", parse_gids("metrics=1,actuals=2,targets=3,people=4"),
                       lambda url, params, timeout: _Resp("<html>nope</html>"))
    with pytest.raises(SheetFetchError):
        bad()


# -------------------------------------------------------------- service -----
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make_service(tmp_path, csvs, clock):
    storage = Storage(data_dir=tmp_path)
    state = {"csvs": csvs, "calls": 0, "fail": False}

    def fetcher():
        state["calls"] += 1
        if state["fail"]:
            raise SheetFetchError("network down")
        return dict(state["csvs"])
    return ScorecardService(storage, fetcher, START, now_fn=clock), state


def test_cache_reuses_for_ten_minutes_then_refetches(tmp_path):
    clock = Clock(et(2026, 10, 1, 9))
    svc, state = make_service(tmp_path, load_csvs(), clock)
    assert svc.current()["available"] and state["calls"] == 1
    clock.t += timedelta(minutes=5)
    svc.current()
    assert state["calls"] == 1
    clock.t += timedelta(minutes=6)
    svc.current()
    assert state["calls"] == 2


def test_sheet_unreachable_serves_last_good(tmp_path):
    clock = Clock(et(2026, 10, 1, 9))
    svc, state = make_service(tmp_path, load_csvs(), clock)
    svc.current()
    state["fail"] = True
    clock.t += timedelta(hours=2)
    out = svc.current()
    assert out["available"] is True and "network down" in out["fetch_error"]


def test_tuesday_freeze_pins_the_meeting_snapshot(tmp_path):
    clock = Clock(et(2026, 10, 6, 7, 30))  # Tuesday before 8
    svc, state = make_service(tmp_path, load_csvs(["gc_safety,2026-10-05,0,,,"]), clock)
    assert svc.freeze()["status"] == "skipped"
    clock.t = et(2026, 10, 6, 8, 5)
    assert svc.freeze()["status"] == "frozen"
    assert svc.freeze()["status"] == "skipped"  # only once
    # Someone edits the Sheet after 8:00 - the meeting view must not change.
    state["csvs"] = load_csvs(["gc_safety,2026-10-05,5,,,"])
    clock.t = et(2026, 10, 6, 10)
    out = svc.current()
    assert out["frozen"] is True
    rows = {r["metric_id"]: r for c in out["view"]["categories"] for r in c["rows"]}
    assert rows["gc_safety"]["current"]["color"] == GREEN
    # Manual refresh during the meeting supersedes the freeze.
    svc.refresh("Bob Kennedy")
    out = svc.current()
    rows = {r["metric_id"]: r for c in out["view"]["categories"] for r in c["rows"]}
    assert rows["gc_safety"]["current"]["color"] == RED
    assert out["snapshot"]["refreshed_by"] == "Bob Kennedy"
    # Wednesday: back to live.
    clock.t = et(2026, 10, 7, 9)
    assert svc.current()["frozen"] is False


def test_freeze_catches_up_if_cron_runs_late(tmp_path):
    clock = Clock(et(2026, 10, 6, 9, 55))
    svc, _ = make_service(tmp_path, load_csvs(), clock)
    assert svc.freeze()["status"] == "frozen"


# ---------------------------------------------------------------- routes ----
@pytest.fixture
def sc_app(tmp_config):
    app = create_app(tmp_config)
    state = {"csvs": load_csvs(["gc_safety,2026-09-28,0,,,"])}
    app.config["SCORECARD_FETCHER"] = lambda: dict(state["csvs"])
    app.config["SCORECARD_NOW"] = lambda: et(2026, 9, 30, 9)
    app.config["_state"] = state
    return app


def test_portal_renders_scorecard_first_in_nav(sc_app):
    with sc_app.test_client() as c:
        html = c.get("/").get_data(as_text=True)
    assert 'id="scorecard"' in html
    nav = html[html.index('class="top-nav"'):html.index("</nav>")]
    assert nav.index("#scorecard") < nav.index("#rocks") < nav.index("#todos")
    assert "Hit Rate" in nav and ">Scoreboard<" not in nav
    assert "not reported" in html
    assert "Months of runway" in html


def test_portal_survives_sheet_outage(tmp_config):
    app = create_app(tmp_config)

    def boom():
        raise SheetFetchError("unreachable")
    app.config["SCORECARD_FETCHER"] = boom
    with app.test_client() as c:
        resp = c.get("/")
    assert resp.status_code == 200
    assert "Scorecard unavailable" in resp.get_data(as_text=True)


def test_api_scorecard_and_refresh(sc_app):
    with sc_app.test_client() as c:
        data = c.get("/api/scorecard").get_json()
        assert data["available"] and data["view"]["metric_count"] == 14
        r = c.post("/api/scorecard/refresh", headers={"X-Actor": "Chris Aiello"})
        assert r.status_code == 200 and r.get_json()["snapshot"]["kind"] == "manual"


def test_ingest_job_requires_api_key_and_skips_outside_window(sc_app):
    with sc_app.test_client() as c:
        assert c.post("/api/jobs/ingest_scorecard").status_code == 401
        r = c.post("/api/jobs/ingest_scorecard", headers={"X-API-Key": "test-key"})
        assert r.get_json()["status"] == "skipped"
        r = c.post("/api/jobs/ingest_scorecard?force=true", headers={"X-API-Key": "test-key"})
        assert r.get_json()["status"] == "frozen"
