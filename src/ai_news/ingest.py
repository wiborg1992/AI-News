"""Indhentning fra RSS-feeds, Hacker News (Algolia) og Reddit."""

from __future__ import annotations

import calendar
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from .config import Config, Feed
from .dedup import RawArticle

log = logging.getLogger(__name__)

USER_AGENT = "ai-news-aggregator/0.1 (+https://github.com/wiborg1992/AI-News)"


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def fetch_feed(client: httpx.Client, feed: Feed, max_age: timedelta) -> list[RawArticle]:
    resp = client.get(feed.url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    cutoff = datetime.now(timezone.utc) - max_age

    articles: list[RawArticle] = []
    for entry in parsed.entries:
        link = getattr(entry, "link", None)
        title = getattr(entry, "title", "").strip()
        if not link or not title:
            continue
        published = None
        struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if struct:
            published = datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
        if published and published < cutoff:
            continue
        summary = _strip_html(getattr(entry, "summary", ""))[:1000]
        articles.append(
            RawArticle(
                source=feed.name,
                source_type=feed.type,
                url=link,
                title=title,
                summary=summary,
                published_at=published,
            )
        )
    return articles


def _matches_keywords(title: str, keywords: list[str]) -> bool:
    for kw in keywords:
        if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", title, re.IGNORECASE):
            return True
    return False


def fetch_hackernews(client: httpx.Client, cfg: Config, max_age: timedelta) -> list[RawArticle]:
    since = int((datetime.now(timezone.utc) - max_age).timestamp())
    resp = client.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={
            "tags": "story",
            "numericFilters": f"points>={cfg.hackernews.min_points},created_at_i>={since}",
            "hitsPerPage": 100,
        },
    )
    resp.raise_for_status()
    articles: list[RawArticle] = []
    for hit in resp.json().get("hits", []):
        title = (hit.get("title") or "").strip()
        if not title or not _matches_keywords(title, cfg.hackernews.keywords):
            continue
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        articles.append(
            RawArticle(
                source="Hacker News",
                source_type="community",
                url=url,
                title=title,
                summary=f"{hit.get('points', 0)} points på Hacker News",
                published_at=datetime.fromtimestamp(hit["created_at_i"], tz=timezone.utc),
            )
        )
    return articles


def fetch_reddit(client: httpx.Client, cfg: Config, max_age: timedelta) -> list[RawArticle]:
    subs = "+".join(cfg.reddit.subreddits)
    resp = client.get(
        f"https://www.reddit.com/r/{subs}/top.json",
        params={"t": "day", "limit": 50, "raw_json": 1},
    )
    resp.raise_for_status()
    cutoff = datetime.now(timezone.utc) - max_age
    articles: list[RawArticle] = []
    for child in resp.json().get("data", {}).get("children", []):
        data = child.get("data", {})
        if data.get("score", 0) < cfg.reddit.min_score:
            continue
        created = datetime.fromtimestamp(data.get("created_utc", 0), tz=timezone.utc)
        if created < cutoff:
            continue
        if data.get("is_self"):
            url = "https://www.reddit.com" + data.get("permalink", "")
        else:
            url = data.get("url", "")
        title = (data.get("title") or "").strip()
        if not url or not title:
            continue
        articles.append(
            RawArticle(
                source=f"Reddit r/{data.get('subreddit', '')}",
                source_type="community",
                url=url,
                title=title,
                summary=f"{data.get('score', 0)} upvotes på r/{data.get('subreddit', '')}",
                published_at=created,
            )
        )
    return articles


def _is_social_signal(text: str, keywords: list[str], min_length: int) -> bool:
    """Sociale opslag er støjende. Behold kun dem der ligner nyheder:
    et nøgleord, et link, eller en post der er lang nok til at have substans."""
    if _matches_keywords(text, keywords):
        return True
    if "http://" in text or "https://" in text:
        return True
    return len(text) >= min_length


def fetch_x(client: httpx.Client, cfg: Config, max_age: timedelta) -> list[RawArticle]:
    """X/Twitter via nitter-instanser (gratis) med failover mellem instanser.

    Nitter er uofficielt og kan blive blokeret af X uden varsel. Fejler alle
    instanser, logges det og pipelinen fortsætter uden X-signalet.
    """
    if cfg.x_bearer_token:
        return _fetch_x_official(client, cfg, max_age)

    cutoff = datetime.now(timezone.utc) - max_age
    articles: list[RawArticle] = []
    dead_instances: set[str] = set()

    for account in cfg.x.accounts:
        for instance in cfg.x.instances:
            if instance in dead_instances:
                continue
            try:
                resp = client.get(f"{instance.rstrip('/')}/{account}/rss")
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
                if not parsed.entries:
                    dead_instances.add(instance)
                    continue
            except Exception as exc:  # noqa: BLE001 - prøv næste instans
                log.debug("nitter %s fejlede for @%s: %s", instance, account, exc)
                dead_instances.add(instance)
                continue

            for entry in parsed.entries:
                title = _strip_html(getattr(entry, "title", ""))
                link = getattr(entry, "link", "")
                if not title or not link:
                    continue
                if not cfg.x.include_retweets and title.startswith("RT by "):
                    continue
                if title.startswith("R to "):  # svar i tråde
                    continue
                published = None
                struct = getattr(entry, "published_parsed", None)
                if struct:
                    published = datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
                if published and published < cutoff:
                    continue
                if not _is_social_signal(title, cfg.x.keywords, cfg.x.min_length):
                    continue
                articles.append(
                    RawArticle(
                        source=f"X @{account}",
                        source_type="social",
                        # Link tilbage til x.com, ikke nitter-instansen
                        url=re.sub(r"^https?://[^/]+", "https://x.com", link).split("#")[0],
                        title=title[:300],
                        summary=f"Opslag fra @{account} på X",
                        published_at=published,
                    )
                )
            break  # instansen virkede for denne konto
        else:
            log.warning("Ingen nitter-instans kunne levere @%s", account)
    return articles


