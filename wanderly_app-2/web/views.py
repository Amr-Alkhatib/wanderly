"""
Presentation views.

These are deliberately thin: they pull data from the `destinations` models,
delegate all ranking to `intelligence.engine.RecommendationEngine`, and pass
typed `ScoredCity` objects to the templates. No business logic lives here,
and the LLM `Explainer` is only ever asked to phrase an already-computed
score.
"""

from __future__ import annotations

import json

from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from destinations.models import (
    ActivityCategory,
    BudgetTier,
    City,
    Country,
    Region,
)
from intelligence.engine import Preferences, RecommendationEngine
from intelligence.comparison import build_comparison
from intelligence.explainers import get_explainer


_NEIGHBORHOODS: dict[str, list[str]] = {
    "tokyo":             ["Shibuya", "Shinjuku", "Asakusa", "Harajuku"],
    "osaka":             ["Dotonbori", "Namba", "Umeda", "Shinsekai"],
    "kyoto":             ["Gion", "Arashiyama", "Higashiyama", "Fushimi"],
    "lisbon":            ["Alfama", "Bairro Alto", "Belém", "Chiado"],
    "porto":             ["Ribeira", "Boavista", "Bonfim", "Foz"],
    "algarve":           ["Lagos", "Albufeira", "Faro", "Portimão"],
    "marrakech":         ["Medina", "Gueliz", "Mellah", "Palmeraie"],
    "fes":               ["Fes el-Bali", "Fes el-Jdid", "Ville Nouvelle"],
    "chefchaouen":       ["Blue Medina", "Kasbah Quarter", "Ras el-Maa"],
    "hanoi":             ["Old Quarter", "Hoan Kiem", "Ba Dinh", "Tay Ho"],
    "ho-chi-minh-city":  ["Bến Thành", "Bùi Viện", "District 3", "Thu Thiêm"],
    "hoi-an":            ["Ancient Town", "An Hội", "Cẩm Nam"],
    "tbilisi":           ["Old Tbilisi", "Rustaveli", "Vake", "Mtatsminda"],
    "batumi":            ["Old Batumi", "New Boulevard", "Makhinjauri"],
    "kazbegi":           ["Stepantsminda", "Gergeti", "Truso Valley"],
    "colombo":           ["Fort", "Pettah", "Colombo 3", "Bambalapitiya"],
    "galle":             ["Galle Fort", "Unawatuna", "Hikkaduwa"],
    "kandy":             ["City Centre", "Peradeniya", "Katugastota"],
    "tirana":            ["Blloku", "Old Bazaar", "Kombinat"],
    "saranda":           ["Old Town", "Waterfront", "Ksamil"],
    "berat":             ["Mangalem", "Gorica", "Kalaja"],
    "skopje":            ["Old Bazaar", "City Centre", "Karpoš"],
    "ohrid":             ["Old Town", "Kaneo", "Lakeside"],
    "pristina":          ["City Centre", "Dragodan", "Ulpiana"],
    "prizren":           ["Old Town", "Shadërvan", "Fortress Quarter"],
    "kerala":            ["Kochi", "Thiruvananthapuram", "Kozhikode"],
    "goa":               ["North Goa", "South Goa", "Panjim"],
    "rajasthan":         ["Jaipur", "Jodhpur", "Udaipur", "Jaisalmer"],
}

