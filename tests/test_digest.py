"""Digest: én samlet besked i stedet for én pr. historie."""

from datetime import datetime, timezone

from ai_news import db
from ai_news.config import Config, Filtering
from ai_news.notify import Notification, build_digest
from ai_news.pipeline import run

NOW = datetime.now(timezone.utc).isoformat()


def _note(title, link, score=7):
    return Notification(title=title, body="Krop.", link=link, score=score)


def test_digest_lists_every_story_with_its_link():
    notes = [
        _note("🚨 OpenAI lancerer GPT-6 (bekræftet af 3 kilder)", "https://a.example/1", 9),
        _note("🤖 Google opdaterer Gemini (🔶 ubekræftet — kun én kilde)", "https://b.example/2", 7),
    ]
    d = build_digest(notes)

    assert "2 AI-nyheder" in d.title
    assert "OpenAI lancerer GPT-6" in d.body
    assert "Google opdaterer Gemini" in d.body
    assert "https://a.example/1" in d.body
    assert "https://b.example/2" in d.body


def test_digest_strips_status_parentheses_from_headlines():
    d = build_digest([_note("🚨 Noget skete (bekræftet af 3 kilder)", "https://a/1"),
                      _note("🤖 Andet skete (🔶 ubekræftet — kun én kilde)", "https://b/2")])
    assert "bekræftet" not in d.body
    assert "🔶" not in d.body


def test_digest_uses_highest_score_for_priority():
    d = build_digest([_note("A", "https://a/1", 4), _note("B", "https://b/2", 9)])
    assert d.score == 9
    assert d.title.startswith("🚨")


def test_single_story_is_not_wrapped_in_a_digest():
    note = _note("🚨 Kun én ting", "https://a/1", 8)
    assert build_digest([note]) is note


def _cfg(digest: bool) -> Config:
    return Config(
        feeds=[], run_hours=[], notify_score=5, max_notifications_per_day=10,
        quiet_start=0, quiet_end=0, filtering=Filtering(), digest=digest,
    )


def _seed(conn, n):
    for i in range(n):
        cur = conn.execute(
            """INSERT INTO clusters (created_at, updated_at, score, category, scored_source_count)
               VALUES (?, ?, 9, 'feature', 1)""",
            (NOW, NOW),
        )
        cid = cur.lastrowid
        conn.execute(
            """INSERT INTO articles
               (cluster_id, source, source_type, url, canonical_url, title, summary, fetched_at)
               VALUES (?, 'Kilde', 'media', ?, ?, ?, '', ?)""",
            (cid, f"https://x.example/{i}", f"https://x.example/{i}", f"Nyhed {i}", NOW),
        )
    conn.commit()


class _Recorder:
    channel = "test"

    def __init__(self):
        self.sent = []

    def send(self, note):
        self.sent.append(note)


def _run_with(monkeypatch, digest: bool, stories: int = 3):
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    recorder = _Recorder()
    monkeypatch.setattr("ai_news.notify.build_notifier", lambda cfg, dry_run=False: recorder)
    conn = db.connect(":memory:")
    _seed(conn, stories)
    stats = run(_cfg(digest), conn, use_llm=False, force=True)
    return recorder, stats, conn


def test_digest_mode_sends_one_message_for_many_stories(monkeypatch):
    recorder, stats, conn = _run_with(monkeypatch, digest=True, stories=3)

    assert len(recorder.sent) == 1          # én besked på telefonen
    assert stats.notified == 3              # men tre historier er behandlet
    assert "3 AI-nyheder" in recorder.sent[0].title
    # Alle tre er markeret som sendt, så de ikke gentages
    assert conn.execute(
        "SELECT COUNT(*) n FROM clusters WHERE notified_at IS NOT NULL"
    ).fetchone()["n"] == 3


def test_without_digest_each_story_is_its_own_message(monkeypatch):
    recorder, stats, _ = _run_with(monkeypatch, digest=False, stories=3)
    assert len(recorder.sent) == 3
    assert stats.notified == 3


def test_digest_respects_daily_cap(monkeypatch):
    """Loftet tæller historier, ikke beskeder — digest ændrer kun indpakningen."""
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    recorder = _Recorder()
    monkeypatch.setattr("ai_news.notify.build_notifier", lambda cfg, dry_run=False: recorder)
    conn = db.connect(":memory:")
    _seed(conn, 15)

    cfg = _cfg(digest=True)
    cfg.max_notifications_per_day = 4
    stats = run(cfg, conn, use_llm=False, force=True)

    assert stats.notified == 4
    assert "4 AI-nyheder" in recorder.sent[0].title
