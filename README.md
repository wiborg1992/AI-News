# AI-News

Overvåger de største AI-nyhedskilder, krydstjekker historier på tværs af kilder, vurderer om de er banebrydende/branchechangende for IT-verdenen (via Claude), og pusher notifikationer til din telefon via Telegram.

Se [PLAN.md](PLAN.md) for arkitektur og faseplan.

## Sådan virker det

1. **Ingestion** — henter RSS-feeds (OpenAI, DeepMind, TechCrunch, TLDR AI m.fl.), Hacker News (Algolia API) og Reddit hvert 15. minut.
2. **Dedup & klyngedannelse** — samme historie fra flere kilder samles i én klynge (URL-kanonisering + fuzzy titelmatch).
3. **Krydstjek** — en klynge er *bekræftet* ved ≥2 uafhængige kilder eller en førstehåndskilde (firma-blog). Ellers markeres den "🔶 ubekræftet".
4. **Scoring** — Claude Haiku scorer 0-10 på banebrydende + IT-relevans. Kun score ≥ 7 (konfigurerbart) går videre.
5. **Notifikation** — Claude Sonnet skriver et dansk resumé (hvad/hvem/påvirkning + link), som sendes til Telegram. Max 8/dag, nattestille 23-07 (score 10 undtaget).

Uden `ANTHROPIC_API_KEY` kører systemet i degraderet tilstand med heuristisk keyword-scoring.

## Opsætning

### 1. Opret Telegram-bot (2 minutter)

1. Åbn Telegram og skriv til [@BotFather](https://t.me/BotFather) → `/newbot` → følg anvisningerne.
2. Gem bot-tokenet (ser ud som `123456789:AAF...`).
3. Åbn din nye bot i Telegram og tryk **Start** (ellers kan den ikke skrive til dig).
4. Find dit chat_id:

   ```bash
   export TELEGRAM_BOT_TOKEN="dit-bot-token"
   python -m ai_news telegram-setup
   ```

5. Test:

   ```bash
   export TELEGRAM_CHAT_ID="dit-chat-id"
   python -m ai_news test-notify
   ```

### 2. GitHub Actions (kører automatisk hvert 15. minut)

Tilføj tre secrets under **Settings → Secrets and variables → Actions**:

| Secret | Værdi |
|---|---|
| `ANTHROPIC_API_KEY` | API-nøgle fra [platform.claude.com](https://platform.claude.com) |
| `TELEGRAM_BOT_TOKEN` | Token fra @BotFather |
| `TELEGRAM_CHAT_ID` | Dit chat_id fra `telegram-setup` |

Workflowet ([.github/workflows/aggregate.yml](.github/workflows/aggregate.yml)) kører derefter selv. Det kan også startes manuelt under **Actions → AI News Aggregator → Run workflow** (med valgfri dry-run).

> Bemærk: GitHub Actions cron kan drifte 5-15 min — acceptabelt til formålet. Databasen gemmes mellem kørsler via Actions cache; ryddes cachen, starter historikken forfra (du får højst lidt dublet-støj i én kørsel).

### 3. Lokal kørsel

```bash
pip install -e ".[dev]"

# Dry-run uden LLM og uden Telegram — udskriver til konsollen
python -m ai_news run --dry-run --no-llm

# Rigtig kørsel
export ANTHROPIC_API_KEY="sk-ant-..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python -m ai_news run
```

## Konfiguration

Alt justeres i [config.yaml](config.yaml): kilder, score-tærskel, dagligt loft, stilleperiode, modeller. Secrets ligger **kun** i miljøvariabler/GitHub Secrets — aldrig i repoet.

## Tests

```bash
pytest
```

## Struktur

```
src/ai_news/
├── config.py    # config.yaml + secrets fra miljø
├── db.py        # SQLite-skema (articles, clusters, notifications)
├── ingest.py    # RSS + Hacker News + Reddit
├── dedup.py     # URL-kanonisering + fuzzy klyngedannelse
├── llm.py       # Claude-scoring/resumé + heuristisk fallback
├── notify.py    # Telegram + konsol
├── pipeline.py  # orkestrering + anti-støj (loft, stilletid)
└── __main__.py  # CLI: run | telegram-setup | test-notify
```
