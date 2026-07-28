# AI-News — Projektplan

Software der overvåger de største AI-nyhedskilder, krydstjekker historier på tværs af kilder, vurderer om de er banebrydende eller branchechangende (særligt for IT-verdenen), og sender push-notifikationer til telefonen med:

- **Kort resumé** af hvad der er sket
- **Hvilket firma/aktør** der står bag
- **Hvordan det påvirker IT-branchen**
- **Link** til den primære artikel

---

## 1. Overordnet arkitektur

```
┌─────────────────────────────────────────────────────────────┐
│                    INGESTION (hvert 10.-15. min)            │
│  RSS/Atom-feeds · TLDR · Hacker News · Reddit · X-kilder    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    NORMALISERING & DEDUP                    │
│  URL-kanonisering · titel-fuzzy-match · embedding-lighed    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    KLYNGEDANNELSE & KRYDSTJEK               │
│  Samme historie fra flere kilder → én klynge                │
│  ≥2 uafhængige kilder = "bekræftet", ellers "ubekræftet"    │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    VÆSENTLIGHEDSVURDERING (LLM)             │
│  Score 0-10: er det banebrydende/branchechangende?          │
│  IT-relevans: udvikling, drift, sikkerhed, værktøjer, jobs  │
└──────────────────────────┬──────────────────────────────────┘
                           ▼ (kun score ≥ tærskel)
┌─────────────────────────────────────────────────────────────┐
│                    RESUMÉ & NOTIFIKATION                    │
│  LLM genererer: hvad/hvem/påvirkning + link                 │
│  Push via ntfy/Telegram/Pushover/Discord → telefonen        │
└─────────────────────────────────────────────────────────────┘
                           │
                     ┌─────┴─────┐
                     │  SQLite   │  (sete artikler, klynger,
                     │  database │   sendte notifikationer)
                     └───────────┘
```

---

## 2. Kilder

### Primære nyhedskilder (RSS/Atom — gratis og stabile)

| Kategori | Kilder |
|---|---|
| **Firma-blogs (førstehåndskilder)** | OpenAI News, Anthropic News, Google DeepMind Blog, Google AI Blog, Meta AI Blog, Microsoft AI Blog, Mistral, xAI, Hugging Face Blog, NVIDIA Blog |
| **Tech-medier** | TechCrunch (AI-sektion), The Verge (AI), VentureBeat AI, Ars Technica, Wired AI, MIT Technology Review |
| **Kuraterede nyhedsbreve** | TLDR AI (dagligt, RSS: `tldr.tech/api/rss/ai`) — fungerer både som kilde og som ekstra krydstjek af, hvad branchen selv fremhæver |
| **Nyhedsbureauer** | Reuters Technology, AP Technology (via RSS) |
| **Community/udvikler-signaler** | Hacker News (Algolia API, filtreret på AI-emner + points-tærskel), Reddit r/MachineLearning, r/LocalLLaMA, r/artificial (offentligt JSON-API) |
| **Forskning (valgfrit, fase 3)** | arXiv cs.AI/cs.CL (kun papers med stort buzz andre steder) |

### X (Twitter) og lignende

X's officielle API koster fra ~200 USD/md for læseadgang i praksis, og gratis-tier er reelt ubrugelig til overvågning. Strategi:

1. **Fase 1-2:** Fang X-signaler *indirekte* — når en tweet er vigtig, lander den på Hacker News, Reddit og i tech-medier inden for kort tid. Det dækker langt det meste uden API-omkostninger.
2. **Fase 3 (valgfrit tilkøb):** X API Basic-abonnement med en kurateret liste af nøglepersoner (Sam Altman, Dario Amodei, Demis Hassabis, Yann LeCun, officielle firma-konti m.fl.). Alternativt Bluesky (gratis API), hvor mange AI-forskere også poster.

Beslutningen om X-API tages først, når vi kan måle hvad den indirekte dækning misser.

### Krydstjek-princip

- En historie regnes som **bekræftet**, når den optræder i ≥2 uafhængige kilder (firma-blog + medie tæller som 2; to medier der begge citerer samme pressemeddelelse tæller også).
- **Ubekræftede** historier med meget høj score kan sendes markeret som "🔶 Ubekræftet — kun én kilde", så breaking news ikke forsinkes unødigt.
- Førstehåndskilder (firmaets egen blog/pressemeddelelse) vægtes højest og kræver ikke ekstra bekræftelse for produktlanceringer.

