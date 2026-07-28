"""Orkestrering: ingestion -> klyngedannelse -> scoring -> notifikation."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic

from . import dedup, ingest, llm, notify
from .config import Config

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    new_articles: int = 0
    scored: int = 0
    notified: int = 0
    skipped_quiet: int = 0
    skipped_run: bool = False
    errors: list[str] = field(default_factory=list)


def in_quiet_hours(hour: int, start: int, end: int) -> bool:
    """Stilleperiode der kan krydse midnat, fx start=23, end=7."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def is_confirmed(source_count: int, has_first_party: bool) -> bool:
    """Bekræftet: >= 2 uafhængige kilder, eller en førstehåndskilde (firma-blog)."""
    return source_count >= 2 or has_first_party


def _cluster_articles(conn: sqlite3.Connection, cluster_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM articles WHERE cluster_id = ?
           ORDER BY CASE source_type
                        WHEN 'first_party' THEN 0
                        WHEN 'media' THEN 1
                        WHEN 'newsletter' THEN 2
                        ELSE 3
                    END, id""",
        (cluster_id,),
    ).fetchall()


def notifications_sent_since(conn: sqlite3.Connection, since_utc: datetime) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE sent_at >= ?",
        (since_utc.isoformat(),),
    ).fetchone()
    return int(row["n"])


def _score_pending(
    conn: sqlite3.Connection,
    cfg: Config,
    client: anthropic.Anthropic | None,
    stats: RunStats,
) -> None:
    rows = conn.execute(
        """SELECT c.id, c.score, c.scored_source_count, c.notified_at,
                  COUNT(DISTINCT a.source) AS n_sources
           FROM clusters c JOIN articles a ON a.cluster_id = c.id
           GROUP BY c.id
           HAVING c.score IS NULL
               OR (c.notified_at IS NULL AND n_sources > c.scored_source_count)"""
    ).fetchall()

    for row in rows:
        articles = _cluster_articles(conn, row["id"])
        try:
            if client is not None:
                result = llm.score_cluster(client, cfg.scoring_model, articles)
            else:
                result = llm.heuristic_score(articles)
        except Exception as exc:  # noqa: BLE001 - én fejlende scoring må ikke stoppe kørslen
            log.warning("Scoring af klynge %s fejlede: %s", row["id"], exc)
            stats.errors.append(f"score cluster {row['id']}: {exc}")
            continue
        conn.execute(
            """UPDATE clusters
               SET score = ?, company = ?, score_reason = ?, scored_source_count = ?
               WHERE id = ?""",
            (result.overall, result.company, result.reason, row["n_sources"], row["id"]),
        )
        conn.commit()
        stats.scored += 1
        log.info("Klynge %s scoret %d: %s", row["id"], result.overall, result.reason)


def _notify_candidates(
    conn: sqlite3.Connection,
    cfg: Config,
    client: anthropic.Anthropic | None,
    notifier,
    stats: RunStats,
) -> None:
    now_utc = datetime.now(timezone.utc)
    tz = ZoneInfo(cfg.timezone)
    now_local = now_utc.astimezone(tz)
    quiet = in_quiet_hours(now_local.hour, cfg.quiet_start, cfg.quiet_end)

    local_midnight = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    sent_today = notifications_sent_since(conn, local_midnight.astimezone(timezone.utc))

    min_created = (now_utc - timedelta(hours=cfg.max_notify_age_hours)).isoformat()
    candidates = conn.execute(
        """SELECT c.id, c.score,
                  COUNT(DISTINCT a.source) AS n_sources,
                  MAX(a.source_type = 'first_party') AS has_first_party
           FROM clusters c JOIN articles a ON a.cluster_id = c.id
           WHERE c.notified_at IS NULL AND c.score >= ? AND c.created_at >= ?
           GROUP BY c.id
           ORDER BY c.score DESC, c.id""",
        (cfg.notify_score, min_created),
    ).fetchall()

    for row in candidates:
        if sent_today >= cfg.max_notifications_per_day:
            log.info("Dagligt loft nået (%d) — resten venter.", cfg.max_notifications_per_day)
            break
        if quiet and row["score"] < cfg.breaking_score:
            stats.skipped_quiet += 1
            continue

        articles = _cluster_articles(conn, row["id"])
        try:
            if client is not None:
                summary = llm.summarize_cluster(client, cfg.summary_model, articles)
            else:
                summary = llm.fallback_summary(articles)
        except Exception as exc:  # noqa: BLE001
            log.warning("Resumé for klynge %s fejlede, bruger fallback: %s", row["id"], exc)
            summary = llm.fallback_summary(articles)

        confirmed = is_confirmed(row["n_sources"], bool(row["has_first_party"]))
        note = notify.build_notification(
            summary, articles[0]["url"], row["n_sources"], confirmed, row["score"]
        )
        try:
            notifier.send(note)
        except Exception as exc:  # noqa: BLE001
            log.error("Afsendelse for klynge %s fejlede: %s", row["id"], exc)
            stats.errors.append(f"send cluster {row['id']}: {exc}")
            continue

        sent_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO notifications (cluster_id, channel, message, sent_at) VALUES (?, ?, ?, ?)",
            (row["id"], notifier.channel, note.plain(), sent_at),
        )
        conn.execute("UPDATE clusters SET notified_at = ? WHERE id = ?", (sent_at, row["id"]))
        conn.commit()
        sent_today += 1
        stats.notified += 1


def run(
    cfg: Config,
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    use_llm: bool = True,
    force: bool = False,
) -> RunStats:
    stats = RunStats()
    now = datetime.now(timezone.utc)

    # GitHub Actions cron kører i UTC, så workflowet vækkes på begge mulige
    # UTC-tidspunkter for sommer- og vintertid. Her afgøres, om det er den
    # rigtige lokale time — ellers afsluttes uden at hente noget.
    local_hour = now.astimezone(ZoneInfo(cfg.timezone)).hour
    if cfg.run_hours and not force and local_hour not in cfg.run_hours:
        log.info(
            "Kl. %02d lokalt er ikke et planlagt kørselstidspunkt (%s) — springer over.",
            local_hour,
            ", ".join(f"{h:02d}" for h in cfg.run_hours),
        )
        stats.skipped_run = True
        return stats

    articles = ingest.fetch_all(cfg)
    stats.fetched = len(articles)
    for article in articles:
        if dedup.assign_cluster(conn, article, now, cfg.cluster_window_hours, cfg.title_match_threshold) is not None:
            stats.new_articles += 1
    log.info("Hentet %d artikler, heraf %d nye", stats.fetched, stats.new_articles)

    client: anthropic.Anthropic | None = None
    if use_llm and cfg.anthropic_api_key:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    elif use_llm:
        log.warning("ANTHROPIC_API_KEY er ikke sat — falder tilbage til heuristisk scoring.")

    _score_pending(conn, cfg, client, stats)

    notifier = notify.build_notifier(cfg, dry_run=dry_run)

    _notify_candidates(conn, cfg, client, notifier, stats)
    return stats
