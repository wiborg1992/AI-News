from ai_news import db
from ai_news.llm import fallback_summary, heuristic_score
from ai_news.notify import TelegramNotifier, build_notification


def _rows(conn, items):
    now = "2026-07-28T12:00:00+00:00"
    cur = conn.execute("INSERT INTO clusters (created_at, updated_at) VALUES (?, ?)", (now, now))
    cluster_id = cur.lastrowid
    for i, (source, title, summary) in enumerate(items):
        conn.execute(
            """INSERT INTO articles
               (cluster_id, source, source_type, url, canonical_url, title, summary, fetched_at)
               VALUES (?, ?, 'media', ?, ?, ?, ?, ?)""",
            (cluster_id, source, f"https://x.com/{cluster_id}/{i}", f"https://x.com/{cluster_id}/{i}", title, summary, now),
        )
    return conn.execute("SELECT * FROM articles WHERE cluster_id = ?", (cluster_id,)).fetchall()


def test_heuristic_scores_launch_higher_than_paper():
    conn = db.connect(":memory:")
    launch = _rows(conn, [("A", "OpenAI launches GPT-6 for developers", "")])
    paper = _rows(conn, [("B", "New research paper on token embeddings", "")])
    assert heuristic_score(launch).overall > heuristic_score(paper).overall


def test_heuristic_multi_source_bonus():
    conn = db.connect(":memory:")
    single = _rows(conn, [("A", "Some AI news", "")])
    multi = _rows(conn, [("A", "Some AI news", ""), ("B", "Some AI news", ""), ("C", "Some AI news", "")])
    assert heuristic_score(multi).overall > heuristic_score(single).overall


def test_build_notification_contains_link_and_status():
    conn = db.connect(":memory:")
    rows = _rows(conn, [("A", "OpenAI lancerer GPT-6", "Ny modelgeneration")])
    note = build_notification(
        fallback_summary(rows), rows[0]["url"], source_count=2, confirmed=True, score=8
    )
    assert "bekræftet af 2 kilder" in note.title
    assert note.link == rows[0]["url"]
    assert note.link in note.plain()


def test_build_notification_unconfirmed_marker():
    conn = db.connect(":memory:")
    rows = _rows(conn, [("A", "Solo story", "")])
    note = build_notification(
        fallback_summary(rows), rows[0]["url"], source_count=1, confirmed=False, score=7
    )
    assert "ubekræftet" in note.title


def test_telegram_rendering_escapes_html_from_sources():
    """HTML fra kilder må aldrig nå Telegram uescapet."""
    conn = db.connect(":memory:")
    rows = _rows(conn, [("A", "Title <script>alert(1)</script>", "Summary & more")])
    note = build_notification(
        fallback_summary(rows), rows[0]["url"], source_count=1, confirmed=False, score=7
    )

    sent = {}

    class FakePost:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, **kwargs):
        sent["text"] = json["text"]
        return FakePost()

    import ai_news.notify as notify_mod

    original = notify_mod.httpx.post
    notify_mod.httpx.post = fake_post
    try:
        TelegramNotifier("token", "chat").send(note)
    finally:
        notify_mod.httpx.post = original

    assert "<script>" not in sent["text"]
    assert "&lt;script&gt;" in sent["text"]
    assert '<a href="https://x.com/' in sent["text"]
