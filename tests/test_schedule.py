"""Planlægning: en misset kørsel skal hentes ind af den næste vækning.

GitHubs cron er 'best effort' og dropper jævnligt kørsler. Testene her sikrer,
at et planlagt tidspunkt bliver betjent, selv når selve klokkeslættet blev
sprunget over — og at det kun betjenes én gang.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ai_news import db
from ai_news.config import Config
from ai_news.pipeline import LAST_RUN_KEY, is_run_due, last_scheduled_slot, run

TZ = ZoneInfo("Europe/Copenhagen")
RUN_HOURS = [8, 12, 17, 22]


def _cfg(run_hours=RUN_HOURS) -> Config:
    return Config(timezone="Europe/Copenhagen", run_hours=run_hours, feeds=[])


def _at(hour, minute=0, day=29) -> datetime:
    """Tidspunkt i dansk tid, returneret som UTC."""
    return datetime(2026, 7, day, hour, minute, tzinfo=TZ).astimezone(timezone.utc)


def test_last_slot_is_the_most_recent_passed_hour():
    now = datetime(2026, 7, 29, 13, 30, tzinfo=TZ)
    assert last_scheduled_slot(now, RUN_HOURS).hour == 12


def test_last_slot_reaches_back_to_yesterday_before_first_hour():
    now = datetime(2026, 7, 29, 3, 0, tzinfo=TZ)
    slot = last_scheduled_slot(now, RUN_HOURS)
    assert slot.hour == 22 and slot.day == 28


def test_first_run_is_always_due():
    conn = db.connect(":memory:")
    due, _ = is_run_due(conn, _cfg(), _at(9))
    assert due


def test_due_when_slot_passed_since_last_run():
    conn = db.connect(":memory:")
    db.set_state(conn, LAST_RUN_KEY, _at(8, 5).isoformat())
    due, _ = is_run_due(conn, _cfg(), _at(12, 3))
    assert due


def test_not_due_when_slot_already_served():
    conn = db.connect(":memory:")
    db.set_state(conn, LAST_RUN_KEY, _at(12, 3).isoformat())
    due, _ = is_run_due(conn, _cfg(), _at(13, 0))
    assert not due


def test_missed_slot_is_caught_up_by_a_later_wakeup():
    """Kernen: 08-kørslen blev droppet af GitHub — 10-vækningen skal tage den."""
    conn = db.connect(":memory:")
    db.set_state(conn, LAST_RUN_KEY, _at(22, 0, day=28).isoformat())
    due, reason = is_run_due(conn, _cfg(), _at(10, 0))
    assert due, reason
    assert "08:00" in reason


def test_catch_up_happens_only_once():
    conn = db.connect(":memory:")
    db.set_state(conn, LAST_RUN_KEY, _at(22, 0, day=28).isoformat())
    assert is_run_due(conn, _cfg(), _at(10, 0))[0]

    db.set_state(conn, LAST_RUN_KEY, _at(10, 1).isoformat())
    assert not is_run_due(conn, _cfg(), _at(11, 0))[0]


def test_every_hour_of_the_day_serves_each_slot_exactly_once(monkeypatch):
    """Simulér timevis cron gennem et døgn: præcis 4 kørsler."""
    conn = db.connect(":memory:")
    db.set_state(conn, LAST_RUN_KEY, _at(22, 5, day=28).isoformat())

    served = []
    for hour in range(24):
        now = _at(hour, 2)
        due, _ = is_run_due(conn, _cfg(), now)
        if due:
            served.append(hour)
            db.set_state(conn, LAST_RUN_KEY, now.isoformat())

    assert served == RUN_HOURS


def test_dropped_wakeups_lose_no_slot_and_repeat_none():
    """Selv hvis GitHub kun fyrer hver 3. time, betjenes hvert planlagt
    tidspunkt præcis én gang — nogle blot forsinket (22-kørslen først efter
    midnat). Det afgørende er, at intet tidspunkt går tabt eller køres dobbelt.
    """
    conn = db.connect(":memory:")
    db.set_state(conn, LAST_RUN_KEY, _at(22, 5, day=28).isoformat())

    served_slots = []
    for day in (29, 30):
        for hour in range(0, 24, 3):  # kun hver 3. vækning overlever
            now = _at(hour, 7, day=day)
            due, _ = is_run_due(conn, _cfg(), now)
            if due:
                slot = last_scheduled_slot(now.astimezone(TZ), RUN_HOURS)
                served_slots.append((slot.day, slot.hour))
                db.set_state(conn, LAST_RUN_KEY, now.isoformat())

    day29 = [hour for day, hour in served_slots if day == 29]
    assert day29 == RUN_HOURS                      # alle fire, i rækkefølge
    assert len(served_slots) == len(set(served_slots))  # ingen dobbeltkørsel


def test_empty_run_hours_always_runs():
    conn = db.connect(":memory:")
    assert is_run_due(conn, _cfg(run_hours=[]), _at(3))[0]


def test_real_run_records_timestamp_but_dry_run_does_not(monkeypatch):
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    conn = db.connect(":memory:")

    run(_cfg(), conn, dry_run=True, use_llm=False, force=True)
    assert db.get_state(conn, LAST_RUN_KEY) is None

    run(_cfg(), conn, dry_run=False, use_llm=False, force=True)
    assert db.get_state(conn, LAST_RUN_KEY) is not None


def test_run_skips_when_not_due(monkeypatch):
    called = []
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: called.append(1) or [])
    conn = db.connect(":memory:")
    # Marker den seneste slot som netop betjent
    now = datetime.now(timezone.utc)
    db.set_state(conn, LAST_RUN_KEY, now.isoformat())

    stats = run(_cfg(), conn, dry_run=True, use_llm=False)
    assert stats.skipped_run is True
    assert called == []
