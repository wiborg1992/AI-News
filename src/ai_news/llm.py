"""LLM-scoring (Claude Haiku) og resumé-generering (Claude Sonnet) med heuristisk fallback."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass

import anthropic

log = logging.getLogger(__name__)

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string"},
        "breakthrough": {"type": "integer"},
        "it_relevance": {"type": "integer"},
        "overall": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["company", "breakthrough", "it_relevance", "overall", "reason"],
    "additionalProperties": False,
}

SCORE_SYSTEM = """\
You score AI news stories for an alert system aimed at IT professionals in Denmark.
Given one story (possibly reported by several sources), return JSON with:
- company: the main company/organization behind the news ("" if none).
- breakthrough (0-10): how groundbreaking or industry-changing this is. High scores are for
  new model generations, major acquisitions/partnerships, regulation, big price/API changes,
  significant open source releases, or security incidents. Routine product updates, opinion
  pieces, funding rumors and minor research papers score low.
- it_relevance (0-10): impact on the IT industry — software development, ops/infrastructure,
  security, developer tools, or the IT job market.
- overall (0-10): combined significance for an IT professional. Only truly major news should
  reach 8+. A 10 means drop-everything breaking news.
- reason: one short sentence in Danish explaining the score.
Be strict: most stories deserve overall 5 or less."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "impact": {"type": "string"},
    },
    "required": ["headline", "body", "impact"],
    "additionalProperties": False,
}

SUMMARY_SYSTEM = """\
You write concise Danish push notifications about AI news for IT professionals.
Given a story (possibly covered by several sources), return JSON with:
- headline: short Danish headline naming the company, max 60 characters, no emoji.
- body: 1-2 Danish sentences on what happened.
- impact: 1-2 Danish sentences on how this affects the IT industry (development,
  ops, security, tooling or jobs). Be concrete.
Plain text only — no markdown, no HTML."""

# Heuristik når der ikke er nogen API-nøgle: groft keyword-baseret skøn.
HEURISTIC_KEYWORDS = {
    9: ["launches", "announces", "releases", "unveils", "acquires", "acquisition"],
    8: ["gpt-", "claude", "gemini", "open source", "open-source", "regulation", "eu ai act"],
    6: ["partnership", "funding", "billion", "api", "price"],
    4: ["research", "paper", "study", "benchmark"],
}


@dataclass
class ScoreResult:
    overall: int
    company: str
    reason: str


@dataclass
class Summary:
    headline: str
    body: str
    impact: str


def _clamp(value: object, lo: int = 0, hi: int = 10) -> int:
    try:
        return max(lo, min(hi, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return lo


def _cluster_text(articles: list[sqlite3.Row]) -> str:
    lines = []
    for art in articles[:8]:
        line = f"- [{art['source']}] {art['title']}"
        if art["summary"]:
            line += f"\n  {art['summary'][:300]}"
        lines.append(line)
    return "\n".join(lines)


def score_cluster(
    client: anthropic.Anthropic, model: str, articles: list[sqlite3.Row]
) -> ScoreResult:
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SCORE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
        messages=[{"role": "user", "content": _cluster_text(articles)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return ScoreResult(
        overall=_clamp(data.get("overall")),
        company=str(data.get("company", ""))[:100],
        reason=str(data.get("reason", ""))[:500],
    )


def heuristic_score(articles: list[sqlite3.Row]) -> ScoreResult:
    text = " ".join(a["title"].lower() for a in articles)
    score = 2
    for value, keywords in HEURISTIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            score = max(score, value)
    # Flere uafhængige kilder er i sig selv et signal om væsentlighed.
    if len({a["source"] for a in articles}) >= 3:
        score = min(10, score + 1)
    return ScoreResult(overall=score, company="", reason="Heuristisk score (ingen LLM)")


def summarize_cluster(
    client: anthropic.Anthropic, model: str, articles: list[sqlite3.Row]
) -> Summary:
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SUMMARY_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SUMMARY_SCHEMA}},
        messages=[{"role": "user", "content": _cluster_text(articles)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return Summary(
        headline=str(data.get("headline", ""))[:120],
        body=str(data.get("body", ""))[:600],
        impact=str(data.get("impact", ""))[:600],
    )


def fallback_summary(articles: list[sqlite3.Row]) -> Summary:
    primary = articles[0]
    body = re.sub(r"\s+", " ", primary["summary"] or "").strip()[:250]
    return Summary(headline=primary["title"][:120], body=body, impact="")
