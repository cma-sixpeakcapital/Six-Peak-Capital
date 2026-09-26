"""Fetch the published Google Sheet tabs as CSV.

The Sheet is published with File -> Share -> Publish to web (entire document,
auto-republish on). Each tab is served at::

    <pub_url>/pub?gid=<tab gid>&single=true&output=csv

No credentials are involved. Google serves published changes up to ~5 minutes
late, which is fine for a weekly meeting.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import requests

TABS = ("metrics", "actuals", "targets", "people")
TIMEOUT = 8  # seconds per tab (tabs are fetched in parallel)


class SheetFetchError(RuntimeError):
    pass


def parse_gids(raw: str) -> dict[str, str]:
    """'metrics=123,actuals=456' -> {'metrics': '123', 'actuals': '456'}"""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


def make_fetcher(pub_url: str, gids: dict[str, str],
                 http_get: Callable[..., requests.Response] | None = None
                 ) -> Callable[[], dict[str, str]]:
    """Return a zero-arg callable that fetches every tab and returns
    {tab_name: csv_text}. Raises SheetFetchError if any tab fails."""
    base = pub_url.rstrip("/")
    if base.endswith("/pubhtml") or base.endswith("/pub"):
        base = base.rsplit("/", 1)[0]
    getter = http_get or requests.get

    def fetch_one(tab: str) -> tuple[str, str]:
        gid = gids.get(tab)
        if not gid:
            raise SheetFetchError(f"no gid configured for tab '{tab}'")
        try:
            resp = getter(
                f"{base}/pub",
                params={"gid": gid, "single": "true", "output": "csv"},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:  # network, DNS, timeout
            raise SheetFetchError(f"{tab}: {exc}") from exc
        if resp.status_code != 200:
            raise SheetFetchError(f"{tab}: HTTP {resp.status_code}")
        resp.encoding = "utf-8"
        text = resp.text
        if text.lstrip().startswith("<"):
            # Google returns an HTML page when a tab is unpublished or the gid is wrong.
            raise SheetFetchError(f"{tab}: got HTML instead of CSV (tab not published or wrong gid)")
        return tab, text

    def fetch_all() -> dict[str, str]:
        with ThreadPoolExecutor(max_workers=len(TABS)) as pool:
            return dict(pool.map(fetch_one, TABS))

    return fetch_all
