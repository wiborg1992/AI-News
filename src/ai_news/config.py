"""Indlæsning af config.yaml + secrets fra miljøvariabler."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Feed:
    name: str
    url: str
    type: str  # first_party | media | newsletter | community


@dataclass
class HackerNews:
    enabled: bool = True
    min_points: int = 100
    keywords: list[str] = field(default_factory=list)


@dataclass
class Reddit:
    enabled: bool = True
    min_score: int = 200
    subreddits: list[str] = field(default_factory=list)


@dataclass
class Config:
    timezone: str = "Europe/Copenhagen"
    language: str = "da"
    notify_score: int = 7
    breaking_score: int = 10
    max_notifications_per_day: int = 8
    cluster_window_hours: int = 72
    max_article_age_hours: int = 48
    max_notify_age_hours: int = 48
    title_match_threshold: int = 87
    quiet_start: int = 23
    quiet_end: int = 7
    scoring_model: str = "claude-haiku-4-5"
    summary_model: str = "claude-sonnet-5"
    feeds: list[Feed] = field(default_factory=list)
    hackernews: HackerNews = field(default_factory=HackerNews)
    reddit: Reddit = field(default_factory=Reddit)

    # Secrets fra miljøet
    anthropic_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    thresholds = raw.get("thresholds", {})
    limits = raw.get("limits", {})
    quiet = raw.get("quiet_hours", {})
    llm = raw.get("llm", {})
    hn = raw.get("hackernews", {})
    reddit = raw.get("reddit", {})

    return Config(
        timezone=raw.get("timezone", "Europe/Copenhagen"),
        language=raw.get("language", "da"),
        notify_score=int(thresholds.get("notify_score", 7)),
        breaking_score=int(thresholds.get("breaking_score", 10)),
        max_notifications_per_day=int(limits.get("max_notifications_per_day", 8)),
        cluster_window_hours=int(limits.get("cluster_window_hours", 72)),
        max_article_age_hours=int(limits.get("max_article_age_hours", 48)),
        max_notify_age_hours=int(limits.get("max_notify_age_hours", 48)),
        title_match_threshold=int(limits.get("title_match_threshold", 87)),
        quiet_start=int(quiet.get("start", 23)),
        quiet_end=int(quiet.get("end", 7)),
        scoring_model=llm.get("scoring_model", "claude-haiku-4-5"),
        summary_model=llm.get("summary_model", "claude-sonnet-5"),
        feeds=[Feed(name=f["name"], url=f["url"], type=f.get("type", "media")) for f in raw.get("feeds", [])],
        hackernews=HackerNews(
            enabled=bool(hn.get("enabled", True)),
            min_points=int(hn.get("min_points", 100)),
            keywords=list(hn.get("keywords", [])),
        ),
        reddit=Reddit(
            enabled=bool(reddit.get("enabled", True)),
            min_score=int(reddit.get("min_score", 200)),
            subreddits=list(reddit.get("subreddits", [])),
        ),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
    )
