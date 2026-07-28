# AI-News

Overvåger de største AI-nyhedskilder, krydstjekker historier på tværs af kilder, vurderer om de er banebrydende/branchechangende for IT-verdenen (via Claude), og pusher notifikationer til din telefon.

Se [PLAN.md](PLAN.md) for arkitektur og faseplan.

## Sådan virker det

1. **Ingestion** — kl. 8, 12, 17 og 22 dansk tid hentes RSS-feeds (OpenAI, DeepMind, TechCrunch, TLDR AI m.fl.), Hacker News, Reddit, **X** (16 AI-konti) og **Bluesky**.
2. **Dedup & klyngedannelse** — samme historie fra flere kilder samles i én klynge (URL-kanonisering + fuzzy titelmatch).
3. **Krydstjek** — en klynge er *bekræftet* ved ≥2 uafhængige kilder eller en førstehåndskilde (firma-blog). Ellers markeres den "🔶 ubekræftet".
4. **Scoring & kategorisering** — Claude Haiku scorer 0-10 og placerer historien i én af 12 kategorier (`model_launch`, `model_update`, `feature`, `noise` …). Kategorien afgør tærsklen — se [Sortering](#sortering-hvad-slipper-igennem).
5. **Notifikation** — Claude Sonnet skriver et dansk resumé (hvad/hvem/påvirkning + link), som pushes til telefonen. Max 10/dag, nattestille 23-07 (score 10 undtaget).

## Sortering: hvad slipper igennem

Systemet sender ikke alt. Hver historie kategoriseres, og hver kategori har sin egen tærskel i [config.yaml](config.yaml) — så en modellancering slipper igennem tidligt, mens et forskningspaper skal være banebrydende:

| Kategori | Tærskel | Hvad det dækker |
|---|---|---|
| `model_launch` | 5 | Ny model eller modelgeneration |
| `model_update` | 5 | Opdatering af eksisterende model (fx Fable) |
| `feature`, `open_source`, `pricing` | 6 | Nye funktioner, åbne vægte, prisændringer |
| `security` | 7 | Sårbarheder, brud, AI-sikkerhed |
| `infrastructure`, `regulation`, `business`, `industry` | 8 | Chips, lovgivning, opkøb, anden IT-nyhed |
| `research` | 9 | Papers og benchmarks — kun hvis banebrydende |
| `noise` | **blokeret** | Holdninger, rygter, listicles, tutorials, marketing |

De fem første kategorier er markeret som `priority_categories` og får desuden +1 i score. Vil du have mere eller mindre igennem, justerer du `category_thresholds` — ikke den globale `notify_score`.

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

### 2. GitHub Actions (kører automatisk kl. 8, 12, 17 og 22)

Tilføj secrets under **Settings → Secrets and variables → Actions** — kun for den kanal du bruger:

| Secret | Værdi |
|---|---|
| `ANTHROPIC_API_KEY` | API-nøgle fra [platform.claude.com](https://platform.claude.com) |
| `X_BEARER_TOKEN` | *Valgfri.* Officielt X API (betalt). Uden den bruges gratis nitter |
| `NTFY_TOPIC` | Dit ntfy-emnenavn *(hvis du bruger ntfy)* |
| `NTFY_SERVER`, `NTFY_TOKEN` | Kun ved selv-hostet ntfy |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | *(hvis du bruger Telegram)* |
| `PUSHOVER_TOKEN`, `PUSHOVER_USER` | *(hvis du bruger Pushover)* |
| `DISCORD_WEBHOOK_URL` | *(hvis du bruger Discord)* |

Workflowet ([.github/workflows/aggregate.yml](.github/workflows/aggregate.yml)) kører derefter selv. Det kan også startes manuelt under **Actions → AI News Aggregator → Run workflow** — manuelle kørsler ignorerer tidsplanen. To valgfrie flueben:

- **Dry-run** — udskriver i loggen i stedet for at sende. Ændrer ingen tilstand: bruger ikke af dagens kvote og markerer ikke historier som sendt, så den kan gentages, og de rigtige notifikationer når stadig frem bagefter.
- **Reset** — nulstiller sende-historikken først, så allerede sendte historier kan sendes igen og dagens kvote frigøres.
- **Rescore** — rydder også scores og kategorier, så LLM'en vurderer alt forfra. Brug den efter ændringer i `category_thresholds` eller scoringsprompten; den koster flere API-kald, da hver klynge scores igen.

**Om tidsplanen og sommertid.** GitHub Actions cron kører altid i UTC, mens Danmark skifter mellem UTC+2 og UTC+1. Workflowet vækkes derfor på otte UTC-tidspunkter (6, 7, 10, 11, 15, 16, 20, 21), og pipelinen tjekker selv den lokale time mod `schedule.run_hours` i `config.yaml`. De fire "forkerte" vækninger afsluttes med det samme uden at hente noget, så du rammer 8, 12, 17 og 22 dansk tid præcist hele året — også hen over sommertidsskiftet.

Vil du have andre tidspunkter, skal **begge** steder rettes: `run_hours` i `config.yaml` (lokale timer) og `cron` i workflowet (de tilsvarende UTC-timer, både sommer og vinter).

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
| `run` | Kør pipelinen (`--dry-run`, `--no-llm`, `--force`) |
| `reset` | Nulstil sende-historik (`--scores` scorer alt forfra, `--all` tømmer databasen) |
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
├── ingest.py    # RSS + Hacker News + Reddit + X (nitter/API) + Bluesky
├── dedup.py     # URL-kanonisering + fuzzy klyngedannelse
├── llm.py       # Claude-scoring, kategorisering, resumé + heuristisk fallback
├── notify.py    # ntfy / Telegram / Pushover / Discord / konsol
├── pipeline.py  # orkestrering + kategorifilter + anti-støj (loft, stilletid)
└── __main__.py  # CLI: run | telegram-setup | test-notify
```
