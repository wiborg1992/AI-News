# AI-News

Overvåger de største AI-nyhedskilder, krydstjekker historier på tværs af kilder, vurderer om de er banebrydende/branchechangende for IT-verdenen (via Claude), og pusher notifikationer til din telefon.

Se [PLAN.md](PLAN.md) for arkitektur og faseplan.

## Sådan virker det

1. **Ingestion** — henter RSS-feeds (OpenAI, DeepMind, TechCrunch, TLDR AI m.fl.), Hacker News (Algolia API) og Reddit hvert 15. minut.
2. **Dedup & klyngedannelse** — samme historie fra flere kilder samles i én klynge (URL-kanonisering + fuzzy titelmatch).
3. **Krydstjek** — en klynge er *bekræftet* ved ≥2 uafhængige kilder eller en førstehåndskilde (firma-blog). Ellers markeres den "🔶 ubekræftet".
4. **Scoring** — Claude Haiku scorer 0-10 på banebrydende + IT-relevans. Kun score ≥ 7 (konfigurerbart) går videre.
5. **Notifikation** — Claude Sonnet skriver et dansk resumé (hvad/hvem/påvirkning + link), som pushes til telefonen. Max 8/dag, nattestille 23-07 (score 10 undtaget).

Uden `ANTHROPIC_API_KEY` kører systemet i degraderet tilstand med heuristisk keyword-scoring.

## Opsætning

### 1. Vælg notifikationskanal

Fire kanaler understøttes. Systemet vælger automatisk den første, der har sine secrets sat (rækkefølge: ntfy → Telegram → Pushover → Discord), eller du kan låse valget med `notifications.channel` i `config.yaml`.

| Kanal | Pris | Opsætning | Noter |
|---|---|---|---|
| **ntfy** *(anbefalet)* | Gratis | ~2 min, ingen konto | Open source, apps til iOS/Android/F-Droid |
| Telegram | Gratis | Bot via @BotFather | Kræver at Telegram virker for dig |
| Pushover | ~5 USD engangskøb | Konto + app | Meget driftssikker |
| Discord | Gratis | Webhook-URL | Hvis du allerede har Discord på telefonen |

#### ntfy (hurtigste vej — ingen konto)

```bash
python -m ai_news ntfy-setup     # foreslår et tilfældigt emnenavn
```

1. Installer **ntfy**-appen (App Store / Google Play / F-Droid).
2. Tryk **+** i appen og abonnér på det foreslåede emnenavn.
3. Sæt det som miljøvariabel og test:

   ```bash
   export NTFY_TOPIC="ai-news-xxxxxxxxxxxx"
   python -m ai_news test-notify
   ```

> **Vigtigt:** På det offentlige ntfy.sh er emnenavnet reelt din adgangsnøgle — alle der kender navnet, kan læse *og* sende dine notifikationer. Brug derfor det tilfældige navn fra `ntfy-setup`, ikke fx `ai-news`. Vil du have rigtig adgangskontrol, kan du selv-hoste ntfy og sætte `NTFY_SERVER` + `NTFY_TOKEN`.

#### Telegram

1. Skriv til [@BotFather](https://t.me/BotFather) → `/newbot` → følg anvisningerne.
2. Åbn din nye bot og tryk **Start** (ellers kan den ikke skrive til dig).
3. Find dit chat_id og test:

   ```bash
   export TELEGRAM_BOT_TOKEN="dit-bot-token"
   python -m ai_news telegram-setup
   export TELEGRAM_CHAT_ID="dit-chat-id"
   python -m ai_news test-notify
   ```

#### Pushover / Discord

```bash
export PUSHOVER_TOKEN="..." PUSHOVER_USER="..."     # fra pushover.net
# eller
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python -m ai_news test-notify
```

### 2. GitHub Actions (kører automatisk hvert 15. minut)

Tilføj secrets under **Settings → Secrets and variables → Actions** — kun for den kanal du bruger:

| Secret | Værdi |
|---|---|
| `ANTHROPIC_API_KEY` | API-nøgle fra [platform.claude.com](https://platform.claude.com) |
| `NTFY_TOPIC` | Dit ntfy-emnenavn *(hvis du bruger ntfy)* |
| `NTFY_SERVER`, `NTFY_TOKEN` | Kun ved selv-hostet ntfy |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | *(hvis du bruger Telegram)* |
| `PUSHOVER_TOKEN`, `PUSHOVER_USER` | *(hvis du bruger Pushover)* |
| `DISCORD_WEBHOOK_URL` | *(hvis du bruger Discord)* |

Workflowet ([.github/workflows/aggregate.yml](.github/workflows/aggregate.yml)) kører derefter selv. Det kan også startes manuelt under **Actions → AI News Aggregator → Run workflow** (med valgfri dry-run).

> Bemærk: GitHub Actions cron kan drifte 5-15 min — acceptabelt til formålet. Databasen gemmes mellem kørsler via Actions cache; ryddes cachen, starter historikken forfra (du får højst lidt dublet-støj i én kørsel).

### 3. Lokal kørsel

```bash
pip install -e ".[dev]"

# Dry-run uden LLM og uden Telegram — udskriver til konsollen
python -m ai_news run --dry-run --no-llm

# Rigtig kørsel
export ANTHROPIC_API_KEY="sk-ant-..."
export NTFY_TOPIC="ai-news-xxxxxxxxxxxx"
python -m ai_news run
```

CLI-kommandoer:

| Kommando | Formål |
|---|---|
| `run` | Kør pipelinen (`--dry-run`, `--no-llm`) |
| `ntfy-setup` | Foreslå et tilfældigt ntfy-emnenavn |
| `telegram-setup` | Vis chat_id'er der har skrevet til botten |
| `test-notify` | Send en testbesked via den valgte kanal |

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
├── notify.py    # ntfy / Telegram / Pushover / Discord / konsol
├── pipeline.py  # orkestrering + anti-støj (loft, stilletid)
└── __main__.py  # CLI: run | telegram-setup | test-notify
```
