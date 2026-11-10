# Wanderly

**Discover more. Travel deeper.** Wanderly is a travel recommender that ranks destinations with a transparent score broken down factor by factor, and always explains *why* a city ranks where it does, not just *what* the ranking is.

**Live demo:** https://wanderly.pythonanywhere.com

TUM Project Work (IN8028) · Python · Django · PostgreSQL / SQLite · Supabase Auth · Gemini · Docker

---

## What it does

- **Personal ranking.** Users set budget, safety, climate and interest preferences. Every city gets a score from four weighted factors.
- **Explanations you can check.** Each result breaks down how much each factor contributed, so "why does Hanoi rank above Marrakech?" has a reproducible answer.
- **Freshness warnings.** Every volatile fact (prices, weather, safety advisories) stores its source and capture date. Data older than its freshness window is flagged with ⚠ in the UI instead of being shown as current.
- **Compare, save, plan.** Side-by-side city comparison, country and destination profiles, saved trips (Supabase Auth) and an AI day-by-day itinerary.
- **AI itinerary that never blocks the page.** The page loads instantly and fetches the itinerary separately. Gemini returns schema-validated JSON in about 2 seconds, with a time-capped fallback model and a 24-hour cache.

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

## Frontend

Still Django templates, no build step and no frontend framework. The motion layer is plain JavaScript in `static/js/wanderly/`, and every library is vendored under `static/vendor/` so the site works offline and behind strict hosts.

- **GSAP** (ScrollTrigger, SplitText, Flip, CustomEase) and **Lenis** run on one clock: GSAP's ticker drives smooth scrolling, scroll triggers and the 3D frame.
- **React Bits**, ported to vanilla JS in `bits.js`: SplitText, BlurText, CountUp, ScrollVelocity, TiltedCard, SpotlightCard, Magnet, ClickSpark, DecryptedText, CircularText.
- **Contour field** (`contours.js`): topographic lines from simplex noise and marching squares. On the home hero the cursor raises the summit.
- **Dusk over the map** (home hero): soft coral and lagoon light rises in and drifts, the map glides slowly, and six places light up and send out a ring now and then.
- **The compass** (`compass.js`, three.js): a pocket compass built entirely from code, lit by a small studio baked into the environment. Scrolling takes it apart on camera, and each part is one piece of a score: copper case for budget, enamel bezel for safety, rose dial for climate, blued-steel needle for interests, glass crystal for the explanation. Hold the button to spin the needle; it settles on north and names today's top match.
- **Strata bars** show every score split into its four factor contributions, wherever a score appears.
- **Saving** (`saves.js`): every save button on the site (cards, the destination hero and sidebar) goes through one script. Buttons for the same city stay in step, signed-out visitors are sent to log in and brought back, and a short message confirms each save or says when one failed. The saved trips reach the page as a `data-saved-trips` attribute on `<body>`.
- Visitors who prefer reduced motion get the finished page, phones keep native scrolling, and without WebGL the compass section falls back to a plain list.
- Destination photos are WebP only, in `static/images/dest/w/`, in two sizes (`srcset`). The PNG originals were removed to save disk space; to add a photo, save `<slug>.webp` (1400 px wide) and `<slug>-760.webp` there.

**Keeping it at 60 fps.** The animations are built so the main thread stays free for scrolling:

- The contour field draws in a **Web Worker** (OffscreenCanvas); `contours.js` is both the page script and its own worker.
- **No endless CSS animations.** A single infinite CSS animation in the hero makes the browser recomposite the whole hero 60 times a second (it doubled CPU use at rest). So the hero's dusk is drawn by the contour worker instead: pins in the contour canvas it already redraws, the light in a canvas one sixth the size that the browser stretches (redrawn every 480 ms; the glows are too soft for that to show). Both redraw on the same clock beats, so the hero recomposites at most 12.5 times a second at rest.
- Reveals and the strata bars are **compositor animations** (Web Animations / CSS transitions) started by one IntersectionObserver, not a scroll listener per element.
- three.js is **not loaded during page load**. The compass is built in idle time, step by step, with shaders compiled in the background, and the section only switches from a plain list to the 3D stage once it is ready. At rest it redraws at ~30 fps, it stops when off screen, and it lowers its resolution if frames run long. Devices without a real GPU keep the plain list (`?force3d` overrides this for testing).
- Only the nav and the three hero stat cards use `backdrop-filter`; repeated elements (card badges, pills, buttons) use solid tints instead.
- **Automatic quality.** The page watches its own frame rate. On a device that cannot hold about 45 fps it switches off the continuous extras for the rest of the visit (smooth-scroll easing, drifting contours, the compass's idle sway, photo-glass blur) and keeps everything that answers a click or a scroll. `?quality=high` and `?quality=low` force either mode.
- The results grid uses `content-visibility: auto`, so a page of 100 cards only renders the ones near the screen.

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

Run the tests (27 tests covering the engine, the comparison logic, the itinerary and the destination page):

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
| `GEMINI_API_KEY` | — | Needed for the AI itinerary. Never commit it. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Primary itinerary model. Change it here when Google retires a model. |
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
