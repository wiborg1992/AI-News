from datetime import datetime, timedelta, timezone

from ai_news import db
from ai_news.pipeline import in_quiet_hours, is_confirmed, notifications_sent_since


def test_quiet_hours_crossing_midnight():
    assert in_quiet_hours(23, 23, 7)
    assert in_quiet_hours(2, 23, 7)
    assert not in_quiet_hours(7, 23, 7)
    assert not in_quiet_hours(12, 23, 7)


def test_quiet_hours_same_day():
    assert in_quiet_hours(13, 12, 14)
    assert not in_quiet_hours(11, 12, 14)


def test_quiet_hours_disabled():
    assert not in_quiet_hours(3, 0, 0)


def test_confirmed_logic():
    assert is_confirmed(2, False)
    assert is_confirmed(1, True)
    assert not is_confirmed(1, False)


def test_notifications_sent_since():
    conn = db.connect(":memory:")
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    cur = conn.execute(
        "INSERT INTO clusters (created_at, updated_at) VALUES (?, ?)",
        (now.isoformat(), now.isoformat()),
    )
    cluster_id = cur.lastrowid
    for hours_ago in (1, 5, 30):
        conn.execute(
            "INSERT INTO notifications (cluster_id, channel, message, sent_at) VALUES (?, 'test', 'm', ?)",
            (cluster_id, (now - timedelta(hours=hours_ago)).isoformat()),
        )
    assert notifications_sent_since(conn, now - timedelta(hours=24)) == 2
