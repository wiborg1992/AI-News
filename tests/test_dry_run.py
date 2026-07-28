"""En tørkørsel skal være ikke-destruktiv: hverken forbruge kvote eller markere sendt."""

from datetime import datetime, timezone

from ai_news import db
from ai_news.config import Config, Filtering
from ai_news.pipeline import run

NOW = datetime.now(timezone.utc).isoformat()


def _cfg(**kw) -> Config:
    return Config(
        feeds=[],
        run_hours=[],
        notify_score=5,
        max_notifications_per_day=10,
        quiet_start=0,
        quiet_end=0,
        filtering=Filtering(),
        **kw,
    )


def _seed(conn, n: int = 3) -> None:
    """Læg n scorede, usendte klynger i databasen."""
    for i in range(n):
        # scored_source_count matcher antal kilder, så klyngen ikke scores om
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
            (cid, f"https://x.com/{i}", f"https://x.com/{i}", f"Nyhed {i}", NOW),
        )
    conn.commit()


def _state(conn) -> tuple[int, int]:
    sent = conn.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]
    marked = conn.execute(
        "SELECT COUNT(*) AS n FROM clusters WHERE notified_at IS NOT NULL"
    ).fetchone()["n"]
    return sent, marked


def test_dry_run_does_not_consume_quota_or_mark_sent(monkeypatch):
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    conn = db.connect(":memory:")
    _seed(conn)

    stats = run(_cfg(), conn, dry_run=True, use_llm=False, force=True)

    assert stats.notified == 3          # den viser hvad den ville sende
    assert _state(conn) == (0, 0)       # men ændrer ingenting


def test_dry_run_is_repeatable(monkeypatch):
    """To tørkørsler i træk skal give samme resultat — ikke 3 og så 0."""
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    conn = db.connect(":memory:")
    _seed(conn)

    first = run(_cfg(), conn, dry_run=True, use_llm=False, force=True)
    second = run(_cfg(), conn, dry_run=True, use_llm=False, force=True)

    assert first.notified == second.notified == 3


def test_real_run_after_dry_run_still_sends(monkeypatch):
    """Tørkørslen må ikke 'spise' historier, så de aldrig sendes rigtigt."""
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    conn = db.connect(":memory:")
    _seed(conn)

    run(_cfg(), conn, dry_run=True, use_llm=False, force=True)
    real = run(_cfg(), conn, dry_run=False, use_llm=False, force=True)

    assert real.notified == 3
    assert _state(conn) == (3, 3)


def test_real_run_does_consume_quota(monkeypatch):
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    conn = db.connect(":memory:")
    _seed(conn)

    first = run(_cfg(), conn, dry_run=False, use_llm=False, force=True)
    second = run(_cfg(), conn, dry_run=False, use_llm=False, force=True)

    assert first.notified == 3
    assert second.notified == 0  # allerede sendt, sendes ikke igen
