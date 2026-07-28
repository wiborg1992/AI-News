from datetime import datetime, timezone

from ai_news import db
from ai_news.dedup import RawArticle, assign_cluster, canonicalize, normalize_title

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def test_canonicalize_strips_tracking_params():
    url = "https://www.example.com/article/?utm_source=x&utm_medium=rss&fbclid=abc&id=42"
    assert canonicalize(url) == "https://example.com/article?id=42"


def test_canonicalize_strips_fragment_and_trailing_slash():
    assert canonicalize("https://Example.com/a/b/#section") == "https://example.com/a/b"


def test_canonicalize_same_story_different_tracking():
    a = canonicalize("https://openai.com/blog/gpt?utm_source=twitter")
    b = canonicalize("https://www.openai.com/blog/gpt/")
    assert a == b


def test_normalize_title():
    assert normalize_title("OpenAI launches GPT-6!") == "openai launches gpt 6"


def _article(url: str, title: str, source: str = "TestKilde", source_type: str = "media") -> RawArticle:
    return RawArticle(source=source, source_type=source_type, url=url, title=title)


def test_duplicate_url_is_skipped():
    conn = db.connect(":memory:")
    art = _article("https://example.com/a", "OpenAI launches GPT-6")
    assert assign_cluster(conn, art, NOW, 72, 87) is not None
    assert assign_cluster(conn, art, NOW, 72, 87) is None
    assert conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"] == 1


def test_similar_titles_share_cluster():
    conn = db.connect(":memory:")
    c1 = assign_cluster(conn, _article("https://a.com/1", "OpenAI launches GPT-6 with better coding"), NOW, 72, 87)
    c2 = assign_cluster(
        conn,
        _article("https://b.com/2", "OpenAI launches GPT-6, promising better coding", source="AndenKilde"),
        NOW,
        72,
        87,
    )
    assert c1 == c2


def test_different_stories_get_different_clusters():
    conn = db.connect(":memory:")
    c1 = assign_cluster(conn, _article("https://a.com/1", "OpenAI launches GPT-6"), NOW, 72, 87)
    c2 = assign_cluster(conn, _article("https://b.com/2", "EU passes new AI regulation for banks"), NOW, 72, 87)
    assert c1 != c2
