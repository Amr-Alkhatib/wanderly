# Wanderly

**Discover more. Travel deeper.** A freshness-aware travel recommender that
ranks destinations with a transparent, per-factor score — and always
explains *why*, not just *what*.

TUM Project Work (IN8028).

---

## Architecture: three honest, separable layers

Wanderly is built so the recommendation can always be justified. The LLM is
**never** the ranker — it is an optional presentation layer on top of a
deterministic engine.

```
┌─────────────────────────────────────────────────────────────┐
│  web/            Presentation: thin views, templates          │
│                  (no business logic)                          │
├─────────────────────────────────────────────────────────────┤
│  intelligence/   Deterministic RecommendationEngine           │
│                  → ScoredCity + FactorContribution + explain()│
│                  Explainer interface (LLM = swappable, off by │
│                  default via NullExplainer)                   │
├─────────────────────────────────────────────────────────────┤
│  destinations/   Data layer: normalized Country/City/Activity │
│                  + provenance-stamped, time-grained           │
│                  MonthlyWeather / CostSnapshot / SafetyAdvisory│
│                  (the database is the differentiator)         │
└─────────────────────────────────────────────────────────────┘
```

**Why the LLM is not the ranker.** If the model produced the ranking, a
tutor asking "why does Hanoi rank above Marrakech?" gets "the model decided."
Instead, `RecommendationEngine` scores every city by transparent arithmetic
over four weighted factors (budget, safety, climate, interests), and each
`ScoredCity.explain()` returns a reproducible breakdown. The `Explainer` only
rephrases that breakdown; it cannot change a score.

**Freshness-aware.** Every volatile fact records its `source` and
`captured_at`. The engine flags any factor built on data older than its
freshness window, and the UI shows a ⚠ so an aging number is never presented
as fresh truth.

---

## Quick start (local, zero config)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate          # uses SQLite by default
python manage.py seed_demo        # populates a small demo dataset
python manage.py runserver
```

Visit http://127.0.0.1:8000/.

Run the tests:

```bash
python manage.py test
```

---

## Configuration

Security-sensitive and environment-specific values are read from the
environment (sensible local defaults are provided):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | insecure dev key | **Set a real value in production.** |
| `DJANGO_DEBUG` | `True` | `0` in production. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated. |
| `DJANGO_DB_ENGINE` | `sqlite3` | Set `postgresql` to use Postgres. |
| `DJANGO_DB_*` | — | Name/User/Password/Host/Port for Postgres. |
| `WANDERLY_EXPLAINER_BACKEND` | `intelligence.explainers.NullExplainer` | Dotted path to the explainer. Swap to a Gemini/Groq subclass to enable LLM prose — a config change, not an architecture change. |

---

## SQLite → PostgreSQL migration path

1. Provision Postgres and set `DJANGO_DB_ENGINE=postgresql` plus the
   `DJANGO_DB_*` variables.
2. `python manage.py migrate` against the empty Postgres database.
3. Re-run `python manage.py seed_demo` (environment-agnostic), **or** move
   existing data with `dumpdata`/`loaddata`.

---

## Docker

```bash
docker compose up --build
```

Brings up Postgres + the app (gunicorn, `DEBUG=0`), runs migrations on start,
and serves on http://localhost:8000/. Static files are served by WhiteNoise.

---

## Planned next steps (seams already in place)

These are intentionally **not** in this MVP, but the interfaces exist so they
drop in without rework:

- **Review ingestion**: a `ReviewSource` interface + `RedditSource` (PRAW),
  driven by a `scrape_reddit` management command.
- **ABSA model**: writes structured sentiment into `intelligence.CityAspectScore`
  (already consumed by the engine's interest factor).
- **Scheduled refresh**: GitHub Actions cron invoking the management commands
  (`scrape_reddit`, `refresh_weather`, `enrich_aspects`) — no Celery/Redis
  needed for an academic-scale pipeline.
