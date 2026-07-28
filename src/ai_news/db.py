"""SQLite-skema og forbindelse."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    score INTEGER,
    company TEXT,
    category TEXT,
    score_reason TEXT,
    scored_source_count INTEGER NOT NULL DEFAULT 0,
    notified_at TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    cluster_id INTEGER NOT NULL REFERENCES clusters(id),
    source TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);
CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    cluster_id INTEGER NOT NULL REFERENCES clusters(id),
    channel TEXT NOT NULL,
    message TEXT NOT NULL,
    sent_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_sent ON notifications(sent_at);
"""


# Kolonner tilføjet efter første udgivelse. Databasen genbruges mellem
# GitHub Actions-kørsler, så nye kolonner skal tilføjes på eksisterende filer.
MIGRATIONS = [
    ("clusters", "category", "ALTER TABLE clusters ADD COLUMN category TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, statement in MIGRATIONS:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(statement)
    conn.commit()


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
