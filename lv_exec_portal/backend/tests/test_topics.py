"""Weekly summary grouped by topic, shown as bubbles — LV exec portal, ported from L10/IC (Chris, 9/30/2026)."""
from app.ingest import ensure_topics
from app.summarizer import clean_topics


class TopicSummarizer:
    def __init__(self, topics=None, fail=False):
        self.topics = topics if topics is not None else [
            {"topic": "Lien releases", "notes": ["Unconditional releases needed before the next draw."]},
            {"topic": "Klump & Scott", "notes": ["Investor approval received.", "Closing in about three months."]},
        ]
        self.fail = fail
        self.calls = 0

    def summarize(self, transcript, title="L10 Meeting"):
        return {"summary": "", "action_items": [], "files": []}

    def group_topics(self, summary, title="L10 Meeting"):
        self.calls += 1
        if self.fail:
            raise RuntimeError("api down")
        return self.topics


def _meeting():
    return {"id": "m1", "date": "2026-09-15", "title": "LV Executive meeting - monthly",
            "summary": "Subs provide conditional releases. The Clump and Scott deals got approval.",
            "action_items": [], "files": []}


def test_clean_topics_drops_empty():
    assert clean_topics([{"topic": " ", "notes": ["x"]}, {"topic": "A", "notes": [" ", ""]},
                         {"topic": "B", "notes": ["ok"]}, "junk"]) == [{"topic": "B", "notes": ["ok"]}]


def test_ensure_topics_once_and_records_failure():
    m = _meeting()
    s = TopicSummarizer()
    assert ensure_topics(m, s) is True and m["topics"][1]["topic"] == "Klump & Scott"
    assert ensure_topics(m, s) is False and s.calls == 1
    m2 = _meeting()
    assert ensure_topics(m2, TopicSummarizer(fail=True)) is True
    assert "api down" in m2["topics_error"] and "topics" not in m2


def test_portal_shows_topic_bubbles_and_stores_them(tmp_config, storage):
    from app import create_app
    storage.save_meeting(_meeting())
    app = create_app(tmp_config)
    s = TopicSummarizer()
    app.config["SUMMARIZER"] = s
    with app.test_client() as c:
        html = c.get("/").get_data(as_text=True)
        assert 'class="topic-bubble"' in html and "Lien releases" in html and "Closing in about three months." in html
        c.get("/")
        c.get("/meetings/m1")
    assert s.calls == 1  # grouped once, then read from the stored meeting
    assert app.config["STORAGE"].get_meeting("m1")["topics"]


def test_falls_back_to_bullets_when_grouping_fails(tmp_config, storage):
    from app import create_app
    storage.save_meeting(_meeting())
    app = create_app(tmp_config)
    app.config["SUMMARIZER"] = TopicSummarizer(fail=True)
    with app.test_client() as c:
        html = c.get("/").get_data(as_text=True)
    assert 'class="topic-bubble"' not in html and 'class="bullet-summary"' in html


def test_regroup_endpoint_requires_key(tmp_config, storage):
    from app import create_app
    storage.save_meeting(_meeting())
    app = create_app(tmp_config)
    app.config["SUMMARIZER"] = TopicSummarizer()
    with app.test_client() as c:
        assert c.post("/api/meetings/m1/topics").status_code == 401
        r = c.post("/api/meetings/m1/topics", headers={"X-API-Key": "test-key"})
        assert r.status_code == 200 and len(r.get_json()["topics"]) == 2


def test_put_topics_stores_and_validates(tmp_config, storage):
    from app import create_app
    storage.save_meeting(_meeting())
    app = create_app(tmp_config)
    with app.test_client() as c:
        assert c.put("/api/meetings/m1/topics", json={"topics": [{"topic": "X", "notes": []}]}).status_code == 400
        assert c.put("/api/meetings/nope/topics", json={"topics": []}).status_code == 404
        r = c.put("/api/meetings/m1/topics", json={"source": "claude-scheduled",
                  "topics": [{"topic": "Reseda", "notes": ["Steyn declined to leave equity in."]}]})
        assert r.status_code == 200
        html = c.get("/").get_data(as_text=True)
    m = app.config["STORAGE"].get_meeting("m1")
    assert m["topics"][0]["topic"] == "Reseda" and m["topics_source"] == "claude-scheduled"
    assert 'class="topic-bubble"' in html
