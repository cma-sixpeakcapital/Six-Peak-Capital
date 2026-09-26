"""Every to-do card shows its dates. A blank due date defaults to 7 days after
creation (Chris, 9/26/2026 decision 1), so "TBD" no longer appears for new to-dos."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def test_todo_cards_show_due_dates(client, storage):
    storage.add_todo({"owner": "Bob Kennedy", "task": "No date yet", "due": ""})
    storage.add_todo({"owner": "Chris Aiello", "task": "Dated", "due": "2026-10-06"})
    html = client.get("/").get_data(as_text=True)
    default = datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=7)
    assert f"Due: {default.month}/{default.day}" in html
    assert "Due: 10/6" in html
    assert "Due: TBD" not in html
    assert "Created " in html