---

## 3. Pipeline i detaljer

### 3.1 Ingestion
- Python-worker der poller alle feeds hvert 10.-15. minut (`feedparser` + `httpx`).
- Hver artikel gemmes med: kilde, URL (kanoniseret — tracking-parametre fjernet), titel, publiceringstid, uddrag.
- Idempotent: allerede sete URL'er/GUID'er springes over.

### 3.2 Dedup og klyngedannelse
- Trin 1 (billigt): kanoniseret URL-match og fuzzy titel-match (fx `rapidfuzz`, tærskel ~85).
- Trin 2: embedding af titel+uddrag (Claude/Voyage embeddings eller lokal model) — cosinus-lighed over tærskel lægger artiklen i eksisterende klynge.
- En klynge = én historie med N kilder. Klyngens "primære link" er førstehåndskilden hvis den findes, ellers det mest ansete medie.

### 3.3 Væsentlighedsvurdering
- LLM-kald (Claude Haiku — billig og hurtig) pr. *ny eller opdateret klynge*, ikke pr. artikel.
- Prompten scorer 0-10 på to akser:
  - **Banebrydende/branchechangende:** ny modelgeneration, større opkøb/partnerskab, regulering, sikkerhedshændelse, prisændring, åbning/lukning af API'er, open source-udgivelser af betydning.
  - **IT-relevans:** påvirker det softwareudvikling, drift/infrastruktur, sikkerhed, udviklerværktøjer eller IT-arbejdsmarkedet?
- Kun klynger med samlet score over tærskel (konfigurerbar, start ~7) går videre. Alt logges, så tærsklen kan justeres ud fra hvad der (ikke) blev sendt.

### 3.4 Resumé og notifikation
- LLM genererer notifikationen på dansk i fast format:

  > **🚨 OpenAI lancerer GPT-6** *(bekræftet af 4 kilder)*
  > Ny modelgeneration med markant bedre kodeevner og lavere pris pr. token.
  > **Påvirkning:** Direkte konkurrence på udviklerværktøjer; forvent pres på priser hos alle udbydere og nye muligheder i CI/CD-automatisering.
  > 🔗 openai.com/blog/gpt-6

- **Leveringskanal — udskiftelig bag ét interface.** Fire kanaler er implementeret, og systemet vælger automatisk den første der har sine secrets sat:
  1. **ntfy.sh** (anbefalet i praksis): gratis, open source, apps til iOS/Android, ingen konto. Emnenavnet fungerer som adgangsnøgle på den offentlige server, så det genereres tilfældigt og opbevares som secret; selv-hosting med token understøttes.
  2. **Telegram-bot**: gratis officielt Bot API, rig formattering.
  3. **Pushover**: engangskøb (~5 USD), meget driftssikker.
  4. **Discord-webhook**: hvis appen alligevel er på telefonen.

  **Signal** blev fravalgt: intet officielt API, kræver selv-hostet `signal-cli`-daemon og et registreret nummer — for skrøbeligt til en ubemandet cron-pipeline.
- **Persondata:** Telefonnummer og `chat_id` opbevares udelukkende som secrets/miljøvariabler (GitHub Actions Secrets) — aldrig i repoet.
- **Anti-støj:** max N notifikationer/dag (konfigurerbart), nattestille (fx 23-07, breaking med score 10 undtaget), og opfølgninger på samme klynge opdaterer/erstattes frem for at sende igen.

### 3.5 Lagring
- **SQLite** (nul drift, rigeligt til formålet): tabeller for `articles`, `clusters`, `scores`, `notifications`.
- Muliggør senere web-dashboard og evaluering af, hvad der blev fanget/misset.

---

## 4. Teknologivalg

| Del | Valg | Begrundelse |
|---|---|---|
| Sprog | Python 3.12 | Bedste økosystem til feeds/scraping/LLM |
| Feeds | `feedparser`, `httpx` | Standard, robust |
| Dedup | `rapidfuzz` + embeddings | Billigt først, præcist bagefter |
| LLM | Claude Haiku (scoring) + Claude Sonnet (resuméer) | Pris/kvalitet matcher opgaverne |
| Database | SQLite | Ingen driftsbyrde |
| Push | ntfy / Telegram / Pushover / Discord (udskiftelig) | Gratis muligheder, push på iOS/Android, ingen låsning til én udbyder |
| Kørsel | GitHub Actions cron, kl. 12 og 22 dansk tid (sommertid håndteres i koden) | Gratis; Actions-cron kan drifte 5-15 min |
| Konfiguration | `config.yaml` (kilder, tærskler, stilletider) + secrets i miljøvariabler | Nemt at justere uden kodeændringer |

