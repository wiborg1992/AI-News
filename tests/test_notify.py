import pytest

from ai_news.config import Config
from ai_news.notify import (
    ConsoleNotifier,
    DiscordNotifier,
    Notification,
    NtfyNotifier,
    PushoverNotifier,
    TelegramNotifier,
    build_notifier,
    suggest_ntfy_topic,
)

NOTE = Notification(title="🚨 Test", body="Krop med æøå", link="https://example.com/a", score=9)


def test_auto_prefers_ntfy():
    cfg = Config(ntfy_topic="hemmeligt-emne", telegram_bot_token="t", telegram_chat_id="c")
    assert isinstance(build_notifier(cfg), NtfyNotifier)


def test_auto_falls_back_through_channels():
    assert isinstance(build_notifier(Config(telegram_bot_token="t", telegram_chat_id="c")), TelegramNotifier)
    assert isinstance(build_notifier(Config(pushover_token="t", pushover_user="u")), PushoverNotifier)
    assert isinstance(build_notifier(Config(discord_webhook_url="https://x")), DiscordNotifier)


def test_auto_falls_back_to_console_when_nothing_configured():
    assert isinstance(build_notifier(Config()), ConsoleNotifier)


def test_dry_run_always_console():
    cfg = Config(ntfy_topic="emne", notify_channel="ntfy")
    assert isinstance(build_notifier(cfg, dry_run=True), ConsoleNotifier)


def test_explicit_channel_without_secrets_raises():
    with pytest.raises(ValueError, match="secrets mangler"):
        build_notifier(Config(notify_channel="ntfy"))


def test_unknown_channel_raises():
    with pytest.raises(ValueError, match="Ukendt kanal"):
        build_notifier(Config(notify_channel="sms"))


def test_explicit_channel_overrides_auto_order():
    cfg = Config(
        notify_channel="telegram",
        ntfy_topic="emne",
        telegram_bot_token="t",
        telegram_chat_id="c",
    )
    assert isinstance(build_notifier(cfg), TelegramNotifier)


def test_ntfy_sends_json_so_danish_chars_survive(monkeypatch):
    """Danske tegn må ikke gå gennem HTTP-headere (latin-1); de skal i JSON-body."""
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("ai_news.notify.httpx.post", fake_post)
    NtfyNotifier("mit-emne").send(NOTE)

    assert captured["url"] == "https://ntfy.sh"
    assert captured["json"]["topic"] == "mit-emne"
    assert captured["json"]["message"] == "Krop med æøå"
    assert captured["json"]["click"] == "https://example.com/a"
    assert captured["json"]["priority"] == 5  # score 9 => høj prioritet


def test_ntfy_custom_server_and_token(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("ai_news.notify.httpx.post", fake_post)
    NtfyNotifier("emne", server="https://ntfy.mit-domæne.dk/", token="tk_123").send(NOTE)

    assert captured["url"] == "https://ntfy.mit-domæne.dk"
    assert captured["headers"]["Authorization"] == "Bearer tk_123"


def test_notification_plain_includes_all_parts():
    text = NOTE.plain()
    assert "🚨 Test" in text
    assert "Krop med æøå" in text
    assert "https://example.com/a" in text


def test_suggested_topics_are_unique_and_hard_to_guess():
    topics = {suggest_ntfy_topic() for _ in range(20)}
    assert len(topics) == 20
    assert all(t.startswith("ai-news-") and len(t) > 16 for t in topics)
