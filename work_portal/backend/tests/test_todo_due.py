"""Every to-do card shows its due date, or TBD when none was entered (Chris, 9/26/2026)."""


def test_todo_cards_show_due_or_tbd(client, storage):
    storage.add_todo({"owner": "Bob Kennedy", "task": "No date yet", "due": ""})
    storage.add_todo({"owner": "Bob Kennedy", "task": "Blank spaces", "due": "   "})
    storage.add_todo({"owner": "Chris Aiello", "task": "Dated", "due": "2026-10-06"})
    html = client.get("/").get_data(as_text=True)
    assert html.count("Due: TBD") == 2
    assert "Due: 2026-10-06" in html
