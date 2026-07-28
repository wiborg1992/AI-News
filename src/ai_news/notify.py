"""Notifikationskanaler: Telegram (primær) og konsol (dry-run)."""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import urlparse

import httpx

from .llm import Summary

log = logging.getLogger(__name__)


def build_message(
    summary: Summary, link: str, source_count: int, confirmed: bool, score: int
) -> str:
    """Byg Telegram-beskeden (HTML parse mode). Alt LLM-output escapes."""
    emoji = "🚨" if score >= 9 else "🤖"
    if confirmed:
        status = f"bekræftet af {source_count} kilder" if source_count > 1 else "førstehåndskilde"
    else:
        status = "🔶 ubekræftet — kun én kilde"

    lines = [f"<b>{emoji} {html.escape(summary.headline)}</b> <i>({status})</i>"]
    if summary.body:
        lines.append(html.escape(summary.body))
    if summary.impact:
        lines.append(f"<b>Påvirkning:</b> {html.escape(summary.impact)}")
    domain = urlparse(link).netloc.removeprefix("www.")
    lines.append(f'🔗 <a href="{html.escape(link, quote=True)}">{html.escape(domain)}</a>')
    return "\n".join(lines)


class ConsoleNotifier:
    channel = "console"

    def send(self, message: str) -> None:
        text = re.sub(r"<[^>]+>", "", message)
        print("\n--- NOTIFIKATION (dry-run) ---")
        print(text)
        print("------------------------------")


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self._token = bot_token
        self._chat_id = chat_id

    def send(self, message: str) -> None:
        resp = httpx.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        resp.raise_for_status()


def print_chat_ids(bot_token: str) -> None:
    """Hjælper til førstegangsopsætning: viser chat_id'er der har skrevet til botten."""
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
    print("\nSæt TELEGRAM_CHAT_ID til dit chat_id (som GitHub Actions Secret eller miljøvariabel).")
