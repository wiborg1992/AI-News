"""CLI: python -m ai_news [run|telegram-setup|test-notify]"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import db, notify
from .config import load_config
from .pipeline import run as run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-news", description="AI-nyhedsaggregator")
    parser.add_argument("--config", default="config.yaml", help="Sti til config.yaml")
    parser.add_argument("--db", default="data/ai_news.db", help="Sti til SQLite-database")
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command")
    run_parser = sub.add_parser("run", help="Kør hele pipelinen (standard)")
    run_parser.add_argument("--dry-run", action="store_true", help="Udskriv notifikationer i stedet for at sende")
    run_parser.add_argument("--no-llm", action="store_true", help="Brug heuristisk scoring uden Claude API")
    sub.add_parser("telegram-setup", help="Vis chat_id'er der har skrevet til botten")
    test_parser = sub.add_parser("test-notify", help="Send en testbesked via Telegram")
    test_parser.add_argument("--message", default="✅ AI-News er sat korrekt op!")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    command = args.command or "run"
    cfg = load_config(args.config)

    if command == "telegram-setup":
        token = cfg.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            print("Sæt TELEGRAM_BOT_TOKEN først (token fra @BotFather).", file=sys.stderr)
            return 1
        notify.print_chat_ids(token)
        return 0

    if command == "test-notify":
        if not (cfg.telegram_bot_token and cfg.telegram_chat_id):
            print("Sæt TELEGRAM_BOT_TOKEN og TELEGRAM_CHAT_ID først.", file=sys.stderr)
            return 1
        notify.TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id).send(args.message)
        print("Testbesked sendt.")
        return 0

    conn = db.connect(args.db)
    try:
        stats = run_pipeline(
            cfg,
            conn,
            dry_run=getattr(args, "dry_run", False),
            use_llm=not getattr(args, "no_llm", False),
        )
    finally:
        conn.close()

    print(
        f"Hentet: {stats.fetched} | nye: {stats.new_articles} | scoret: {stats.scored} "
        f"| notificeret: {stats.notified} | udskudt (stille): {stats.skipped_quiet}"
    )
    if stats.errors:
        print(f"Fejl undervejs: {len(stats.errors)} (se log)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
