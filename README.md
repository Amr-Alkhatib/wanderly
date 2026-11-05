# Wanderly

**Discover more. Travel deeper.** Wanderly is a travel recommender that ranks destinations with a transparent score broken down factor by factor, and always explains *why* a city ranks where it does, not just *what* the ranking is.

TUM Project Work (IN8028) · Python · Django · PostgreSQL / SQLite · Supabase Auth · Docker

---

## What it does

- **Personal ranking.** Users set budget, safety, climate and interest preferences. Every city gets a score from four weighted factors.
- **Explanations you can check.** Each result breaks down how much each factor contributed, so "why does Hanoi rank above Marrakech?" has a reproducible answer.
- **Freshness warnings.** Every volatile fact (prices, weather, safety advisories) stores its source and capture date. Data older than its freshness window is flagged with ⚠ in the UI instead of being shown as current.
- **Compare, save, plan.** Side-by-side city comparison, country and destination profiles, saved trips (Supabase Auth) and a day-by-day itinerary.

---

## Architecture: three separable layers

The LLM is **never** the ranker. It is an optional presentation layer on top of a deterministic engine.

```
┌─────────────────────────────────────────────────────────────┐
│  web/            Presentation: thin views, templates         │
│                  (no business logic)                         │
├─────────────────────────────────────────────────────────────┤
│  intelligence/   Deterministic RecommendationEngine          │
│                  → ScoredCity + FactorContribution + explain()│
│                  Explainer interface (LLM = swappable, off by │
│                  default via NullExplainer)                  │
├─────────────────────────────────────────────────────────────┤
│  destinations/   Data layer: normalized Country/City/Activity│
│                  + provenance-stamped, time-grained          │
│                  MonthlyWeather / CostSnapshot / SafetyAdvisory│
└─────────────────────────────────────────────────────────────┘
```

**Why the LLM is not the ranker.** If a model produced the ranking, the only answer to "why this order?" would be "the model decided". Instead, `RecommendationEngine` scores every city with transparent arithmetic over four weighted factors (budget, safety, climate, interests). The weights live as class attributes, in one auditable place. `ScoredCity.explain()` returns a reproducible breakdown. The `Explainer` can only rephrase that breakdown. It can never change a score.

**Freshness-aware.** Every volatile fact records its `source` and `captured_at`. The engine flags any factor built on data older than its freshness window.

---

## Quick start (local, zero config)

```bash
cd wanderly_app-2
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate          # uses SQLite by default
python manage.py seed_demo        # populates a small demo dataset
python manage.py runserver
```

Visit http://127.0.0.1:8000/.

Run the tests (14 tests covering the engine and the comparison logic):

```bash
python manage.py test
```

---

## Configuration

Security-sensitive and environment-specific values are read from the environment. Sensible local defaults are provided.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | insecure dev key | **Set a real value in production.** |
| `DJANGO_DEBUG` | `True` | `0` in production. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated. |
| `DJANGO_DB_ENGINE` | `sqlite3` | Set `postgresql` to use Postgres. |
| `DJANGO_DB_*` | — | Name/User/Password/Host/Port for Postgres. |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | project defaults | Auth and saved trips. The anon key is public by design. |
| `SUPABASE_SERVICE_KEY` | empty | Backend only. Never commit it. |
| `WANDERLY_EXPLAINER_BACKEND` | `intelligence.explainers.NullExplainer` | Dotted path to the explainer. Swap in a Gemini/Groq subclass to enable LLM prose. It's a config change, not an architecture change. |

---

## SQLite → PostgreSQL

1. Provision Postgres and set `DJANGO_DB_ENGINE=postgresql` plus the `DJANGO_DB_*` variables.
2. Run `python manage.py migrate` against the empty database.
3. Re-run `python manage.py seed_demo`, **or** move existing data with `dumpdata` / `loaddata`.

## Docker

```bash
cd wanderly_app-2
docker compose up --build
```

This brings up Postgres and the app (gunicorn, `DEBUG=0`), runs migrations on start and serves on http://localhost:8000/. Static files are served by WhiteNoise. A `fly.toml` is included for deployment to Fly.io.

---

## Planned next steps (seams already in place)

These are intentionally **not** in this MVP, but the interfaces exist so they can drop in without rework:

- **Review ingestion:** a `ReviewSource` interface plus a `RedditSource` (PRAW), driven by a management command.
- **Aspect-based sentiment:** writes structured sentiment into `intelligence.CityAspectScore`, which the engine's interest factor already consumes.
- **Scheduled refresh:** a GitHub Actions cron that runs the refresh commands. No Celery/Redis needed at academic scale.
