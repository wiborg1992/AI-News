"""Sammenlægning af klynger der dækker samme begivenhed."""

from ai_news import db
from ai_news.llm import find_duplicate_groups
from ai_news.pipeline import merge_clusters

NOW = "2026-07-28T12:00:00+00:00"


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]


class _FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.payload)


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def _seed_cluster(conn, score, category, articles) -> int:
    cur = conn.execute(
        """INSERT INTO clusters (created_at, updated_at, score, category, score_reason, scored_source_count)
           VALUES (?, ?, ?, ?, 'grund', 1)""",
        (NOW, NOW, score, category),
    )
    cid = cur.lastrowid
    for source, title in articles:
        url = f"https://{source}.example/{cid}/{title[:8]}"
        conn.execute(
            """INSERT INTO articles
               (cluster_id, source, source_type, url, canonical_url, title, summary, fetched_at)
               VALUES (?, ?, 'media', ?, ?, ?, '', ?)""",
            (cid, source, url, url, title, NOW),
        )
    conn.commit()
    return cid


def test_merge_combines_articles_and_keeps_oldest_cluster():
    conn = db.connect(":memory:")
    a = _seed_cluster(conn, 7, "security", [("TechCrunch", "Shared chats on Google")])
    b = _seed_cluster(conn, 9, "security", [("Wired", "Private chats exposed in search")])

    kept = merge_clusters(conn, [a, b])

    assert kept == a  # ældste beholdes
    assert conn.execute("SELECT COUNT(*) n FROM clusters").fetchone()["n"] == 1
    assert conn.execute(
        "SELECT COUNT(*) n FROM articles WHERE cluster_id = ?", (a,)
    ).fetchone()["n"] == 2
    row = conn.execute("SELECT score, scored_source_count FROM clusters WHERE id = ?", (a,)).fetchone()
    assert row["score"] == 9              # gruppens højeste score vinder
    assert row["scored_source_count"] == 2


def test_merged_cluster_counts_as_confirmed():
    """To medier om samme sag skal blive 'bekræftet af 2 kilder'."""
    from ai_news.pipeline import is_confirmed

    conn = db.connect(":memory:")
    a = _seed_cluster(conn, 7, "security", [("TechCrunch", "Shared chats on Google")])
    b = _seed_cluster(conn, 7, "security", [("Wired", "Private chats exposed")])

    assert not is_confirmed(1, False)  # hver for sig: ubekræftet
    merge_clusters(conn, [a, b])

    n = conn.execute(
        "SELECT COUNT(DISTINCT source) n FROM articles WHERE cluster_id = ?", (a,)
    ).fetchone()["n"]
    assert is_confirmed(n, False)


def test_merge_moves_existing_notifications():
    """Fremmednøglen må ikke knække hvis en klynge allerede har en notifikation."""
    conn = db.connect(":memory:")
    a = _seed_cluster(conn, 7, "feature", [("A", "Story one")])
    b = _seed_cluster(conn, 7, "feature", [("B", "Story two")])
    conn.execute(
        "INSERT INTO notifications (cluster_id, channel, message, sent_at) VALUES (?, 'ntfy', 'm', ?)",
        (b, NOW),
    )
    conn.commit()

    merge_clusters(conn, [a, b])
    assert conn.execute(
        "SELECT cluster_id FROM notifications"
    ).fetchone()["cluster_id"] == a


def test_find_duplicate_groups_parses_response():
    client = _FakeClient('{"groups": [{"story": "Claude chats", "cluster_ids": [1, 2]}]}')
    groups = find_duplicate_groups(client, "m", [(1, "Shared chats"), (2, "Private chats"), (3, "Andet")])
    assert groups == [[1, 2]]


def test_find_duplicate_groups_ignores_unknown_ids():
    client = _FakeClient('{"groups": [{"story": "x", "cluster_ids": [1, 99]}]}')
    assert find_duplicate_groups(client, "m", [(1, "A"), (2, "B")]) == []


def test_find_duplicate_groups_never_reuses_a_cluster():
    """En klynge må ikke indgå i to grupper — så ville sammenlægningen fejle."""
    client = _FakeClient(
        '{"groups": [{"story": "x", "cluster_ids": [1, 2]}, {"story": "y", "cluster_ids": [2, 3]}]}'
    )
    groups = find_duplicate_groups(client, "m", [(1, "A"), (2, "B"), (3, "C")])
    assert groups == [[1, 2]]


def test_find_duplicate_groups_skips_llm_call_for_single_candidate():
    client = _FakeClient('{"groups": []}')
    assert find_duplicate_groups(client, "m", [(1, "A")]) == []
    assert client.messages.calls == []  # intet unødigt API-kald
