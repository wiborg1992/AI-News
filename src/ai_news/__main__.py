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
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Kør uanset schedule.run_hours (bruges ved manuel start)",
    )
    reset_parser = sub.add_parser(
        "reset", help="Nulstil sende-historik, så historier kan sendes igen"
    )
    reset_parser.add_argument(
        "--scores",
        action="store_true",
        help="Ryd også scores og kategorier, så alt vurderes forfra af LLM'en",
    )
    reset_parser.add_argument(
        "--all",
        action="store_true",
        help="Slet også alle artikler og klynger (helt frisk start)",
    )
    sub.add_parser("telegram-setup", help="Vis chat_id'er der har skrevet til Telegram-botten")
    sub.add_parser("ntfy-setup", help="Foreslå et tilfældigt ntfy-emnenavn")
    test_parser = sub.add_parser("test-notify", help="Send en testbesked via den valgte kanal")
    test_parser.add_argument("--message", default="AI-News er sat korrekt op!")

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

    if command == "reset":
        conn = db.connect(args.db)
        try:
            conn.execute("DELETE FROM notifications")
            if args.all:
                conn.execute("DELETE FROM articles")
                conn.execute("DELETE FROM clusters")
                print("Databasen er tømt — næste kørsel starter forfra.")
            elif args.scores:
                conn.execute(
                    """UPDATE clusters
                       SET notified_at = NULL, score = NULL, category = NULL,
                           score_reason = NULL, scored_source_count = 0"""
                )
                print(
                    "Sende-historik OG scores nulstillet — næste kørsel lader LLM'en "
                    "vurdere og kategorisere alt forfra."
                )
            else:
                conn.execute("UPDATE clusters SET notified_at = NULL")
                print("Sende-historik nulstillet — kvoten er fri, og historier kan sendes igen.")
            conn.commit()
        finally:
            conn.close()
        return 0

    if command == "ntfy-setup":
        topic = notify.suggest_ntfy_topic()
        print("1. Installer ntfy-appen (App Store / Google Play / F-Droid).")
        print(f"2. Tryk + og abonnér på emnet:  {topic}")
        print(f"3. Sæt NTFY_TOPIC={topic} som miljøvariabel / GitHub Secret.")
        print("4. Kør: python -m ai_news test-notify")
        print(
            "\nEmnenavnet er reelt din adgangsnøgle på det offentlige ntfy.sh — "
            "hold det for dig selv, ellers kan andre læse og sende dine notifikationer."
        )
        return 0

    if command == "test-notify":
        try:
            notifier = notify.build_notifier(cfg)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if notifier.channel == "console":
            print(
                "Ingen kanal konfigureret. Kør 'python -m ai_news ntfy-setup' for den "
                "hurtigste vej til notifikationer på telefonen.",
                file=sys.stderr,
            )
            return 1
        note = notify.Notification(
            title=f"✅ {args.message}",
            body="Det er en testbesked fra AI-News. Rigtige notifikationer indeholder "
            "resumé, påvirkning på IT-branchen og link til artiklen.",
            link="https://github.com/wiborg1992/AI-News",
            score=7,
        )
        notifier.send(note)
        print(f"Testbesked sendt via {notifier.channel}.")
        return 0

    conn = db.connect(args.db)
    try:
        stats = run_pipeline(
            cfg,
            conn,
            dry_run=getattr(args, "dry_run", False),
            use_llm=not getattr(args, "no_llm", False),
            force=getattr(args, "force", False),
        )
    finally:
        conn.close()

    if stats.skipped_run:
        print("Sprunget over — ikke et planlagt kørselstidspunkt (brug --force for at tvinge).")
        return 0

    print(
        f"Hentet: {stats.fetched} | nye: {stats.new_articles} | scoret: {stats.scored} "
        f"| lagt sammen: {stats.merged} | notificeret: {stats.notified} "
        f"| filtreret fra: {stats.skipped_category} | udskudt (stille): {stats.skipped_quiet}"
    )
    if stats.errors:
        print(f"Fejl undervejs: {len(stats.errors)} (se log)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
