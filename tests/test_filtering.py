from ai_news.config import Filtering
from ai_news.llm import CATEGORIES, heuristic_score
from ai_news.pipeline import effective_score, passes_filter
from ai_news import db

FILTERING = Filtering(
    priority_categories=["model_launch", "model_update", "feature", "open_source", "pricing"],
    priority_boost=1,
    blocked_categories=["noise"],
    category_thresholds={
        "model_launch": 5,
        "model_update": 5,
        "feature": 6,
        "research": 9,
        "business": 8,
        "industry": 8,
    },
)
DEFAULT = 7


def test_noise_is_always_blocked():
    """Holdninger og rygter må aldrig sendes — heller ikke med topscore."""
    assert not passes_filter(10, "noise", FILTERING, DEFAULT)


def test_model_launch_passes_at_low_score():
    """En ny modellancering vil brugeren næsten altid vide."""
    assert passes_filter(4, "model_launch", FILTERING, DEFAULT)  # 4 + boost = 5
    assert not passes_filter(3, "model_launch", FILTERING, DEFAULT)


def test_model_update_passes_at_low_score():
    """Fx en opdatering til Fable."""
    assert passes_filter(4, "model_update", FILTERING, DEFAULT)


def test_research_needs_high_score():
    """Papers skal være banebrydende for at forstyrre."""
    assert not passes_filter(8, "research", FILTERING, DEFAULT)
    assert passes_filter(9, "research", FILTERING, DEFAULT)


def test_business_needs_high_score():
    assert not passes_filter(7, "business", FILTERING, DEFAULT)
    assert passes_filter(8, "business", FILTERING, DEFAULT)


def test_priority_boost_only_applies_to_priority_categories():
    assert effective_score(6, "feature", FILTERING) == 7
    assert effective_score(6, "research", FILTERING) == 6


def test_boost_cannot_exceed_ten():
    assert effective_score(10, "model_launch", FILTERING) == 10


def test_unknown_category_falls_back_to_default_threshold():
    assert passes_filter(7, "security", FILTERING, DEFAULT)
    assert not passes_filter(6, "security", FILTERING, DEFAULT)


def test_empty_filtering_behaves_like_plain_threshold():
    plain = Filtering()
    assert passes_filter(7, "noise", plain, DEFAULT)
    assert not passes_filter(6, "noise", plain, DEFAULT)


def _rows(conn, titles):
    now = "2026-07-28T12:00:00+00:00"
    cur = conn.execute("INSERT INTO clusters (created_at, updated_at) VALUES (?, ?)", (now, now))
    cid = cur.lastrowid
    for i, title in enumerate(titles):
        conn.execute(
            """INSERT INTO articles
               (cluster_id, source, source_type, url, canonical_url, title, summary, fetched_at)
               VALUES (?, ?, 'media', ?, ?, ?, '', ?)""",
            (cid, f"K{i}", f"https://x.com/{cid}/{i}", f"https://x.com/{cid}/{i}", title, now),
        )
    return conn.execute("SELECT * FROM articles WHERE cluster_id = ?", (cid,)).fetchall()


def test_heuristic_categories_are_valid():
    conn = db.connect(":memory:")
    cases = {
        "OpenAI launches GPT-6": "model_launch",
        "Anthropic releases open weights for Claude": "open_source",
        "New security vulnerability found in AI library": "security",
        "EU AI Act regulation takes effect": "regulation",
    }
    for title, expected in cases.items():
        result = heuristic_score(_rows(conn, [title]))
        assert result.category in CATEGORIES
        assert result.category == expected, f"{title!r} -> {result.category}"


def test_db_migration_adds_category_to_existing_database(tmp_path):
    """Databasen genbruges mellem Actions-kørsler — gammelt skema skal migreres."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """CREATE TABLE clusters (
               id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
               score INTEGER, company TEXT, score_reason TEXT,
               scored_source_count INTEGER NOT NULL DEFAULT 0, notified_at TEXT);"""
    )
    old.execute(
        "INSERT INTO clusters (created_at, updated_at, score) VALUES ('t', 't', 8)"
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(clusters)")}
    assert "category" in columns
    # Eksisterende rækker skal bevares
    assert conn.execute("SELECT score FROM clusters").fetchone()["score"] == 8