def _fetch_x_official(client: httpx.Client, cfg: Config, max_age: timedelta) -> list[RawArticle]:
    """Officielt X API v2 — kræver betalt adgang og X_BEARER_TOKEN."""
    headers = {"Authorization": f"Bearer {cfg.x_bearer_token}"}
    start = (datetime.now(timezone.utc) - max_age).strftime("%Y-%m-%dT%H:%M:%SZ")
    articles: list[RawArticle] = []
    for account in cfg.x.accounts:
        try:
            user = client.get(
                f"https://api.x.com/2/users/by/username/{account}", headers=headers
            )
            user.raise_for_status()
            user_id = user.json()["data"]["id"]
            resp = client.get(
                f"https://api.x.com/2/users/{user_id}/tweets",
                headers=headers,
                params={
                    "max_results": 25,
                    "start_time": start,
                    "tweet.fields": "created_at,text",
                    "exclude": "replies" if cfg.x.include_retweets else "replies,retweets",
                },
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("X API fejlede for @%s: %s", account, exc)
            continue

        for tweet in resp.json().get("data", []):
            text = tweet.get("text", "").strip()
            if not text or not _is_social_signal(text, cfg.x.keywords, cfg.x.min_length):
                continue
            created = tweet.get("created_at")
            articles.append(
                RawArticle(
                    source=f"X @{account}",
                    source_type="social",
                    url=f"https://x.com/{account}/status/{tweet['id']}",
                    title=text[:300],
                    summary=f"Opslag fra @{account} på X",
                    published_at=datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if created
                    else None,
                )
            )
    return articles


def fetch_bluesky(client: httpx.Client, cfg: Config, max_age: timedelta) -> list[RawArticle]:
    """Bluesky via det offentlige AppView-API — gratis og uden auth."""
    cutoff = datetime.now(timezone.utc) - max_age
    articles: list[RawArticle] = []
    for handle in cfg.bluesky.accounts:
        try:
            resp = client.get(
                "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                params={"actor": handle, "limit": 30, "filter": "posts_no_replies"},
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("Bluesky fejlede for @%s: %s", handle, exc)
            continue

        for item in resp.json().get("feed", []):
            post = item.get("post", {})
            if item.get("reason"):  # repost
                continue
            record = post.get("record", {})
            text = (record.get("text") or "").strip()
            created = record.get("createdAt")
            if not text or not created:
                continue
            published = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if published < cutoff:
                continue
            if not _is_social_signal(text, cfg.bluesky.keywords, cfg.bluesky.min_length):
                continue
            rkey = post.get("uri", "").rsplit("/", 1)[-1]
            articles.append(
                RawArticle(
                    source=f"Bluesky @{handle}",
                    source_type="social",
                    url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                    title=text[:300],
                    summary=f"Opslag fra @{handle} på Bluesky",
                    published_at=published,
                )
            )
    return articles


def fetch_all(cfg: Config) -> list[RawArticle]:
    """Hent alle kilder; en fejlende kilde logges og springes over."""
    max_age = timedelta(hours=cfg.max_article_age_hours)
    articles: list[RawArticle] = []
    with _client() as client:
        for feed in cfg.feeds:
            try:
                fetched = fetch_feed(client, feed, max_age)
                log.info("%s: %d artikler", feed.name, len(fetched))
                articles.extend(fetched)
            except Exception as exc:  # noqa: BLE001 - én død kilde må ikke stoppe resten
                log.warning("Kilden %s fejlede: %s", feed.name, exc)
        if cfg.hackernews.enabled:
            try:
                fetched = fetch_hackernews(client, cfg, max_age)
                log.info("Hacker News: %d artikler", len(fetched))
                articles.extend(fetched)
            except Exception as exc:  # noqa: BLE001
                log.warning("Hacker News fejlede: %s", exc)
        if cfg.reddit.enabled and cfg.reddit.subreddits:
            try:
                fetched = fetch_reddit(client, cfg, max_age)
                log.info("Reddit: %d artikler", len(fetched))
                articles.extend(fetched)
            except Exception as exc:  # noqa: BLE001
                log.warning("Reddit fejlede: %s", exc)
        if cfg.x.enabled and cfg.x.accounts:
            try:
                fetched = fetch_x(client, cfg, max_age)
                log.info("X: %d opslag", len(fetched))
                articles.extend(fetched)
            except Exception as exc:  # noqa: BLE001
                log.warning("X fejlede: %s", exc)
        if cfg.bluesky.enabled and cfg.bluesky.accounts:
            try:
                fetched = fetch_bluesky(client, cfg, max_age)
                log.info("Bluesky: %d opslag", len(fetched))
                articles.extend(fetched)
            except Exception as exc:  # noqa: BLE001
                log.warning("Bluesky fejlede: %s", exc)
    return articles
