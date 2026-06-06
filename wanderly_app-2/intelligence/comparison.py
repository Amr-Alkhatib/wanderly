"""
The comparison builder.

This module turns a set of engine-scored cities into a structured,
side-by-side comparison table for the Comparison page. It is deliberately a
*presentation-layer* concern, sitting on top of the deterministic engine and
the verified `destinations` data -- it never ranks the cities itself, it
only lays their already-computed facts next to each other.

Design notes
------------
* **Typed, not stringly.** Each row is a `ComparisonRow` of `ComparisonCell`s.
  A cell carries both the *display* string and an optional *comparable*
  numeric value, so the winner of each row can be decided deterministically
  rather than by parsing text in the template.

* **Winners are computed, never hardcoded.** For every row we mark the cell(s)
  with the best comparable value as `is_winner`. The template then paints the
  winning cell green and the rest blue -- exactly mirroring the Figma frame,
  but driven by data so it stays honest if the underlying numbers change.

* **Placeholders are isolated and labelled.** A few rows in the mockup
  (English level, nightlife) have no backing model field yet. Their values
  are produced by the clearly-named `_PLACEHOLDER_*` helpers below and tagged
  `is_estimated=True`, so when the real data source lands we delete one helper
  and wire the field -- the row, ordering and UI stay put. This keeps the
  UI-first pass looking complete without pretending the data is verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from destinations.models import ActivityCategory, City
from intelligence.engine import ScoredCity


# --- Cell / row data types ---------------------------------------------------


@dataclass(frozen=True)
class ComparisonCell:
    """One city's value for one comparison row."""

    display: str               # what the user sees, e.g. "$65–95/day"
    sort_value: float | None = None   # comparable number for winner logic
    is_winner: bool = False    # set by the row once all cells are known
    is_estimated: bool = False # True when value is a placeholder, not verified

    def with_winner(self, won: bool) -> "ComparisonCell":
        return ComparisonCell(
            display=self.display,
            sort_value=self.sort_value,
            is_winner=won,
            is_estimated=self.is_estimated,
        )


@dataclass
class ComparisonRow:
    """A labelled metric across all compared cities."""

    label: str
    cells: list[ComparisonCell]
    #: "high" means a larger sort_value wins; "low" means smaller wins;
    #: "none" disables winner highlighting (e.g. purely textual rows).
    better: str = "high"

    def decided(self) -> "ComparisonRow":
        """Return a copy with `is_winner` flags resolved deterministically."""
        comparables = [c.sort_value for c in self.cells if c.sort_value is not None]
        if self.better == "none" or len(comparables) < 2:
            return self
        target = max(comparables) if self.better == "high" else min(comparables)
        new_cells = [
            c.with_winner(c.sort_value is not None and c.sort_value == target)
            for c in self.cells
        ]
        return ComparisonRow(label=self.label, cells=new_cells, better=self.better)


@dataclass
class ComparisonResult:
    """Everything the Comparison template needs."""

    scored: list[ScoredCity]
    rows: list[ComparisonRow] = field(default_factory=list)
    verdicts: list[tuple[str, str]] = field(default_factory=list)  # (label, winner)


# --- Placeholder helpers (UI-first; replace when a real field exists) --------


def _placeholder_english_level(city: City) -> tuple[str, float]:
    """
    Rough English-proficiency proxy until a real field exists. Europe and
    well-touristed Asian hubs trend higher; everything else "Moderate".
    Returns (display, sort_value 0-100). Tagged estimated in the cell.
    """
    name = city.country.name
    high = {"Portugal", "Kosovo", "North Macedonia"}
    limited = {"Japan", "Morocco", "Vietnam"}
    if name in high:
        return "Moderate", 60.0
    if name in limited:
        return "Limited", 35.0
    return "Basic", 45.0


def _placeholder_nightlife(city: City) -> tuple[str, float]:
    """Nightlife star proxy until backed by data. 0-100 -> 1-5 stars."""
    base = {
        ActivityCategory.CITY: 80.0,
        ActivityCategory.CULTURAL: 70.0,
        ActivityCategory.BEACH: 75.0,
        ActivityCategory.FOOD: 72.0,
    }.get(city.primary_category, 55.0)
    return _stars(base), base


def _placeholder_aspect(city: City, aspect: str) -> tuple[str, float]:
    """
    Fallback star value for an ABSA aspect a city has no score for yet.
    Derived from the city's primary category so it is plausible and stable,
    and tagged estimated by the caller. Returns (stars, sort_value).
    """
    affinity = {
        ActivityCategory.NATURE: {
            ActivityCategory.NATURE: 88.0, ActivityCategory.BEACH: 78.0,
            ActivityCategory.MOUNTAINS: 90.0, ActivityCategory.ADVENTURE: 80.0,
        },
        ActivityCategory.FOOD: {
            ActivityCategory.FOOD: 90.0, ActivityCategory.CITY: 76.0,
            ActivityCategory.CULTURAL: 74.0,
        },
    }.get(aspect, {})
    val = affinity.get(city.primary_category, 60.0)
    return _stars(val), val


# --- Formatting helpers ------------------------------------------------------


def _stars(score_0_100: float) -> str:
    """Render a 0-100 score as five ★/☆ glyphs."""
    filled = max(1, min(5, round(score_0_100 / 20)))
    return "★" * filled + "☆" * (5 - filled)


