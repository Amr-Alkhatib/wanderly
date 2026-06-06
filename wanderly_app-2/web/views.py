"""
Presentation views.

These are deliberately thin: they pull data from the `destinations` models,
delegate all ranking to `intelligence.engine.RecommendationEngine`, and pass
typed `ScoredCity` objects to the templates. No business logic lives here,
and the LLM `Explainer` is only ever asked to phrase an already-computed
score.
"""

from __future__ import annotations

from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from destinations.models import (
    ActivityCategory,
    BudgetTier,
    City,
    Region,
)
from intelligence.engine import Preferences, RecommendationEngine
from intelligence.comparison import build_comparison
from intelligence.explainers import get_explainer


def _cities_with_related():
    """Base queryset with related rows prefetched to avoid N+1 queries."""
    return City.objects.select_related("country").prefetch_related(
        "cost_snapshots", "safety_advisories", "weather", "aspect_scores", "activities"
    )


def home(request: HttpRequest) -> HttpResponse:
    """Discover page: featured cities plus an engine-ranked 'top picks' list."""
    # The landing page ranks for a representative "default traveller" rather
    # than the fully-neutral anonymous profile: a mid-range budget, an active
    # interest in safety, and the common interest mix. This is still 100%
    # deterministic and explainable -- it just gives the scores a meaningful
    # spread on the homepage instead of clustering everything at ~50.
    discover_persona = Preferences(
        max_daily_budget_eur=80,
        safety_priority=4,
        interests=(
            ActivityCategory.CULTURAL,
            ActivityCategory.FOOD,
            ActivityCategory.NATURE,
        ),
    )
    engine = RecommendationEngine(discover_persona)

    # Featured cards: the curated set, ranked by the engine so the score
    # badge on each card is the real, explainable score (not a static number).
    # Display order is pinned to the mockup (Japan, Portugal, Morocco, Vietnam)
    # while the score shown on each card stays engine-derived.
    _featured_order = ["Japan", "Portugal", "Morocco", "Vietnam"]
    featured_scored = {
        sc.city.country.name: sc
        for sc in engine.rank(_cities_with_related().filter(is_featured=True))
    }
    featured = [featured_scored[name] for name in _featured_order if name in featured_scored]
    # Append any other featured cities not in the explicit order.
    featured += [sc for n, sc in featured_scored.items() if n not in _featured_order]

    # "Top Picks This Month": every city, ranked, minus the ones already
    # surfaced as featured, so the two sections don't duplicate.
    featured_ids = {sc.city.id for sc in featured}
    top_picks = [
        sc for sc in engine.rank(_cities_with_related()) if sc.city.id not in featured_ids
    ][:5]

    # Category tiles mirror the mockup exactly: fixed label, value (for the
    # search filter) and brand colour. Kept here, not in the template, so the
    # palette lives in one auditable place.
    category_tiles = [
        ("Beach", ActivityCategory.BEACH, "#3380b2"),
        ("Mountains", ActivityCategory.MOUNTAINS, "#4d734d"),
        ("Cities", ActivityCategory.CITY, "#1a3c4e"),
        ("Food", ActivityCategory.FOOD, "#f4845f"),
        ("History", ActivityCategory.CULTURAL, "#805933"),
        ("Nature", ActivityCategory.NATURE, "#408c59"),
    ]

    context = {
        "featured": featured,
        "top_picks": top_picks,
        "category_tiles": category_tiles,
        "suggestion_pills": featured + top_picks,
    }
    return render(request, "core/home.html", context)


def search(request: HttpRequest) -> HttpResponse:
    """Explore page: filter by region/budget/safety/category, then rank."""
    qs = _cities_with_related()

    region = request.GET.get("region") or ""
    budget = request.GET.get("budget") or ""
    category = request.GET.get("category") or ""
    query = (request.GET.get("q") or "").strip()

    if region:
        qs = qs.filter(country__region=region)
    if budget:
        qs = qs.filter(budget_tier=budget)
    if category:
        qs = qs.filter(primary_category=category)
    if query:
        qs = qs.filter(name__icontains=query) | qs.filter(country__name__icontains=query)

    # Honour the safety knob by feeding it into the engine's preferences.
    try:
        safety_priority = int(request.GET.get("safety_priority", 3))
    except (TypeError, ValueError):
        safety_priority = 3

    engine = RecommendationEngine(Preferences(safety_priority=safety_priority))
    results = engine.rank(qs.distinct())

    context = {
        "results": results,
        "result_count": len(results),
        "regions": Region.choices,
        "budget_tiers": BudgetTier.choices,
        "categories": ActivityCategory.choices,
        "selected": {
            "region": region,
            "budget": budget,
            "category": category,
            "q": query,
        },
    }
    return render(request, "core/search.html", context)


def destination(request: HttpRequest, slug: str) -> HttpResponse:
    """City profile: full breakdown across cost/safety/climate tabs + 'why'."""
    city = get_object_or_404(_cities_with_related(), slug=slug)

    engine = RecommendationEngine(Preferences.for_anonymous())
    scored = engine.score_city(city)

    explainer = get_explainer()
    why = explainer.explain(scored)

    latest_cost = city.cost_snapshots.order_by("-captured_at").first()
    latest_safety = city.safety_advisories.order_by("-captured_at").first()

    context = {
        "city": city,
        "scored": scored,
        "why": why,
        "latest_cost": latest_cost,
        "latest_safety": latest_safety,
        "weather": city.weather.order_by("month"),
        "activities": city.activities.all(),
    }
    return render(request, "core/destination.html", context)


def compare(request: HttpRequest) -> HttpResponse:
    """
    Side-by-side comparison of up to three engine-scored cities.

    The view stays thin: it resolves the chosen cities, scores each with the
    deterministic engine, and hands them to `build_comparison`, which produces
    the typed rows (with per-cell winners) and verdicts the template renders.
    """
    slugs = [s for s in request.GET.getlist("city") if s][:3]
    engine = RecommendationEngine(Preferences.for_anonymous())

    comparison = None
    if slugs:
        # Preserve the order the user picked the columns in.
        by_slug = {c.slug: c for c in _cities_with_related().filter(slug__in=slugs)}
        ordered = [by_slug[s] for s in slugs if s in by_slug]
        scored = [engine.score_city(c) for c in ordered]
        comparison = build_comparison(scored)

    # Three picker slots, each pre-filled with the slug chosen for that
    # position (empty string when unset) so every dropdown is independent.
    picker_slots = (slugs + ["", "", ""])[:3]

    context = {
        "all_cities": City.objects.select_related("country").order_by("country__name"),
        "comparison": comparison,
        "selected_slugs": slugs,
        "picker_slots": picker_slots,
        # How many "add column" placeholders to show (mockup tops out at 3).
        "open_slots": range(max(0, 3 - len(slugs))),
    }
    return render(request, "core/compare.html", context)
