from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ItineraryDay:
    title: str
    morning: str
    afternoon: str
    evening: str
    morning_cost: int = 0
    afternoon_cost: int = 0
    evening_cost: int = 0

PROMPT = (
    "You are a travel planner. Create a {days}-day itinerary for {city}, {country}. "
    "Keep the daily budget around €{budget}. "
    "For each activity, add an estimated cost in euros as a plain number (0 if free). "
    "Return ONLY this exact format, one item per line, nothing else:\n"
    "DAY 1 | short theme for the day\n"
    "Morning | one activity | estimated euro cost\n"
    "Afternoon | one activity | estimated euro cost\n"
    "Evening | one activity | estimated euro cost\n"
    "Then repeat DAY 2, DAY 3, etc."
)

def build_itinerary(city, days: int = 3) -> list[ItineraryDay]:
    cost = city.cost_snapshots.order_by("-captured_at").first()
    budget = cost.daily_budget_eur if cost else 60
    prompt = PROMPT.format(
        days=days, city=city.name, country=city.country.name, budget=budget
    )
    try:
        return _parse(_complete(prompt))
    except Exception as exc:
        print(f"[build_itinerary] ERROR: {exc}")
        return []

def _complete(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    return resp.text or ""


def _parse(text: str) -> list[ItineraryDay]:
    days: list[ItineraryDay] = []
    current: ItineraryDay | None = None
    for line in text.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        label = parts[0].lower()
        activity = parts[1] if len(parts) > 1 else ""
        cost = _to_cost(parts[2]) if len(parts) > 2 else 0
        if label.startswith("day"):
            if current:
                days.append(current)
            current = ItineraryDay(activity, "", "", "")
        elif current and label == "morning":
            current.morning = activity
            current.morning_cost = cost
        elif current and label == "afternoon":
            current.afternoon = activity
            current.afternoon_cost = cost
        elif current and label == "evening":
            current.evening = activity
            current.evening_cost = cost
    if current:
        days.append(current)
    return days

def _to_cost(text: str) -> int:
    text = text.replace("€", "").strip()
    try:
        return int(text)
    except ValueError:
        return 0