"""
The deterministic recommendation engine.

This module is the heart of Wanderly's value proposition and the reason the
LLM is *not* the ranker. Every score a user sees is produced here, by
transparent arithmetic over verified data, and carries a breakdown of
exactly which factors contributed how much.

The contract:

    engine = RecommendationEngine(preferences)
    results: list[ScoredCity] = engine.rank(cities)
    results[0].explain()   # -> human-readable, deterministic justification

`ScoredCity` and `FactorContribution` are plain dataclasses, deliberately
decoupled from the ORM, so the engine is trivially unit-testable and the
LLM presentation layer consumes a stable, typed surface.

A note on staleness: if a city's scoring relies on data older than its
freshness policy, the contributing factor is marked `is_stale` and the
final `ScoredCity` exposes `has_stale_inputs`, so the UI can be honest
about confidence rather than presenting an aging number as fresh truth.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from destinations.models import (
    ActivityCategory,
    BudgetTier,
    City,
    CostSnapshot,
    MonthlyWeather,
    SafetyAdvisory,
)


# --- Inputs ------------------------------------------------------------------


@dataclass(frozen=True)
class Preferences:
    """
    A snapshot of what a traveller wants. Decoupled from the ORM so the
    engine can be exercised with hand-built inputs in tests, and so an
    anonymous visitor (no UserProfile row) can still get recommendations.
    """

    max_daily_budget_eur: int = 100
    travel_month: int | None = None  # 1-12, or None for "flexible"
    preferred_climate: str = ""  # a MonthlyWeather.Climate value, or ""
    safety_priority: int = 3  # 1 (ignore) .. 5 (critical)
    interests: tuple[str, ...] = ()  # ActivityCategory values

    @classmethod
    def for_anonymous(cls) -> "Preferences":
        """Neutral defaults so the homepage can rank without a logged-in user."""
        return cls()


# --- Outputs -----------------------------------------------------------------


@dataclass(frozen=True)
class FactorContribution:
    """
    One named component of a city's score.

    `points` is the contribution to the final 0-100 score (weight * raw),
    already weighted. `detail` is a short, deterministic sentence so the
    UI -- and any LLM explainer -- can state the 'why' without inventing it.
    """

    name: str
    raw_score: float  # 0-100 before weighting
    weight: float  # 0-1; the factor weights sum to 1
    points: float  # raw_score * weight, the actual contribution
    detail: str
    is_stale: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "raw_score": round(self.raw_score, 1),
            "weight": round(self.weight, 2),
            "points": round(self.points, 1),
            "detail": self.detail,
            "is_stale": self.is_stale,
        }


@dataclass
class ScoredCity:
    """
    A city together with its overall score and the factor breakdown that
    produced it. Sortable by score (descending) for ranking.
    """

    city: City
    score: int
    factors: list[FactorContribution] = field(default_factory=list)

    @property
    def has_stale_inputs(self) -> bool:
        """True if any contributing factor used stale data."""
        return any(f.is_stale for f in self.factors)

    def explain(self) -> str:
        """
        Produce a deterministic, human-readable justification of the score.

        This is intentionally plain text generated from the factor table --
        no model, no randomness. A tutor asking "why does this city rank
        here?" gets a concrete, reproducible answer every time.
        """
        lines = [f"{self.city} scored {self.score}/100. Breakdown:"]
        for factor in sorted(self.factors, key=lambda f: f.points, reverse=True):
            stale = " (based on stale data)" if factor.is_stale else ""
            lines.append(
                f"  • {factor.name}: {factor.points:.0f} pts "
                f"({factor.raw_score:.0f}/100 × {factor.weight:.0%}) — {factor.detail}{stale}"
            )
        if self.has_stale_inputs:
            lines.append(
                "  Note: some inputs are older than their freshness window; "
                "treat this score as indicative."
            )
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        return {
            "city": str(self.city),
            "score": self.score,
            "has_stale_inputs": self.has_stale_inputs,
            "factors": [f.as_dict() for f in self.factors],
        }


# --- The engine --------------------------------------------------------------


class RecommendationEngine:
    """
    Ranks cities for a given set of preferences using fixed, declared
    factor weights. Pure, deterministic, and fully explainable.

    The four factors -- budget, safety, climate, interests -- mirror the
    knobs presented on the "AI realistic recommendations" screen. Their
    weights are class attributes so they are auditable in one place and can
    be tuned without touching scoring logic.
    """

    #: Declared factor weights. Must sum to ~1.0 (asserted at construction).
    WEIGHT_BUDGET = 0.30
    WEIGHT_SAFETY = 0.25
    WEIGHT_CLIMATE = 0.20
    WEIGHT_INTERESTS = 0.25

    def __init__(self, preferences: Preferences | None = None) -> None:
        self.preferences = preferences or Preferences.for_anonymous()
        total = (
            self.WEIGHT_BUDGET
            + self.WEIGHT_SAFETY
            + self.WEIGHT_CLIMATE
            + self.WEIGHT_INTERESTS
        )
        assert abs(total - 1.0) < 1e-6, f"Factor weights must sum to 1.0 (got {total})."

    # -- public API --

    def rank(self, cities: Iterable[City]) -> list[ScoredCity]:
        """Score every city and return them sorted best-first.

        Ties are broken by city name so ordering is stable and reproducible.
        """
        scored = [self.score_city(c) for c in cities]
        scored.sort(key=lambda sc: (-sc.score, sc.city.name))
        return scored

    def score_city(self, city: City) -> ScoredCity:
        """Compute the full breakdown and overall score for one city."""
        factors = [
            self._budget_factor(city),
            self._safety_factor(city),
            self._climate_factor(city),
            self._interest_factor(city),
        ]
        overall = round(sum(f.points for f in factors))
        # Clamp into [0, 100] defensively.
        overall = max(0, min(100, overall))
        return ScoredCity(city=city, score=overall, factors=factors)

    # -- individual factors --

    def _budget_factor(self, city: City) -> FactorContribution:
        """Reward cities whose daily budget cost fits the traveller's cap."""
        snapshot: CostSnapshot | None = city.cost_snapshots.order_by("-captured_at").first()
        cap = self.preferences.max_daily_budget_eur

        if snapshot is None:
            return FactorContribution(
                name="Budget",
                raw_score=50.0,
                weight=self.WEIGHT_BUDGET,
                points=50.0 * self.WEIGHT_BUDGET,
                detail="No cost data on file; assumed neutral.",
                is_stale=True,
            )

        daily = snapshot.daily_budget_eur
        if daily <= cap:
            # Comfortably affordable -> near-full marks, with a small bonus
            # for being well under budget.
            headroom = (cap - daily) / cap if cap else 0
            raw = min(100.0, 80.0 + headroom * 20.0)
            detail = f"Daily budget ~€{daily} fits within your €{cap}/day cap."
        else:
            # Over budget -> decays with how far over.
            overshoot = (daily - cap) / cap if cap else 1
            raw = max(0.0, 60.0 - overshoot * 60.0)
            detail = f"Daily budget ~€{daily} exceeds your €{cap}/day cap."

        return FactorContribution(
            name="Budget",
            raw_score=raw,
            weight=self.WEIGHT_BUDGET,
            points=raw * self.WEIGHT_BUDGET,
            detail=detail,
            is_stale=snapshot.is_stale,
        )

    def _safety_factor(self, city: City) -> FactorContribution:
        """Use the latest advisory, scaled by how much the user cares."""
        advisory: SafetyAdvisory | None = city.safety_advisories.order_by("-captured_at").first()
        # Map priority 1..5 to an emphasis multiplier on the raw safety score.
        priority = max(1, min(5, self.preferences.safety_priority))

        if advisory is None:
            return FactorContribution(
                name="Safety",
                raw_score=50.0,
                weight=self.WEIGHT_SAFETY,
                points=50.0 * self.WEIGHT_SAFETY,
                detail="No safety advisory on file; assumed neutral.",
                is_stale=True,
            )

        # When the user cares a lot (priority 5), an unsafe city is punished
        # harder and a safe one rewarded more; at priority 1 we pull toward
        # a neutral 50 so safety barely moves the ranking.
        emphasis = (priority - 1) / 4  # 0 .. 1
        raw = 50.0 + (advisory.safety_score - 50.0) * (0.4 + 0.6 * emphasis)
        raw = max(0.0, min(100.0, raw))
        detail = (
            f"Safety {advisory.safety_score}/100 "
            f"({advisory.get_level_display()}), weighted by your priority {priority}/5."
        )
        return FactorContribution(
            name="Safety",
            raw_score=raw,
            weight=self.WEIGHT_SAFETY,
            points=raw * self.WEIGHT_SAFETY,
            detail=detail,
            is_stale=advisory.is_stale,
        )

    def _climate_factor(self, city: City) -> FactorContribution:
        """Match the travel-month climate against the stated preference."""
        month = self.preferences.travel_month
        preferred = self.preferences.preferred_climate

        # No month chosen and no climate preference -> neutral, full marks
        # withheld but not penalised.
        if month is None and not preferred:
            return FactorContribution(
                name="Climate",
                raw_score=70.0,
                weight=self.WEIGHT_CLIMATE,
                points=70.0 * self.WEIGHT_CLIMATE,
                detail="Flexible dates and climate; treated favourably.",
            )

        weather: MonthlyWeather | None = None
        if month is not None:
            weather = city.weather.filter(month=month).first()

        if weather is None:
            return FactorContribution(
                name="Climate",
                raw_score=55.0,
                weight=self.WEIGHT_CLIMATE,
                points=55.0 * self.WEIGHT_CLIMATE,
                detail="No climate record for the chosen month; assumed neutral.",
                is_stale=True,
            )

        raw = 60.0
        bits: list[str] = []
        if weather.is_recommended_month:
            raw += 25.0
            bits.append("a recommended month to visit")
        if preferred and weather.climate_type == preferred:
            raw += 15.0
            bits.append(f"matches your preferred climate ({weather.get_climate_type_display()})")
        elif preferred:
            raw -= 10.0
            bits.append(f"climate is {weather.get_climate_type_display()}, not your preference")
        raw = max(0.0, min(100.0, raw))

        detail = (
            f"In month {month}: {weather.avg_high_c}°C high"
            + (", " + "; ".join(bits) if bits else "")
            + "."
        )
        return FactorContribution(
            name="Climate",
            raw_score=raw,
            weight=self.WEIGHT_CLIMATE,
            points=raw * self.WEIGHT_CLIMATE,
            detail=detail,
            is_stale=weather.is_stale,
        )

    def _interest_factor(self, city: City) -> FactorContribution:
        """
        Reward cities whose aspect scores align with the user's interests.

        Uses ABSA-derived `CityAspectScore` rows where available, and falls
        back to the city's primary category when no aspect data exists.
        """
        interests: Sequence[str] = self.preferences.interests
        if not interests:
            # No stated interests -> lean on the editorial primary category
            # as a mild signal; never the dominant factor.
            return FactorContribution(
                name="Interests",
                raw_score=65.0,
                weight=self.WEIGHT_INTERESTS,
                points=65.0 * self.WEIGHT_INTERESTS,
                detail="No interests specified; scored on general appeal.",
            )

        aspect_rows = {a.aspect: a for a in city.aspect_scores.all()}
        matched: list[str] = []
        stale = False
        total = 0.0
        for interest in interests:
            row = aspect_rows.get(interest)
            if row is not None:
                total += row.score
                matched.append(f"{interest} {row.score}/100")
            elif city.primary_category == interest:
                total += 75.0  # primary-category fallback
                matched.append(f"{interest} (primary focus)")
            else:
                total += 40.0  # interest present but city is weak on it
        raw = total / len(interests)

        detail = (
            "Interest match — " + "; ".join(matched) + "."
            if matched
            else "No strong match for your interests."
        )
        return FactorContribution(
            name="Interests",
            raw_score=raw,
            weight=self.WEIGHT_INTERESTS,
            points=raw * self.WEIGHT_INTERESTS,
            detail=detail,
            is_stale=stale,
        )
