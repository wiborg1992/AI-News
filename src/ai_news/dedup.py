"""URL-kanonisering, titel-normalisering og klyngedannelse (fuzzy match)."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from rapidfuzz import fuzz

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "fbclid", "gclid", "msclkid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_src", "cmpid", "smid", "sref", "guccounter",
}


@dataclass
class RawArticle:
    source: str
    source_type: str
    url: str
    title: str
    summary: str = ""
    published_at: datetime | None = None


def canonicalize(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
        and not k.lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower() or "https", host, path, "", urlencode(sorted(params)), ""))


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9æøå]+", " ", title.lower()).strip()


def assign_cluster(
    conn: sqlite3.Connection,
    article: RawArticle,
    now: datetime,
    window_hours: int,
    threshold: int,
) -> int | None:
    """Indsæt artiklen og returnér dens cluster_id, eller None hvis den er en dublet."""
    canonical = canonicalize(article.url)
    existing = conn.execute(
        "SELECT id FROM articles WHERE canonical_url = ?", (canonical,)
    ).fetchone()
    if existing:
        return None

    cutoff = (now - timedelta(hours=window_hours)).isoformat()
    candidates = conn.execute(
        "SELECT cluster_id, title FROM articles WHERE fetched_at >= ?", (cutoff,)
    ).fetchall()

    norm = normalize_title(article.title)
    cluster_id: int | None = None
    best = 0.0
    for row in candidates:
        ratio = fuzz.token_set_ratio(norm, normalize_title(row["title"]))
        if ratio >= threshold and ratio > best:
            best = ratio
            cluster_id = row["cluster_id"]

    now_iso = now.isoformat()
    if cluster_id is None:
        cur = conn.execute(
            "INSERT INTO clusters (created_at, updated_at) VALUES (?, ?)",
            (now_iso, now_iso),
        )
        cluster_id = cur.lastrowid
    else:
        conn.execute(
            "UPDATE clusters SET updated_at = ? WHERE id = ?", (now_iso, cluster_id)
        )

    conn.execute(
        """INSERT INTO articles
           (cluster_id, source, source_type, url, canonical_url, title, summary, published_at, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cluster_id,
            article.source,
            article.source_type,
            article.url,
            canonical,
            article.title,
            article.summary,
            article.published_at.isoformat() if article.published_at else None,
            now_iso,
        ),
    )
    conn.commit()
    return cluster_id