_TRANSPORT: dict[str, list[str]] = {
    "tokyo":             ["Metro (13 lines)", "Shinkansen", "City Bus", "IC Card (Suica)"],
    "osaka":             ["Metro", "JR Loop Line", "City Bus", "IC Card (ICOCA)"],
    "kyoto":             ["City Bus (main)", "Randen Tram", "Bicycle friendly"],
    "lisbon":            ["Metro (4 lines)", "Iconic Tram 28", "Carris Bus", "Uber / Bolt"],
    "porto":             ["Metro (6 lines)", "Historic Tram", "STCP Bus"],
    "algarve":           ["EVA Bus", "Car hire recommended", "Taxi"],
    "marrakech":         ["Caleche (horse carriage)", "City Bus", "Petit Taxi"],
    "fes":               ["Petit Taxi", "City Bus", "Walkable medina"],
    "chefchaouen":       ["CTM Bus to Fes/Tangier", "Grand Taxi", "Walkable"],
    "hanoi":             ["City Bus", "Grab / Gojek", "Taxi"],
    "ho-chi-minh-city":  ["Grab / Gojek", "City Bus", "Taxi"],
    "hoi-an":            ["Bicycle (most common)", "Motorbike hire", "Taxi"],
    "tbilisi":           ["Metro (2 lines)", "Marshrutka", "Bolt / Yandex"],
    "batumi":            ["City Bus", "Bolt / Yandex", "Walkable promenade"],
    "kazbegi":           ["Marshrutka from Tbilisi", "4WD taxi", "Hiking trails"],
    "colombo":           ["CTB Bus", "Tuk-Tuk", "PickMe / Uber"],
    "galle":             ["Train (scenic)", "Bus", "Tuk-Tuk"],
    "kandy":             ["Scenic train", "Bus", "Tuk-Tuk"],
    "tirana":            ["City Bus", "Taxi", "Lime Scooter"],
    "saranda":           ["Taxi", "Scooter hire", "Walkable seafront"],
    "berat":             ["Taxi", "Minibus from Tirana", "Walkable"],
    "skopje":            ["City Bus", "Taxi", "Bike lanes"],
    "ohrid":             ["Taxi", "Lake ferry", "Walkable old town"],
    "pristina":          ["City Bus", "Taxi", "Walkable centre"],
    "prizren":           ["Taxi", "Walkable", "Bus to Pristina"],
    "kerala":            ["Train (coastal)", "KSRTC Bus", "Auto-rickshaw"],
    "goa":               ["Scooter hire", "Goa Miles app", "Kadamba Bus"],
    "rajasthan":         ["Train (intercity)", "Camel ride (local)", "Taxi"],
}

_DEFAULT_TRANSPORT = ["Local Bus", "Taxi / Rideshare", "Walkable city centre"]

