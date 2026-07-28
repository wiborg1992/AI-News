"""LLM-scoring (Claude Haiku) og resumé-generering (Claude Sonnet) med heuristisk fallback."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass

import anthropic

log = logging.getLogger(__name__)

CATEGORIES = [
    "model_launch",   # helt ny model eller modelgeneration
    "model_update",   # opdatering af eksisterende model
    "feature",        # ny funktion, produkt eller API-kapabilitet
    "open_source",    # åbne vægte / open source-udgivelse af betydning
    "pricing",        # pris- eller tilgængelighedsændringer
    "infrastructure", # chips, compute, datacentre, cloud
    "security",       # sårbarheder, brud, AI-sikkerhed
    "regulation",     # lovgivning, politik, retsafgørelser
    "business",       # opkøb, investeringer, partnerskaber, ledelse
    "research",       # papers, benchmarks, videnskabelige resultater
    "industry",       # anden væsentlig IT-branchenyhed
    "noise",          # holdninger, rygter, listicles, tutorials, marketing
]

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "breakthrough": {"type": "integer"},
        "it_relevance": {"type": "integer"},
        "overall": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["company", "category", "breakthrough", "it_relevance", "overall", "reason"],
    "additionalProperties": False,
}

SCORE_SYSTEM = """\
You triage AI/tech news for an alert system used by an IT professional in Denmark.
They want concrete, actionable developments — not commentary. Specifically:
new model launches and model updates (e.g. a new Claude/GPT/Gemini version), new
features and API capabilities they could actually use, significant open source
releases, and price changes. Beyond AI, they also want genuinely notable IT
industry news. They do NOT want opinion pieces, speculation, rumors, listicles,
tutorials, "top 10 AI tools" articles, marketing, or funding gossip.

Given one story (possibly reported by several sources), return JSON with:

- company: the main company/organization behind the news ("" if none).

- category: exactly one of:
    model_launch   - a genuinely new model or model generation is released
    model_update   - an existing model gets a new version or notable capability
    feature        - a new product, feature, or API capability ships
    open_source    - significant open weights or open source release
    pricing        - price, quota, or availability changes
    infrastructure - chips, compute, datacenters, cloud capacity
    security       - vulnerabilities, breaches, AI security incidents
    regulation     - laws, policy, court rulings
    business       - acquisitions, funding, partnerships, leadership changes
    research       - papers, benchmarks, scientific results
    industry       - other genuinely notable IT industry news
    noise          - opinion, speculation, rumors, listicles, tutorials, marketing,
                     "X thinks Y about AI", personality drama, vague announcements
  Use "noise" generously. A social media post that merely reacts to news, teases
  something unannounced, or expresses an opinion is noise, even from a CEO.
  An announcement of something concrete and shipped is not noise.

- breakthrough (0-10): how groundbreaking or industry-changing this is.
- it_relevance (0-10): impact on software development, ops/infrastructure,
  security, developer tooling, or the IT job market.
- overall (0-10): combined significance. Reserve 8+ for genuinely major news a
  professional would want interrupted for. A 10 means drop-everything breaking news.
- reason: one short sentence in Danish explaining the score.

Be strict. Most stories deserve overall 5 or less. When a story is thin on
substance or you cannot tell what concretely happened, score it low."""

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

# Grov kategorigætning uden LLM. Rækkefølgen er prioriteret — første match vinder.
HEURISTIC_CATEGORIES = [
    ("model_launch", ["launches", "introducing", "unveils", "announcing", "meet "]),
    ("model_update", ["update", "now available", "upgraded", "improves", "version"]),
    ("open_source", ["open source", "open-source", "open weights", "open-weights"]),
    ("pricing", ["price", "pricing", "free tier", "cheaper", "cost"]),
    ("security", ["vulnerability", "breach", "exploit", "security", "cve-"]),
    ("regulation", ["regulation", "ai act", "lawsuit", "court", "policy", "ban"]),
    ("business", ["acquires", "acquisition", "funding", "raises", "partnership", "ipo"]),
    ("research", ["paper", "research", "benchmark", "study", "arxiv"]),
    ("feature", ["feature", "api", "launch", "release", "support for"]),
]


@dataclass
class ScoreResult:
    overall: int
    company: str
    reason: str
    category: str = "industry"


@dataclass
class Summary:
    headline: str
    body: str
    impact: str


DEDUP_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "story": {"type": "string"},
                    "cluster_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["story", "cluster_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["groups"],
    "additionalProperties": False,
}

DEDUP_SYSTEM = """\
You group news items that report the SAME underlying event, so a reader is not
notified twice about one story.

You get a numbered list of candidate items. Return groups of cluster_ids that
cover the same event, plus a short label for each group.

Group them only when they describe the same concrete event — the same launch,
the same incident, the same announcement — even when the wording differs a lot.
For example, "PSA: Your shared chats ended up on Google" and "Private chats
exposed in search results" are the same incident and belong together.

Do NOT group items merely because they share a topic, a company, or a product
line. Two separate features from the same vendor are two stories. A launch and
a later analysis of that launch are two stories.

Only return groups containing two or more cluster_ids. If nothing is a
duplicate, return an empty list."""


def find_duplicate_groups(
    client: anthropic.Anthropic, model: str, candidates: list[tuple[int, str]]
) -> list[list[int]]:
    """Find grupper af klynger der dækker samme begivenhed.

    Kører kun på de få kandidater der er sluppet gennem tærsklen, så det er
    ét billigt kald — ikke ét pr. artikel.
    """
    if len(candidates) < 2:
        return []

    listing = "\n".join(f"{cid}: {title[:200]}" for cid, title in candidates)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=DEDUP_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": DEDUP_SCHEMA}},
        messages=[{"role": "user", "content": listing}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)

    valid_ids = {cid for cid, _ in candidates}
    groups: list[list[int]] = []
    seen: set[int] = set()
    for group in data.get("groups", []):
        # Behold kun kendte id'er, og lad aldrig en klynge indgå i to grupper.
        ids = [i for i in dict.fromkeys(group.get("cluster_ids", [])) if i in valid_ids and i not in seen]
        if len(ids) >= 2:
            seen.update(ids)
            groups.append(ids)
    return groups


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
    category = str(data.get("category", "industry"))
    return ScoreResult(
        overall=_clamp(data.get("overall")),
        company=str(data.get("company", ""))[:100],
        reason=str(data.get("reason", ""))[:500],
        category=category if category in CATEGORIES else "industry",
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

    category = "industry"
    for name, keywords in HEURISTIC_CATEGORIES:
        if any(kw in text for kw in keywords):
            category = name
            break

    return ScoreResult(
        overall=score,
        company="",
        reason="Heuristisk score (ingen LLM)",
        category=category,
    )


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
