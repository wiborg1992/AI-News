"""Verificerer at cron-tidspunkterne rammer 12:00 og 22:00 dansk tid året rundt."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ai_news import db
from ai_news.config import Config
from ai_news.pipeline import run

CRON_UTC_HOURS = [10, 11, 20, 21]  # skal matche cron i .github/workflows/aggregate.yml
TARGET_LOCAL_HOURS = [12, 22]
TZ = ZoneInfo("Europe/Copenhagen")


def _local_hours_for(date_utc: datetime) -> list[int]:
    return [
        date_utc.replace(hour=h).astimezone(TZ).hour for h in CRON_UTC_HOURS
    ]


def test_summer_time_cron_hits_targets_exactly_twice():
    """Sommertid (UTC+2): 10 og 20 UTC rammer; 11 og 21 UTC skal frasorteres."""
    summer = datetime(2026, 7, 15, tzinfo=timezone.utc)
    local = _local_hours_for(summer)
    assert local == [12, 13, 22, 23]
    assert [h for h in local if h in TARGET_LOCAL_HOURS] == [12, 22]


def test_winter_time_cron_hits_targets_exactly_twice():
    """Vintertid (UTC+1): 11 og 21 UTC rammer; 10 og 20 UTC skal frasorteres."""
    winter = datetime(2026, 1, 15, tzinfo=timezone.utc)
    local = _local_hours_for(winter)
    assert local == [11, 12, 21, 22]
    assert [h for h in local if h in TARGET_LOCAL_HOURS] == [12, 22]


def test_every_day_of_year_gets_exactly_two_runs():
    """Uanset dato — inkl. selve sommertidsskiftene — må der køres præcis 2 gange."""
    for day in range(1, 366):
        date = datetime(2026, 1, 1, tzinfo=timezone.utc).replace(day=1)
        date = datetime.fromordinal(datetime(2026, 1, 1).toordinal() + day - 1).replace(
            tzinfo=timezone.utc
        )
        hits = [h for h in _local_hours_for(date) if h in TARGET_LOCAL_HOURS]
        assert len(hits) == 2, f"{date.date()} gav {hits}"


def _cfg(run_hours: list[int]) -> Config:
    return Config(timezone="Europe/Copenhagen", run_hours=run_hours, feeds=[])


def test_run_skips_outside_run_hours(monkeypatch):
    """Uden for de planlagte timer må pipelinen slet ikke hente noget."""
    called = []
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: called.append(1) or [])

    now_local = datetime.now(TZ).hour
    off_hours = [h for h in range(24) if h != now_local][:2]

    stats = run(_cfg(off_hours), db.connect(":memory:"), dry_run=True, use_llm=False)
    assert stats.skipped_run is True
    assert called == []


def test_force_overrides_run_hours(monkeypatch):
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    now_local = datetime.now(TZ).hour
    off_hours = [h for h in range(24) if h != now_local][:2]

    stats = run(_cfg(off_hours), db.connect(":memory:"), dry_run=True, use_llm=False, force=True)
    assert stats.skipped_run is False


def test_empty_run_hours_means_always_run(monkeypatch):
    monkeypatch.setattr("ai_news.ingest.fetch_all", lambda cfg: [])
    stats = run(_cfg([]), db.connect(":memory:"), dry_run=True, use_llm=False)
    assert stats.skipped_run is False