_EMERGENCY: dict[str, dict[str, str]] = {
    "tokyo":            {"Police": "110", "Ambulance / Fire": "119", "English hotline": "03-3501-0110"},
    "osaka":            {"Police": "110", "Ambulance / Fire": "119", "English hotline": "06-6942-1119"},
    "kyoto":            {"Police": "110", "Ambulance / Fire": "119"},
    "lisbon":           {"Police": "112", "Ambulance": "112", "Fire": "112", "Tourist Helpline": "21 342 1634"},
    "porto":            {"Police": "112", "Ambulance": "112", "Fire": "112"},
    "algarve":          {"Police": "112", "Ambulance": "112", "Fire": "112"},
    "marrakech":        {"Police": "19", "Ambulance": "15", "Fire": "15", "Tourist Helpline": "0524-38-46-01"},
    "fes":              {"Police": "19", "Ambulance": "15", "Fire": "15"},
    "chefchaouen":      {"Police": "19", "Ambulance": "15", "Fire": "15"},
    "hanoi":            {"Police": "113", "Ambulance": "115", "Fire": "114"},
    "ho-chi-minh-city": {"Police": "113", "Ambulance": "115", "Fire": "114"},
    "hoi-an":           {"Police": "113", "Ambulance": "115", "Fire": "114"},
    "tbilisi":          {"Police": "112", "Ambulance": "112", "Fire": "112"},
    "batumi":           {"Police": "112", "Ambulance": "112", "Fire": "112"},
    "kazbegi":          {"Police": "112", "Ambulance": "112", "Fire": "112"},
    "colombo":          {"Police": "119", "Ambulance": "110", "Fire": "111"},
    "galle":            {"Police": "119", "Ambulance": "110", "Fire": "111"},
    "kandy":            {"Police": "119", "Ambulance": "110", "Fire": "111"},
    "tirana":           {"Police": "129", "Ambulance": "127", "Fire": "128"},
    "saranda":          {"Police": "129", "Ambulance": "127", "Fire": "128"},
    "berat":            {"Police": "129", "Ambulance": "127", "Fire": "128"},
    "skopje":           {"Police": "192", "Ambulance": "194", "Fire": "193"},
    "ohrid":            {"Police": "192", "Ambulance": "194", "Fire": "193"},
    "pristina":         {"Police": "192", "Ambulance": "194", "Fire": "193"},
    "prizren":          {"Police": "192", "Ambulance": "194", "Fire": "193"},
    "kerala":           {"Police": "100", "Ambulance": "108", "Fire": "101"},
    "goa":              {"Police": "100", "Ambulance": "108", "Fire": "101"},
    "rajasthan":        {"Police": "100", "Ambulance": "108", "Fire": "101"},
}
_DEFAULT_EMERGENCY = {"Police": "112", "Ambulance": "112", "Fire": "112"}


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
    featured = featured[:8]

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

    from web.views_saved import get_saved_trip_map
    saved_trip_map = get_saved_trip_map(request.user)

    context = {
        "saved_trip_map_json": json.dumps(saved_trip_map),
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

    from web.views_saved import get_saved_trip_map
    saved_trip_map = get_saved_trip_map(request.user)

    context = {
        "saved_trip_map_json": json.dumps(saved_trip_map),
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


def country_profile(request: HttpRequest, slug: str) -> HttpResponse:
    """Country overview page: mirrors the original destination layout with sidebar city links."""
    country = get_object_or_404(Country, slug=slug)
    cities = (
        City.objects.filter(country=country)
        .select_related("country")
        .prefetch_related("cost_snapshots", "safety_advisories", "weather")
        .order_by("name")
    )
    anchor = cities.filter(is_featured=True).first() or cities.first()
    latest_cost = anchor.cost_snapshots.order_by("-captured_at").first() if anchor else None
    latest_safety = anchor.safety_advisories.order_by("-captured_at").first() if anchor else None
    weather = anchor.weather.order_by("month") if anchor else []

    engine = RecommendationEngine(Preferences.for_anonymous())
    scored = engine.score_city(anchor) if anchor else None

    context = {
        "country": country,
        "cities": cities,
        "anchor": anchor,
        "scored": scored,
        "latest_cost": latest_cost,
        "latest_safety": latest_safety,
        "weather": weather,
    }
    return render(request, "core/country.html", context)


def destination(request: HttpRequest, slug: str) -> HttpResponse:
    """City profile: full breakdown across cost/safety/climate tabs + 'why'."""
    city = get_object_or_404(_cities_with_related(), slug=slug)

    engine = RecommendationEngine(Preferences.for_anonymous())
    scored = engine.score_city(city)

    explainer = get_explainer()
    why = explainer.explain(scored)

    latest_cost = city.cost_snapshots.order_by("-captured_at").first()
    latest_safety = city.safety_advisories.order_by("-captured_at").first()

    from web.views_saved import get_saved_trip_map
    saved_trip_map = get_saved_trip_map(request.user)

    context = {
        "saved_trip_map_json": json.dumps(saved_trip_map),
        "city": city,
        "scored": scored,
        "why": why,
        "latest_cost": latest_cost,
        "latest_safety": latest_safety,
        "weather": city.weather.order_by("month"),
        "activities": city.activities.all(),
        "cities_in_country": City.objects.filter(country=city.country).exclude(slug=slug).select_related("country"),
        "neighborhoods": _NEIGHBORHOODS.get(slug, []),
        "transport": _TRANSPORT.get(slug, _DEFAULT_TRANSPORT),
        "emergency": _EMERGENCY.get(slug, _DEFAULT_EMERGENCY),
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
