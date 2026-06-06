# Discover page — Figma implementation notes

This draft brings the **Discover / Home** screen in line with the Figma
"Wanderly — final mockup" (frame `01 · Home / Discover`, node `1:2`).

## What changed
- **`templates/base.html`** — navbar + footer rebuilt to the mockup (navy
  `#1a3c4e`, orange `#f4845f`, logo + wordmark, white nav search, "Plan a
  Trip" CTA, "L" avatar).
- **`templates/core/home.html`** — Discover layout: hero (logo, headline,
  search, suggestion pills), Featured cards, "Top Picks This Month", and the
  "Plan by Category" colour tiles.
- **`static/css/styles.css`** — design tokens taken verbatim from Figma; new
  navbar/hero/discover styles; downstream pages (search/destination/compare)
  retuned to the same palette.
- **`destinations/models.py`** — added presentation-only `City.image` and
  `City.card_pill` fields, plus `image_file` / `safety_label` helpers. The
  engine never reads these; they are display sugar only.
  Migration: `destinations/migrations/0002_city_card_pill_city_image.py`.
- **`destinations/management/commands/seed_demo.py`** — extended to the 10
  cities shown on the mockup (added Georgia, Sri Lanka, North Macedonia,
  Kosovo) with image filenames and editorial card pills.
- **`web/views.py`** — `home()` now ranks for a representative *default
  traveller* persona (mid budget, safety-conscious, common interests) instead
  of the fully-neutral anonymous profile. This is still 100% deterministic and
  explainable; it just gives the homepage score badges a meaningful spread
  rather than clustering them. Featured display order is pinned to the mockup
  while each card's score stays engine-derived.

## Images
Card/thumbnail images load from `static/images/dest/<slug>.png`
(e.g. `japan.png`, `albania.png`) plus `wanderly-hero.png`. This repo ships
**brand-tinted placeholder gradients** so the page renders offline. Drop the
real Figma exports into that folder using the same filenames — no code change
needed. `City.image` can override the filename per city if you prefer.

## Architecture preserved
The LLM is still **not** the ranker. Score badges come from
`RecommendationEngine`; the `ⓘ` tooltip on each badge is the engine's own
`ScoredCity.explain()` output. The `Explainer` layer is untouched.

## Run it
    python manage.py migrate
    python manage.py seed_demo
    python manage.py runserver

---

# Comparison page — Figma implementation notes (frame `10 · Comparison`, node 1:889)

UI-first build of the side-by-side Comparison page.

## What changed
- **`intelligence/comparison.py`** (new) — `build_comparison(scored)` turns
  engine-scored cities into typed `ComparisonRow`/`ComparisonCell` objects.
  Per-cell winners are computed **deterministically** (lower-is-better for
  budget, higher-is-better for safety/aspects, no winner for textual rows),
  so the green/blue highlighting and the verdict card can never contradict
  the table. Rows with no model field yet (English Level, Nightlife, and
  Food/Nature when a city lacks an ABSA score) use clearly-named
  `_placeholder_*` helpers and are tagged `is_estimated` → shown as `EST.`
- **`web/views.py`** — `compare()` resolves the chosen cities (order
  preserved), scores them with the engine, and hands them to
  `build_comparison`. Adds independent picker slots and "+ Add country" slots.
- **`templates/core/compare.html`** — full rebuild to the mockup: title +
  "Add destination", navy/teal column headers, navy header bar, alternating
  white/cream rows with green-winner / blue-other value chips, navy verdict
  card, picker with one dropdown per column.
- **`static/css/styles.css`** — new `.cmp-*` block matching the Figma tokens
  (winner `#e0f5e5`/`#34a853`, other `#e0eafb`, header navy `#1a3c4e`,
  second column teal `#295960`). CSS grid scales to 2 *or* 3 columns via
  `--cols`.
- **`intelligence/tests_comparison.py`** (new) — 5 tests covering winner
  logic, textual-row no-winner, verdict/row consistency, and full population.

## Honest gaps to revisit with the backend
- **English Level / Nightlife**: no source field yet → placeholder, tagged EST.
- **Visa**: cell truncates `country.visa_summary`; add a short visa field
  (e.g. "Visa Free 90d") for the clean mockup string. Row currently has no
  winner (textual).
- **Currency**: shows € (models store EUR); mockup shows $. One-line change.

## Try it
    /compare/?city=tokyo&city=lisbon
    /compare/?city=tokyo&city=lisbon&city=tbilisi   (3 columns)
