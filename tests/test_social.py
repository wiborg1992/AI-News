"""Tests for X- og Bluesky-indhentning (forfiltrering og parsing)."""

from datetime import timedelta

import httpx

from ai_news.config import Bluesky, Config, XSource
from ai_news.ingest import _is_social_signal, fetch_bluesky, fetch_x

KEYWORDS = ["launch", "introducing", "model"]


def test_social_signal_keeps_announcements():
    assert _is_social_signal("Introducing our new model", KEYWORDS, 60)


def test_social_signal_keeps_posts_with_links():
    assert _is_social_signal("Read this https://example.com/x", KEYWORDS, 60)


def test_social_signal_keeps_long_posts():
    assert _is_social_signal("x" * 80, KEYWORDS, 60)


def test_social_signal_drops_short_chatter():
    """'wrong' og 'congrats!' må ikke ind i pipelinen."""
    assert not _is_social_signal("wrong", KEYWORDS, 60)
    assert not _is_social_signal("congrats on the amazing result!", KEYWORDS, 60)


RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Introducing our newest model, now available in the API</title>
<link>https://nitter.net/OpenAI/status/123#m</link>
<pubDate>Mon, 27 Jul 2026 10:00:00 GMT</pubDate></item>
<item><title>RT by @OpenAI: another lab shipped a new model today</title>
<link>https://nitter.net/OpenAI/status/124#m</link>
<pubDate>Mon, 27 Jul 2026 11:00:00 GMT</pubDate></item>
<item><title>thanks!</title>
<link>https://nitter.net/OpenAI/status/125#m</link>
<pubDate>Mon, 27 Jul 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""


def _x_cfg(**kw) -> Config:
    return Config(x=XSource(accounts=["OpenAI"], instances=["https://nitter.net"],
                            keywords=KEYWORDS, min_length=60, **kw))


def test_fetch_x_filters_and_rewrites_links():
    def handler(request):
        return httpx.Response(200, content=RSS.encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    articles = fetch_x(client, _x_cfg(), timedelta(days=3650))

    assert len(articles) == 1, [a.title for a in articles]
    art = articles[0]
    assert art.title.startswith("Introducing our newest model")
    # Link skal pege på x.com, ikke nitter-instansen, og uden #m-fragment
    assert art.url == "https://x.com/OpenAI/status/123"
    assert art.source == "X @OpenAI"
    assert art.source_type == "social"


def test_fetch_x_can_include_retweets():
    def handler(request):
        return httpx.Response(200, content=RSS.encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    articles = fetch_x(client, _x_cfg(include_retweets=True), timedelta(days=3650))
    assert len(articles) == 2


def test_fetch_x_fails_over_to_next_instance():
    """Nitter-instanser dør jævnligt — den næste skal overtage."""
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "dead.example":
            return httpx.Response(502)
        return httpx.Response(200, content=RSS.encode())

    cfg = Config(
        x=XSource(
            accounts=["OpenAI"],
            instances=["https://dead.example", "https://nitter.net"],
            keywords=KEYWORDS,
        )
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    articles = fetch_x(client, cfg, timedelta(days=3650))

    assert "dead.example" in seen and "nitter.net" in seen
    assert len(articles) == 1


def test_fetch_x_survives_all_instances_dead():
    def handler(request):
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_x(client, _x_cfg(), timedelta(days=3650)) == []


BSKY = {
    "feed": [
        {
            "post": {
                "uri": "at://did:plc:abc/app.bsky.feed.post/rkey1",
                "record": {
                    "text": "Introducing a new open source model release today",
                    "createdAt": "2026-07-27T10:00:00Z",
                },
            }
        },
        {
            "post": {
                "uri": "at://did:plc:abc/app.bsky.feed.post/rkey2",
                "record": {"text": "lol", "createdAt": "2026-07-27T11:00:00Z"},
            }
        },
        {
            "reason": {"$type": "app.bsky.feed.defs#reasonRepost"},
            "post": {
                "uri": "at://did:plc:abc/app.bsky.feed.post/rkey3",
                "record": {
                    "text": "Introducing something reposted from elsewhere",
                    "createdAt": "2026-07-27T12:00:00Z",
                },
            },
        },
    ]
}


def test_fetch_bluesky_filters_chatter_and_reposts():
    def handler(request):
        return httpx.Response(200, json=BSKY)

    cfg = Config(bluesky=Bluesky(accounts=["simonwillison.net"], keywords=KEYWORDS))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    articles = fetch_bluesky(client, cfg, timedelta(days=3650))

    assert len(articles) == 1
    assert articles[0].url == "https://bsky.app/profile/simonwillison.net/post/rkey1"
    assert articles[0].source_type == "social"


def test_fetch_bluesky_survives_error():
    def handler(request):
        return httpx.Response(500)

    cfg = Config(bluesky=Bluesky(accounts=["simonwillison.net"]))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_bluesky(client, cfg, timedelta(days=3650)) == []
