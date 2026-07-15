# Merge: wanderly2 features → wanderly (deployed repo)

## What was merged in (from wanderly2)
- **Gemini API explainer** — `intelligence/explainers.py`: `GeminiExplainer`
  (gemini-2.5-flash) + error logging. Enable by setting Fly secrets:
  `WANDERLY_EXPLAINER_BACKEND=intelligence.explainers.GeminiExplainer` and
  `GEMINI_API_KEY=<key>`. Default stays NullExplainer (no key, no network).
- **Cities database** — `destinations/management/commands/seed_real.py`
  (100 cities, real Open-Meteo weather) and `fetch_images.py` (Pexels).
- **New UI** — redesigned destination page (breadcrumbs, safety/cost stats,
  neighborhoods, transport, emergency numbers), new `country/<slug>/` page
  (`country_profile` view + `templates/core/country.html`), category tiles
  with images, 129 destination photos, `styles.css` from wanderly2.

## What was preserved from wanderly (deployed)
- Working **save/unsave button** on home, search and destination pages
  (CSRF meta tag, saved-map hydration, `/api/trips/...` Supabase calls) —
  re-embedded into the new wanderly2 templates.
- **Saved page** (`/saved/`, `views_saved.py`) and its nav link.
- `fly.toml`, `settings.py`, Supabase auth/trips, requirements pins
  (+ `google-genai`).

## Verified locally
`manage.py check`, migrations, `seed_real --skip-weather` (100 cities),
14/14 tests pass, all pages return 200, save buttons + JS render on
home/search/destination, `collectstatic` OK, GeminiExplainer loads from config.

## Deploy checklist
1. `fly deploy` (release command runs migrations automatically).
2. If not yet done in prod DB: `fly ssh console -C "python manage.py seed_real"`.
3. Optional Gemini prose: `fly secrets set GEMINI_API_KEY=... WANDERLY_EXPLAINER_BACKEND=intelligence.explainers.GeminiExplainer`.
