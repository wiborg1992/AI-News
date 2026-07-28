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
class XSource:
    """X/Twitter. Hentes gratis via nitter-instanser, eller via det officielle
    API hvis X_BEARER_TOKEN er sat (mere driftssikkert, men betalt)."""

    enabled: bool = True
    accounts: list[str] = field(default_factory=list)
    instances: list[str] = field(default_factory=list)
    include_retweets: bool = False
    min_length: int = 60
    keywords: list[str] = field(default_factory=list)


@dataclass
class Bluesky:
    enabled: bool = True
    accounts: list[str] = field(default_factory=list)
    min_length: int = 60
    keywords: list[str] = field(default_factory=list)


@dataclass
class Filtering:
    """Kategoribaseret sortering, så det ikke bare er ALT der sendes."""

    priority_categories: list[str] = field(default_factory=list)
    priority_boost: int = 1
    blocked_categories: list[str] = field(default_factory=list)
    category_thresholds: dict[str, int] = field(default_factory=dict)

    def threshold_for(self, category: str, default: int) -> int:
        return self.category_thresholds.get(category, default)


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
    run_hours: list[int] = field(default_factory=list)
    scoring_model: str = "claude-haiku-4-5"
    summary_model: str = "claude-sonnet-5"
    prices: dict[str, dict[str, float]] = field(default_factory=dict)
    dkk_per_usd: float = 0.0
    feeds: list[Feed] = field(default_factory=list)
    hackernews: HackerNews = field(default_factory=HackerNews)
    reddit: Reddit = field(default_factory=Reddit)
    x: XSource = field(default_factory=XSource)
    bluesky: Bluesky = field(default_factory=Bluesky)
    filtering: Filtering = field(default_factory=Filtering)

    # Notifikationskanal: auto | ntfy | telegram | pushover | discord | console
    notify_channel: str = "auto"
    ntfy_server: str = "https://ntfy.sh"

    # Secrets fra miljøet
    anthropic_api_key: str | None = None
    x_bearer_token: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    pushover_token: str | None = None
    pushover_user: str | None = None
    discord_webhook_url: str | None = None


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    thresholds = raw.get("thresholds", {})
    limits = raw.get("limits", {})
    quiet = raw.get("quiet_hours", {})
    llm = raw.get("llm", {})
    hn = raw.get("hackernews", {})
    reddit = raw.get("reddit", {})
    notifications = raw.get("notifications", {})
    ntfy = notifications.get("ntfy", {})
    schedule = raw.get("schedule", {})
    x = raw.get("x", {})
    bluesky = raw.get("bluesky", {})
    filtering = raw.get("filtering", {})

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
        run_hours=[int(h) for h in schedule.get("run_hours", [])],
        scoring_model=llm.get("scoring_model", "claude-haiku-4-5"),
        summary_model=llm.get("summary_model", "claude-sonnet-5"),
        prices={
            str(model): {str(k): float(v) for k, v in (rates or {}).items()}
            for model, rates in (llm.get("prices") or {}).items()
        },
        dkk_per_usd=float(llm.get("dkk_per_usd", 0.0)),
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
        x=XSource(
            enabled=bool(x.get("enabled", True)),
            accounts=list(x.get("accounts", [])),
            instances=list(x.get("instances", ["https://nitter.net"])),
            include_retweets=bool(x.get("include_retweets", False)),
            min_length=int(x.get("min_length", 60)),
            keywords=list(x.get("keywords", [])),
        ),
        bluesky=Bluesky(
            enabled=bool(bluesky.get("enabled", True)),
            accounts=list(bluesky.get("accounts", [])),
            min_length=int(bluesky.get("min_length", 60)),
            keywords=list(bluesky.get("keywords", [])),
        ),
        filtering=Filtering(
            priority_categories=list(filtering.get("priority_categories", [])),
            priority_boost=int(filtering.get("priority_boost", 1)),
            blocked_categories=list(filtering.get("blocked_categories", [])),
            category_thresholds={
                str(k): int(v) for k, v in (filtering.get("category_thresholds") or {}).items()
            },
        ),
        notify_channel=notifications.get("channel", "auto"),
        ntfy_server=os.environ.get("NTFY_SERVER") or ntfy.get("server", "https://ntfy.sh"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        x_bearer_token=os.environ.get("X_BEARER_TOKEN"),
        ntfy_topic=os.environ.get("NTFY_TOPIC") or ntfy.get("topic") or None,
        ntfy_token=os.environ.get("NTFY_TOKEN"),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        pushover_token=os.environ.get("PUSHOVER_TOKEN"),
        pushover_user=os.environ.get("PUSHOVER_USER"),
        discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL"),
    )
