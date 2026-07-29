"""Notifikationskanaler: ntfy, Telegram, Pushover, Discord og konsol.

Alle kanaler deler samme Notification-objekt; hver kanal renderer det selv.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .llm import Summary

log = logging.getLogger(__name__)


@dataclass
class Notification:
    """Kanaluafhængig repræsentation af én notifikation."""

    title: str
    body: str
    link: str
    score: int

    def plain(self) -> str:
        parts = [self.title]
        if self.body:
            parts.append(self.body)
        parts.append(f"🔗 {self.link}")
        return "\n\n".join(parts)


def build_notification(
    summary: Summary, link: str, source_count: int, confirmed: bool, score: int
) -> Notification:
    emoji = "🚨" if score >= 9 else "🤖"
    if confirmed:
        status = f"bekræftet af {source_count} kilder" if source_count > 1 else "førstehåndskilde"
    else:
        status = "🔶 ubekræftet — kun én kilde"

    body_parts = []
    if summary.body:
        body_parts.append(summary.body)
    if summary.impact:
        body_parts.append(f"Påvirkning: {summary.impact}")

    return Notification(
        title=f"{emoji} {summary.headline} ({status})",
        body="\n\n".join(body_parts),
        link=link,
        score=score,
    )


def build_digest(notes: list[Notification]) -> Notification:
    """Saml flere historier i én besked.

    Med fire daglige kørsler kommer nyhederne i klumper; ti separate
    notifikationer på én gang er værre end én samlet oversigt.
    """
    if len(notes) == 1:
        return notes[0]

    top_score = max(n.score for n in notes)
    emoji = "🚨" if top_score >= 9 else "🤖"
    lines = []
    for i, note in enumerate(notes, 1):
        # Fjern statusparentesen fra overskriften — den fylder for meget her
        headline = re.sub(r"\s*\((?:🔶 )?(?:bekræftet|ubekræftet|førstehåndskilde)[^)]*\)\s*$", "", note.title)
        headline = re.sub(r"^[🚨🤖]\s*", "", headline)
        lines.append(f"{i}. {headline}\n   {note.link}")

    return Notification(
        title=f"{emoji} {len(notes)} AI-nyheder",
        body="\n\n".join(lines),
        link=notes[0].link,
        score=top_score,
    )


class ConsoleNotifier:
    """Bruges til dry-run og som fallback når intet er konfigureret."""

    channel = "console"

    def send(self, note: Notification) -> None:
        print("\n--- NOTIFIKATION (dry-run) ---")
        print(note.plain())
        print("------------------------------")


class NtfyNotifier:
    """ntfy.sh — gratis, open source, apps til iOS/Android. Ingen konto nødvendig.

    Der publiceres med JSON-body i stedet for HTTP-headere, så danske tegn
    (æøå) og emoji overlever — ntfy-headere er begrænset til latin-1.
    """

    channel = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh", token: str | None = None):
        self._topic = topic
        self._server = server.rstrip("/")
        self._token = token

    def send(self, note: Notification) -> None:
        priority = 5 if note.score >= 9 else 4 if note.score >= 8 else 3
        payload = {
            "topic": self._topic,
            "title": note.title,
            "message": note.body or note.link,
            "priority": priority,
            "click": note.link,
        }
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        resp = httpx.post(self._server, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self._token = bot_token
        self._chat_id = chat_id

    def send(self, note: Notification) -> None:
        domain = urlparse(note.link).netloc.removeprefix("www.")
        lines = [f"<b>{html.escape(note.title)}</b>"]
        if note.body:
            lines.append(html.escape(note.body))
        lines.append(f'🔗 <a href="{html.escape(note.link, quote=True)}">{html.escape(domain)}</a>')
        resp = httpx.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={
                "chat_id": self._chat_id,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        resp.raise_for_status()


class PushoverNotifier:
    """Pushover — engangskøb (~5 USD pr. platform), meget driftssikker."""

    channel = "pushover"

    def __init__(self, app_token: str, user_key: str):
        self._app_token = app_token
        self._user_key = user_key

    def send(self, note: Notification) -> None:
        resp = httpx.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": self._app_token,
                "user": self._user_key,
                "title": note.title[:250],
                "message": (note.body or note.link)[:1024],
                "url": note.link,
                "url_title": "Læs artiklen",
                "priority": 1 if note.score >= 9 else 0,
            },
            timeout=20,
        )
        resp.raise_for_status()


class DiscordNotifier:
    """Discord-webhook — nyttig hvis du allerede har Discord på telefonen."""

    channel = "discord"

    def __init__(self, webhook_url: str):
        self._webhook_url = webhook_url

    def send(self, note: Notification) -> None:
        resp = httpx.post(
            self._webhook_url,
            json={
                "embeds": [
                    {
                        "title": note.title[:256],
                        "description": note.body[:4000],
                        "url": note.link,
                        "color": 0xE74C3C if note.score >= 9 else 0x3498DB,
                    }
                ]
            },
            timeout=20,
        )
        resp.raise_for_status()


def build_notifier(cfg, *, dry_run: bool = False):
    """Vælg kanal ud fra config og tilgængelige secrets.

    channel: auto | ntfy | telegram | pushover | discord | console
    'auto' tager den første kanal der har de nødvendige secrets sat.
    """
    if dry_run:
        return ConsoleNotifier()

    builders = {
        "ntfy": lambda: NtfyNotifier(cfg.ntfy_topic, cfg.ntfy_server, cfg.ntfy_token)
        if cfg.ntfy_topic
        else None,
        "telegram": lambda: TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
        if cfg.telegram_bot_token and cfg.telegram_chat_id
        else None,
        "pushover": lambda: PushoverNotifier(cfg.pushover_token, cfg.pushover_user)
        if cfg.pushover_token and cfg.pushover_user
        else None,
        "discord": lambda: DiscordNotifier(cfg.discord_webhook_url)
        if cfg.discord_webhook_url
        else None,
        "console": ConsoleNotifier,
    }

    requested = (cfg.notify_channel or "auto").lower()
    if requested != "auto":
        builder = builders.get(requested)
        if builder is None:
            raise ValueError(
                f"Ukendt kanal '{requested}'. Vælg mellem: {', '.join(builders)} eller auto."
            )
        notifier = builder()
        if notifier is None:
            raise ValueError(
                f"Kanalen '{requested}' er valgt, men dens secrets mangler. Se README."
            )
        return notifier

    for name in ("ntfy", "telegram", "pushover", "discord"):
        notifier = builders[name]()
        if notifier is not None:
            log.info("Bruger notifikationskanal: %s", name)
            return notifier

    log.warning(
        "Ingen notifikationskanal er konfigureret — udskriver til konsol. "
        "Sæt fx NTFY_TOPIC for at få beskeder på telefonen (se README)."
    )
    return ConsoleNotifier()


def print_chat_ids(bot_token: str) -> None:
    """Telegram-hjælper: viser chat_id'er der har skrevet til botten."""
    resp = httpx.get(f"https://api.telegram.org/bot{bot_token}/getUpdates", timeout=20)
    resp.raise_for_status()
    updates = resp.json().get("result", [])
    seen: dict[int, str] = {}
    for update in updates:
        msg = update.get("message") or update.get("edited_message") or {}
        chat = msg.get("chat", {})
        if "id" in chat:
            name = chat.get("username") or chat.get("first_name") or chat.get("title") or "?"
            seen[chat["id"]] = name
    if not seen:
        print("Ingen beskeder fundet. Åbn din bot i Telegram, tryk Start / skriv en besked, og kør igen.")
        return
    for chat_id, name in seen.items():
        print(f"chat_id: {chat_id}  ({name})")
    print("\nSæt TELEGRAM_CHAT_ID til dit chat_id.")


def suggest_ntfy_topic() -> str:
    """Foreslå et tilfældigt, svært-at-gætte emnenavn til ntfy."""
    import secrets

    return f"ai-news-{secrets.token_hex(6)}"