_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _best_months(city: City) -> tuple[str, float]:
    """Summarise recommended months as a compact range string + a count."""
    months = sorted(
        w.month for w in city.weather.all() if w.is_recommended_month
    )
    if not months:
        return "Flexible", 0.0
    # Compress consecutive months into "Mar–May" style spans.
    spans: list[str] = []
    start = prev = months[0]
    for m in months[1:] + [None]:  # sentinel to flush the final span
        if m is not None and m == prev + 1:
            prev = m
            continue
        spans.append(_MONTHS[start] if start == prev else f"{_MONTHS[start]}–{_MONTHS[prev]}")
        if m is not None:
            start = prev = m
    return ", ".join(spans), float(len(months))


def _aspect(city: City, aspect: str) -> float:
    """Latest ABSA aspect score for a city, or 0 when absent."""
    row = next((a for a in city.aspect_scores.all() if a.aspect == aspect), None)
    return float(row.score) if row else 0.0


# --- The builder -------------------------------------------------------------


def build_comparison(scored: Sequence[ScoredCity]) -> ComparisonResult:
    """
    Assemble the full comparison table for the given scored cities.

    Each row pulls from verified data where it exists (cost, safety, weather,
    visa, ABSA aspects) and from a clearly-marked placeholder otherwise. Row
    winners are then resolved deterministically.
    """
    cities = [sc.city for sc in scored]

    def row(label: str, fn: Callable[[City], ComparisonCell], better: str = "high") -> ComparisonRow:
        return ComparisonRow(label=label, cells=[fn(c) for c in cities], better=better).decided()

    rows: list[ComparisonRow] = []

    # Daily budget -- lower is better. Display the budget-traveller band.
    def budget_cell(c: City) -> ComparisonCell:
        cost = c.cost_snapshots.order_by("-captured_at").first()
        if not cost:
            return ComparisonCell("—")
        lo, hi = cost.daily_budget_eur, cost.daily_midrange_eur
        return ComparisonCell(f"€{lo}–{hi}/day", sort_value=float(lo))

    rows.append(row("Daily Budget", budget_cell, better="low"))

    # Safety score -- higher is better.
    def safety_cell(c: City) -> ComparisonCell:
        adv = c.safety_advisories.order_by("-captured_at").first()
        if not adv:
            return ComparisonCell("—")
        return ComparisonCell(f"{adv.safety_score} / 100", sort_value=float(adv.safety_score))

    rows.append(row("Safety Score", safety_cell, better="high"))

    # Best months -- more recommended months is (mildly) better.
    def months_cell(c: City) -> ComparisonCell:
        disp, count = _best_months(c)
        return ComparisonCell(disp, sort_value=count)

    rows.append(row("Best Months", months_cell, better="high"))

    # Visa -- textual; no winner. Uses the country's visa summary if present.
    def visa_cell(c: City) -> ComparisonCell:
        summary = c.country.visa_summary or "Check requirements"
        # Keep it short for the cell.
        short = summary.split(".")[0][:28]
        return ComparisonCell(short)

    rows.append(ComparisonRow("Visa (EU/DE)", [visa_cell(c) for c in cities], better="none"))

    # English level -- placeholder, higher proxy is better.
    def english_cell(c: City) -> ComparisonCell:
        disp, val = _placeholder_english_level(c)
        return ComparisonCell(disp, sort_value=val, is_estimated=True)

    rows.append(row("English Level", english_cell, better="high"))

    # Food scene -- from ABSA aspect, higher is better; placeholder fallback.
    def food_cell(c: City) -> ComparisonCell:
        v = _aspect(c, ActivityCategory.FOOD)
        if v:
            return ComparisonCell(_stars(v), sort_value=v)
        disp, val = _placeholder_aspect(c, ActivityCategory.FOOD)
        return ComparisonCell(disp, sort_value=val, is_estimated=True)

    rows.append(row("Food Scene", food_cell, better="high"))

    # Nightlife -- placeholder, higher is better.
    def nightlife_cell(c: City) -> ComparisonCell:
        disp, val = _placeholder_nightlife(c)
        return ComparisonCell(disp, sort_value=val, is_estimated=True)

    rows.append(row("Nightlife", nightlife_cell, better="high"))

    # Nature -- from ABSA aspect, higher is better; placeholder fallback.
    def nature_cell(c: City) -> ComparisonCell:
        v = _aspect(c, ActivityCategory.NATURE)
        if v:
            return ComparisonCell(_stars(v), sort_value=v)
        disp, val = _placeholder_aspect(c, ActivityCategory.NATURE)
        return ComparisonCell(disp, sort_value=val, is_estimated=True)

    rows.append(row("Nature", nature_cell, better="high"))

    # --- Verdict card ---------------------------------------------------------
    verdicts = _verdicts(scored, rows)

    return ComparisonResult(scored=list(scored), rows=rows, verdicts=verdicts)


def _verdicts(
    scored: Sequence[ScoredCity], rows: Sequence[ComparisonRow]
) -> list[tuple[str, str]]:
    """
    Derive the "Best for X" lines shown in the verdict card, entirely from
    the rows we just computed -- so the verdicts can never contradict the
    table above them.
    """
    cities = [sc.city for sc in scored]
    if len(cities) < 2:
        return []

    def winner_of(label: str) -> str | None:
        r = next((r for r in rows if r.label == label), None)
        if not r:
            return None
        winners = [cities[i].country.name for i, c in enumerate(r.cells) if c.is_winner]
        return winners[0] if len(winners) == 1 else None

    verdicts: list[tuple[str, str]] = []
    if (b := winner_of("Daily Budget")):
        verdicts.append(("Best for Budget", b))
    if (s := winner_of("Safety Score")):
        verdicts.append(("Best for Safety", s))

    # Best overall = highest engine score (the deterministic ranker has the
    # final say, consistent with the rest of the product).
    best_overall = max(scored, key=lambda sc: sc.score)
    verdicts.append(("Best Overall (engine score)", best_overall.city.country.name))
    return verdicts