**Estimerede driftsomkostninger:** 0 kr. for infrastruktur (GitHub Actions + ntfy/Telegram) + LLM-forbrug skønnet **1-5 USD/md** (Haiku-scoring af ~50-150 klynger/dag + få Sonnet-resuméer). X API er eneste potentielt dyre tilkøb.

---

## 5. Faseplan

### Fase 1 — MVP (kernen virker end-to-end) ✅
- [x] Projektskelet: `pyproject.toml`, `config.yaml`, SQLite-skema
- [x] Ingestion af 10-15 RSS-feeds (firma-blogs + 4-5 medier + TLDR AI)
- [x] URL/titel-dedup
- [x] LLM-scoring med tærskel (Claude Haiku, structured outputs; heuristisk fallback uden API-nøgle)
- [x] Resumé-generering på dansk i det faste format (Claude Sonnet)
- [x] Push til telefonen via udskiftelig kanal — ntfy, Telegram, Pushover eller Discord (alle tokens som secrets)
- [x] Kørsel via GitHub Actions cron (hvert 15. min)

**Resultat:** Notifikationer på telefonen om de vigtigste AI-nyheder, typisk inden for 15-30 min efter publicering.

### Fase 2 — Krydstjek og kvalitet (delvist leveret i MVP)
- [ ] Embedding-baseret klyngedannelse på tværs af kilder (pt. fuzzy titelmatch — fanger ikke omskrevne overskrifter)
- [x] Bekræftet/ubekræftet-mærkning (≥2 uafhængige kilder eller førstehåndskilde)
- [x] Hacker News + Reddit som bekræftelses- og opdagelseskilder (Reddit kan 403'e fra datacenter-IP'er; håndteres som advarsel)
- [x] Anti-støj: dagligt loft, nattestille, ingen gentagelser pr. klynge
- [x] Logning af alle scores til senere tærskel-tuning (gemmes i `clusters`-tabellen)
- [ ] Sundhedstjek pr. kilde (alarm hvis en kilde er tavs >48 t)

### Fase 3 — Bredere signaler
- [ ] Bluesky-overvågning af nøglepersoner (gratis API)
- [ ] Evaluering: misser vi noget, som kun var på X? → beslutning om X API Basic
- [ ] Evt. arXiv-integration (kun papers med community-buzz)
- [ ] Ugentlig digest-mail/notifikation med overblik

### Fase 4 — Finpudsning (efter behov)
- [ ] Lille web-dashboard (historik, scores, hvad blev filtreret fra)
- [ ] Feedback-loop: 👍/👎 på notifikationer justerer tærskler/prompt
- [ ] Flere modtagere/kanaler, emne-filtre pr. modtager

---

## 6. Risici og modtræk

| Risiko | Modtræk |
|---|---|
| Notifikationstræthed (for meget støj) | Høj start-tærskel, dagligt loft, feedback-loop i fase 4 |
| Falske/overhypede historier | Krydstjek-kravet + kildevægtning; ubekræftet-mærkning |
| X-indhold utilgængeligt uden dyrt API | Indirekte dækning via HN/Reddit/medier; Bluesky; målt beslutning i fase 3 |
| Feeds ændrer format/dør | Sundhedstjek pr. kilde (alarm hvis en kilde er tavs >48 t) |
| GitHub Actions cron-drift (5-15 min forsinkelse) | Acceptabelt i fase 1; flyt til VPS hvis det bliver et problem |
| LLM-fejlvurdering af væsentlighed | Alle vurderinger logges; tærskel og prompt justeres på data |

---

## 7. Første skridt efter godkendelse af planen

1. Opsæt projektskelet og SQLite-skema (fase 1, punkt 1)
2. Implementér ingestion + dedup for de første 10-15 feeds
3. Scoring- og resumé-prompts + Telegram-integration
4. GitHub Actions-workflow og en uges prøvekørsel med lav tærskel for at samle kalibreringsdata
