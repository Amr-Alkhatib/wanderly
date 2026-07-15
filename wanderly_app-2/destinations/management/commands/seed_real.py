"""
Populates the database with a curated set of real destinations.
re-running updates existing rows rather than duplicating them.

Data provenance:
  * Country/city identity (name, region, language, currency, coordinates)
    are real, verifiable facts.
  * Monthly weather is fetched live from the Open-Meteo archive API and
    averaged over recent years -> DataSource.OPEN_METEO.
  * Cost and safety figures are curated estimates, not scraped from a live
    source -> DataSource.MANUAL.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from destinations.models import (
    ActivityCategory,
    BudgetTier,
    City,
    CostSnapshot,
    Country,
    DataSource,
    MonthlyWeather,
    Region,
    SafetyAdvisory,
)
from intelligence.models import CityAspectScore

_AC = ActivityCategory
_BT = BudgetTier
_LVL = SafetyAdvisory.Level

# Years of history to average Open-Meteo daily data into monthly norms.
_WX_START = "2019-01-01"
_WX_END = "2023-12-31"
_WX_YEARS = 5  # keep in sync with the range above;


_COUNTRIES = [
    # ---- EUROPE ------------------------------------------------------------
    {
        "name": "Portugal", "region": Region.EUROPE,
        "language": "Portuguese", "currency": "Euro (€)",
        "cities": [
            {"name": "Lisbon", "lat": 38.72, "lon": -9.14, "emoji": "🇵🇹",
             "image": "portugal.png", "card_pill": "Budget Pick",
             "category": _AC.CITY, "budget_tier": _BT.BUDGET, "featured": True,
             "summary": "Sun-soaked hills, tile-clad streets and easy coastal escapes.",
             "cost": (40, 75, 155), "safety": (86, _LVL.SAFE),
             "aspects": {_AC.CITY: 92, _AC.FOOD: 88, _AC.BEACH: 80}},
            {"name": "Porto", "lat": 41.15, "lon": -8.61, "emoji": "🍷",
             "image": "", "card_pill": "",
             "category": _AC.FOOD, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Port-wine cellars, riverside tiles and hearty northern food.",
             "cost": (38, 70, 145), "safety": (87, _LVL.SAFE),
             "aspects": {_AC.FOOD: 90, _AC.CITY: 84, _AC.CULTURAL: 82}},
        ],
    },
    {
        "name": "Spain", "region": Region.EUROPE,
        "language": "Spanish", "currency": "Euro (€)",
        "cities": [
            {"name": "Barcelona", "lat": 41.39, "lon": 2.17, "emoji": "🏝️",
             "image": "", "card_pill": "Trending",
             "category": _AC.CITY, "budget_tier": _BT.MID_RANGE, "featured": True,
             "summary": "Modernist architecture, tapas and Mediterranean beaches in one city.",
             "cost": (50, 95, 200), "safety": (78, _LVL.MODERATE),
             "aspects": {_AC.CITY: 90, _AC.CULTURAL: 88, _AC.BEACH: 82}},
            {"name": "Seville", "lat": 37.39, "lon": -5.99, "emoji": "💃",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "Flamenco, Moorish palaces and orange-scented Andalusian squares.",
             "cost": (42, 82, 170), "safety": (84, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 90, _AC.FOOD: 84, _AC.CITY: 80}},
        ],
    },
    {
        "name": "Italy", "region": Region.EUROPE,
        "language": "Italian", "currency": "Euro (€)",
        "cities": [
            {"name": "Rome", "lat": 41.90, "lon": 12.50, "emoji": "🏛️",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE, "featured": True,
             "summary": "Ancient ruins, Renaissance art and cacio e pepe at every corner.",
             "cost": (52, 100, 210), "safety": (79, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 96, _AC.FOOD: 90, _AC.CITY: 84}},
            {"name": "Florence", "lat": 43.77, "lon": 11.26, "emoji": "🎨",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "The cradle of the Renaissance, walkable and wine-country adjacent.",
             "cost": (50, 96, 200), "safety": (83, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 94, _AC.FOOD: 88, _AC.CITY: 78}},
        ],
    },
    {
        "name": "France", "region": Region.EUROPE,
        "language": "French", "currency": "Euro (€)",
        "cities": [
            {"name": "Paris", "lat": 48.86, "lon": 2.35, "emoji": "🗼",
             "image": "", "card_pill": "Iconic",
             "category": _AC.CITY, "budget_tier": _BT.LUXURY, "featured": True,
             "summary": "Grand boulevards, world museums and a café on every corner.",
             "cost": (60, 120, 260), "safety": (76, _LVL.MODERATE),
             "aspects": {_AC.CITY: 92, _AC.CULTURAL: 94, _AC.FOOD: 90}},
        ],
    },
    {
        "name": "Netherlands", "region": Region.EUROPE,
        "language": "Dutch", "currency": "Euro (€)",
        "cities": [
            {"name": "Amsterdam", "lat": 52.37, "lon": 4.90, "emoji": "🚲",
             "image": "", "card_pill": "",
             "category": _AC.CITY, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "Canals, bikes and Golden-Age art in a compact, liberal capital.",
             "cost": (55, 105, 220), "safety": (85, _LVL.SAFE),
             "aspects": {_AC.CITY: 90, _AC.CULTURAL: 86, _AC.FOOD: 78}},
        ],
    },
    {
        "name": "Czechia", "region": Region.EUROPE,
        "language": "Czech", "currency": "Czech Koruna (Kč)",
        "cities": [
            {"name": "Prague", "lat": 50.08, "lon": 14.44, "emoji": "🏰",
             "image": "", "card_pill": "Budget Pick",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Fairy-tale spires, cheap pilsner and a walkable medieval core.",
             "cost": (35, 70, 150), "safety": (88, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 90, _AC.CITY: 86, _AC.FOOD: 76}},
        ],
    },
    {
        "name": "Hungary", "region": Region.EUROPE,
        "language": "Hungarian", "currency": "Hungarian Forint (Ft)",
        "cities": [
            {"name": "Budapest", "lat": 47.50, "lon": 19.04, "emoji": "♨️",
             "image": "", "card_pill": "",
             "category": _AC.CITY, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Thermal baths, ruin bars and a grand Danube riverfront.",
             "cost": (33, 68, 145), "safety": (86, _LVL.SAFE),
             "aspects": {_AC.CITY: 86, _AC.CULTURAL: 84, _AC.FOOD: 78}},
        ],
    },
    {
        "name": "Croatia", "region": Region.EUROPE,
        "language": "Croatian", "currency": "Euro (€)",
        "cities": [
            {"name": "Split", "lat": 43.51, "lon": 16.44, "emoji": "⛵",
             "image": "", "card_pill": "",
             "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "A Roman palace turned old town, with island-hopping off the quay.",
             "cost": (40, 80, 165), "safety": (87, _LVL.SAFE),
             "aspects": {_AC.BEACH: 88, _AC.CULTURAL: 82, _AC.NATURE: 80}},
        ],
    },
    {
        "name": "Greece", "region": Region.EUROPE,
        "language": "Greek", "currency": "Euro (€)",
        "cities": [
            {"name": "Athens", "lat": 37.98, "lon": 23.73, "emoji": "🏺",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "The Acropolis above a gritty, lively, increasingly hip capital.",
             "cost": (37, 74, 150), "safety": (80, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 92, _AC.CITY: 78, _AC.FOOD: 82}},
        ],
    },
    {
        "name": "Iceland", "region": Region.EUROPE,
        "language": "Icelandic", "currency": "Icelandic Króna (kr)",
        "cities": [
            {"name": "Reykjavik", "lat": 64.15, "lon": -21.94, "emoji": "🌋",
             "image": "", "card_pill": "",
             "category": _AC.NATURE, "budget_tier": _BT.LUXURY, "featured": True,
             "summary": "Base camp for volcanoes, geysers and the northern lights.",
             "cost": (70, 130, 280), "safety": (94, _LVL.SAFE),
             "aspects": {_AC.NATURE: 96, _AC.ADVENTURE: 90, _AC.CITY: 70}},
        ],
    },
    {
        "name": "Albania", "region": Region.EUROPE,
        "language": "Albanian", "currency": "Albanian Lek (L)",
        "cities": [
            {"name": "Tirana", "lat": 41.33, "lon": 19.82, "emoji": "🏖️",
             "image": "albania.png", "card_pill": "",
             "category": _AC.BEACH, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "A colourful capital near Europe's most affordable Riviera.",
             "cost": (22, 55, 110), "safety": (80, _LVL.MODERATE),
             "aspects": {_AC.BEACH: 86, _AC.NATURE: 82, _AC.CITY: 70}},
        ],
    },

    # ---- ASIA --------------------------------------------------------------
    {
        "name": "Japan", "region": Region.ASIA,
        "language": "Japanese", "currency": "Japanese Yen (¥)",
        "cities": [
            {"name": "Tokyo", "lat": 35.68, "lon": 139.69, "emoji": "🗾",
             "image": "japan.png", "card_pill": "Trending",
             "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE, "featured": True,
             "summary": "A blend of ancient tradition and cutting-edge modernity.",
             "cost": (55, 110, 240), "safety": (92, _LVL.SAFE),
             "aspects": {_AC.FOOD: 96, _AC.CULTURAL: 94, _AC.CITY: 90}},
            {"name": "Kyoto", "lat": 35.01, "lon": 135.77, "emoji": "⛩️",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "Temples, geisha districts and raked-gravel gardens.",
             "cost": (50, 100, 220), "safety": (93, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 96, _AC.FOOD: 86, _AC.NATURE: 78}},
        ],
    },
    {
        "name": "Vietnam", "region": Region.ASIA,
        "language": "Vietnamese", "currency": "Vietnamese Dong (₫)",
        "cities": [
            {"name": "Hanoi", "lat": 21.03, "lon": 105.85, "emoji": "🍜",
             "image": "vietnam.png", "card_pill": "Food Scene",
             "category": _AC.FOOD, "budget_tier": _BT.BUDGET, "featured": True,
             "summary": "Street-food capital with lakes, old quarters and rich history.",
             "cost": (25, 55, 120), "safety": (84, _LVL.SAFE),
             "aspects": {_AC.FOOD: 95, _AC.CULTURAL: 82, _AC.CITY: 78}},
            {"name": "Ho Chi Minh City", "lat": 10.82, "lon": 106.63, "emoji": "🛵",
             "image": "", "card_pill": "",
             "category": _AC.CITY, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "A frenetic southern metropolis of markets, motorbikes and coffee.",
             "cost": (24, 52, 115), "safety": (80, _LVL.MODERATE),
             "aspects": {_AC.FOOD: 90, _AC.CITY: 82, _AC.CULTURAL: 76}},
        ],
    },
    {
        "name": "Thailand", "region": Region.ASIA,
        "language": "Thai", "currency": "Thai Baht (฿)",
        "cities": [
            {"name": "Bangkok", "lat": 13.76, "lon": 100.50, "emoji": "🛕",
             "image": "", "card_pill": "",
             "category": _AC.CITY, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Golden temples, night markets and legendary street food.",
             "cost": (28, 58, 130), "safety": (78, _LVL.MODERATE),
             "aspects": {_AC.FOOD: 92, _AC.CITY: 84, _AC.CULTURAL: 82}},
            {"name": "Chiang Mai", "lat": 18.79, "lon": 98.99, "emoji": "🐘",
             "image": "", "card_pill": "",
             "category": _AC.NATURE, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Mountain temples, elephant sanctuaries and a slow northern pace.",
             "cost": (24, 50, 110), "safety": (85, _LVL.SAFE),
             "aspects": {_AC.NATURE: 88, _AC.CULTURAL: 86, _AC.FOOD: 84}},
        ],
    },
    {
        "name": "Indonesia", "region": Region.ASIA,
        "language": "Indonesian", "currency": "Indonesian Rupiah (Rp)",
        "cities": [
            {"name": "Ubud", "lat": -8.52, "lon": 115.26, "emoji": "🌾",
             "image": "", "card_pill": "",
             "category": _AC.NATURE, "budget_tier": _BT.BUDGET, "featured": True,
             "summary": "Bali's green heart of rice terraces, yoga and temple valleys.",
             "cost": (25, 55, 125), "safety": (82, _LVL.SAFE),
             "aspects": {_AC.NATURE: 92, _AC.CULTURAL: 84, _AC.FOOD: 80}},
        ],
    },
    {
        "name": "India", "region": Region.ASIA,
        "language": "Hindi / English", "currency": "Indian Rupee (₹)",
        "cities": [
            {"name": "Jaipur", "lat": 26.91, "lon": 75.79, "emoji": "🏰",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "The Pink City of hilltop forts, bazaars and Rajput palaces.",
             "cost": (18, 42, 100), "safety": (68, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 92, _AC.FOOD: 82, _AC.CITY: 74}},
        ],
    },
    {
        "name": "Sri Lanka", "region": Region.ASIA,
        "language": "Sinhala / Tamil", "currency": "Sri Lankan Rupee (Rs)",
        "cities": [
            {"name": "Colombo", "lat": 6.93, "lon": 79.86, "emoji": "🌴",
             "image": "srilanka.png", "card_pill": "",
             "category": _AC.NATURE, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Coastal gateway to tea highlands, ancient cities and surf beaches.",
             "cost": (22, 50, 110), "safety": (74, _LVL.MODERATE),
             "aspects": {_AC.NATURE: 90, _AC.BEACH: 86, _AC.CULTURAL: 80}},
        ],
    },
    {
        "name": "Nepal", "region": Region.ASIA,
        "language": "Nepali", "currency": "Nepalese Rupee (रू)",
        "cities": [
            {"name": "Kathmandu", "lat": 27.71, "lon": 85.32, "emoji": "🏔️",
             "image": "", "card_pill": "",
             "category": _AC.ADVENTURE, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "The Himalayan trekking hub, dense with temples and mountain views.",
             "cost": (18, 42, 95), "safety": (72, _LVL.MODERATE),
             "aspects": {_AC.ADVENTURE: 94, _AC.MOUNTAINS: 96, _AC.CULTURAL: 84}},
        ],
    },
    {
        "name": "Georgia", "region": Region.ASIA,
        "language": "Georgian", "currency": "Georgian Lari (₾)",
        "cities": [
            {"name": "Tbilisi", "lat": 41.72, "lon": 44.79, "emoji": "⛰️",
             "image": "georgia.png", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Wine country, sulphur baths and old-town charm where Europe meets Asia.",
             "cost": (18, 45, 95), "safety": (85, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 86, _AC.FOOD: 88, _AC.NATURE: 84}},
        ],
    },

    # ---- MIDDLE EAST -------------------------------------------------------
    {
        "name": "Jordan", "region": Region.MIDDLE_EAST,
        "language": "Arabic", "currency": "Jordanian Dinar (JD)",
        "cities": [
            {"name": "Amman", "lat": 31.95, "lon": 35.93, "emoji": "🏜️",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "Hillside capital and springboard for Petra and the Wadi Rum desert.",
             "cost": (35, 72, 155), "safety": (79, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 88, _AC.ADVENTURE: 84, _AC.CITY: 72}},
        ],
    },
    {
        "name": "United Arab Emirates", "region": Region.MIDDLE_EAST,
        "language": "Arabic", "currency": "UAE Dirham (AED)",
        "cities": [
            {"name": "Dubai", "lat": 25.20, "lon": 55.27, "emoji": "🏙️",
             "image": "", "card_pill": "",
             "category": _AC.CITY, "budget_tier": _BT.LUXURY, "featured": False,
             "summary": "Superlative skyscrapers, desert safaris and duty-free excess.",
             "cost": (55, 120, 300), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.CITY: 90, _AC.ADVENTURE: 78, _AC.FOOD: 80}},
        ],
    },
    {
        "name": "Turkey", "region": Region.MIDDLE_EAST,
        "language": "Turkish", "currency": "Turkish Lira (₺)",
        "cities": [
            {"name": "Istanbul", "lat": 41.01, "lon": 28.98, "emoji": "🕌",
             "image": "", "card_pill": "Trending",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": True,
             "summary": "Where two continents meet: bazaars, mosques and Bosphorus ferries.",
             "cost": (28, 60, 135), "safety": (74, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 94, _AC.FOOD: 88, _AC.CITY: 84}},
        ],
    },

    # ---- AFRICA ------------------------------------------------------------
    {
        "name": "Morocco", "region": Region.AFRICA,
        "language": "Arabic / Berber", "currency": "Moroccan Dirham (MAD)",
        "cities": [
            {"name": "Marrakech", "lat": 31.63, "lon": -7.99, "emoji": "🕌",
             "image": "morocco.png", "card_pill": "Cultural",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": True,
             "summary": "Souks, palaces and desert gateways steeped in colour.",
             "cost": (28, 62, 140), "safety": (66, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 90, _AC.FOOD: 82, _AC.ADVENTURE: 78}},
            {"name": "Fes", "lat": 34.04, "lon": -4.99, "emoji": "🧵",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "A living medieval medina of tanneries, artisans and blue gates.",
             "cost": (26, 58, 130), "safety": (68, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 92, _AC.FOOD: 78, _AC.CITY: 70}},
        ],
    },
    {
        "name": "Egypt", "region": Region.AFRICA,
        "language": "Arabic", "currency": "Egyptian Pound (E£)",
        "cities": [
            {"name": "Cairo", "lat": 30.04, "lon": 31.24, "emoji": "🐫",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "The pyramids on the doorstep of a vast, chaotic, ancient capital.",
             "cost": (22, 50, 120), "safety": (62, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 94, _AC.ADVENTURE: 76, _AC.CITY: 68}},
        ],
    },
    {
        "name": "South Africa", "region": Region.AFRICA,
        "language": "English / Afrikaans", "currency": "South African Rand (R)",
        "cities": [
            {"name": "Cape Town", "lat": -33.92, "lon": 18.42, "emoji": "🏔️",
             "image": "", "card_pill": "Trending",
             "category": _AC.NATURE, "budget_tier": _BT.MID_RANGE, "featured": True,
             "summary": "Table Mountain, wine lands and two oceans meeting at the Cape.",
             "cost": (35, 72, 160), "safety": (58, _LVL.EXERCISE_CAUTION),
             "aspects": {_AC.NATURE: 94, _AC.BEACH: 82, _AC.ADVENTURE: 86}},
        ],
    },
    {
        "name": "Tanzania", "region": Region.AFRICA,
        "language": "Swahili / English", "currency": "Tanzanian Shilling (TSh)",
        "cities": [
            {"name": "Zanzibar City", "lat": -6.16, "lon": 39.19, "emoji": "🏝️",
             "image": "", "card_pill": "",
             "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "Spice-island beaches and a Swahili stone-town of carved doors.",
             "cost": (32, 68, 150), "safety": (70, _LVL.MODERATE),
             "aspects": {_AC.BEACH: 92, _AC.CULTURAL: 80, _AC.NATURE: 82}},
        ],
    },

    # ---- NORTH AMERICA -----------------------------------------------------
    {
        "name": "Mexico", "region": Region.NORTH_AMERICA,
        "language": "Spanish", "currency": "Mexican Peso (MX$)",
        "cities": [
            {"name": "Mexico City", "lat": 19.43, "lon": -99.13, "emoji": "🌮",
             "image": "", "card_pill": "Food Scene",
             "category": _AC.FOOD, "budget_tier": _BT.BUDGET, "featured": True,
             "summary": "Aztec ruins, world-class museums and a boundless food scene.",
             "cost": (30, 62, 140), "safety": (64, _LVL.MODERATE),
             "aspects": {_AC.FOOD: 94, _AC.CULTURAL: 90, _AC.CITY: 84}},
            {"name": "Oaxaca", "lat": 17.07, "lon": -96.72, "emoji": "🌶️",
             "image": "", "card_pill": "",
             "category": _AC.FOOD, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Mole, mezcal and craft markets in a colonial-era highland town.",
             "cost": (26, 55, 125), "safety": (72, _LVL.MODERATE),
             "aspects": {_AC.FOOD: 96, _AC.CULTURAL: 88, _AC.NATURE: 72}},
        ],
    },
    {
        "name": "United States", "region": Region.NORTH_AMERICA,
        "language": "English", "currency": "US Dollar ($)",
        "cities": [
            {"name": "New York", "lat": 40.71, "lon": -74.01, "emoji": "🗽",
             "image": "", "card_pill": "Iconic",
             "category": _AC.CITY, "budget_tier": _BT.LUXURY, "featured": True,
             "summary": "The archetypal global city: theatre, museums and every cuisine on earth.",
             "cost": (65, 135, 320), "safety": (74, _LVL.MODERATE),
             "aspects": {_AC.CITY: 96, _AC.FOOD: 90, _AC.CULTURAL: 90}},
        ],
    },
    {
        "name": "Canada", "region": Region.NORTH_AMERICA,
        "language": "English / French", "currency": "Canadian Dollar (C$)",
        "cities": [
            {"name": "Vancouver", "lat": 49.28, "lon": -123.12, "emoji": "🌲",
             "image": "", "card_pill": "",
             "category": _AC.NATURE, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "Mountains, ocean and rainforest wrapped around a laid-back city.",
             "cost": (50, 100, 220), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.NATURE: 92, _AC.CITY: 82, _AC.ADVENTURE: 84}},
        ],
    },
    {
        "name": "Guatemala", "region": Region.NORTH_AMERICA,
        "language": "Spanish", "currency": "Guatemalan Quetzal (Q)",
        "cities": [
            {"name": "Antigua", "lat": 14.56, "lon": -90.73, "emoji": "🌋",
             "image": "", "card_pill": "",
             "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Cobblestoned colonial streets framed by three volcanoes.",
             "cost": (22, 48, 110), "safety": (66, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 88, _AC.ADVENTURE: 82, _AC.NATURE: 84}},
        ],
    },

    # ---- SOUTH AMERICA -----------------------------------------------------
    {
        "name": "Peru", "region": Region.SOUTH_AMERICA,
        "language": "Spanish / Quechua", "currency": "Peruvian Sol (S/)",
        "cities": [
            {"name": "Cusco", "lat": -13.53, "lon": -71.97, "emoji": "🏔️",
             "image": "", "card_pill": "",
             "category": _AC.ADVENTURE, "budget_tier": _BT.BUDGET, "featured": True,
             "summary": "The Inca capital and gateway to Machu Picchu, high in the Andes.",
             "cost": (25, 55, 130), "safety": (70, _LVL.MODERATE),
             "aspects": {_AC.ADVENTURE: 92, _AC.CULTURAL: 90, _AC.MOUNTAINS: 94}},
        ],
    },
    {
        "name": "Colombia", "region": Region.SOUTH_AMERICA,
        "language": "Spanish", "currency": "Colombian Peso (COL$)",
        "cities": [
            {"name": "Medellin", "lat": 6.24, "lon": -75.58, "emoji": "🌸",
             "image": "", "card_pill": "",
             "category": _AC.CITY, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "The City of Eternal Spring, transformed and endlessly green.",
             "cost": (26, 55, 125), "safety": (62, _LVL.MODERATE),
             "aspects": {_AC.CITY: 84, _AC.NATURE: 80, _AC.FOOD: 78}},
            {"name": "Cartagena", "lat": 10.39, "lon": -75.51, "emoji": "🏖️",
             "image": "", "card_pill": "",
             "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "A walled Caribbean old town of bougainvillea and warm nights.",
             "cost": (30, 62, 140), "safety": (66, _LVL.MODERATE),
             "aspects": {_AC.BEACH: 88, _AC.CULTURAL: 84, _AC.CITY: 76}},
        ],
    },
    {
        "name": "Argentina", "region": Region.SOUTH_AMERICA,
        "language": "Spanish", "currency": "Argentine Peso (AR$)",
        "cities": [
            {"name": "Buenos Aires", "lat": -34.60, "lon": -58.38, "emoji": "💃",
             "image": "", "card_pill": "",
             "category": _AC.CITY, "budget_tier": _BT.BUDGET, "featured": False,
             "summary": "Tango, steak and grand European boulevards in a South-American beat.",
             "cost": (28, 60, 135), "safety": (68, _LVL.MODERATE),
             "aspects": {_AC.CITY: 88, _AC.FOOD: 86, _AC.CULTURAL: 84}},
        ],
    },
    {
        "name": "Brazil", "region": Region.SOUTH_AMERICA,
        "language": "Portuguese", "currency": "Brazilian Real (R$)",
        "cities": [
            {"name": "Rio de Janeiro", "lat": -22.91, "lon": -43.17, "emoji": "🏖️",
             "image": "", "card_pill": "",
             "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE, "featured": True,
             "summary": "Copacabana, Christ the Redeemer and mountains straight off the sand.",
             "cost": (32, 68, 150), "safety": (56, _LVL.EXERCISE_CAUTION),
             "aspects": {_AC.BEACH: 92, _AC.CITY: 84, _AC.NATURE: 82}},
        ],
    },

    # ---- OCEANIA -----------------------------------------------------------
    {
        "name": "Australia", "region": Region.OCEANIA,
        "language": "English", "currency": "Australian Dollar (A$)",
        "cities": [
            {"name": "Sydney", "lat": -33.87, "lon": 151.21, "emoji": "🌉",
             "image": "", "card_pill": "",
             "category": _AC.BEACH, "budget_tier": _BT.LUXURY, "featured": True,
             "summary": "Harbour icons, surf beaches and an outdoor, sun-lit lifestyle.",
             "cost": (55, 115, 260), "safety": (88, _LVL.SAFE),
             "aspects": {_AC.BEACH: 90, _AC.CITY: 88, _AC.NATURE: 82}},
            {"name": "Melbourne", "lat": -37.81, "lon": 144.96, "emoji": "☕",
             "image": "", "card_pill": "",
             "category": _AC.FOOD, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "Laneway coffee, street art and a restless cultural calendar.",
             "cost": (50, 105, 235), "safety": (87, _LVL.SAFE),
             "aspects": {_AC.FOOD: 90, _AC.CITY: 88, _AC.CULTURAL: 84}},
        ],
    },
    {
        "name": "New Zealand", "region": Region.OCEANIA,
        "language": "English / Māori", "currency": "New Zealand Dollar (NZ$)",
        "cities": [
            {"name": "Queenstown", "lat": -45.03, "lon": 168.66, "emoji": "🪂",
             "image": "", "card_pill": "",
             "category": _AC.ADVENTURE, "budget_tier": _BT.MID_RANGE, "featured": False,
             "summary": "The adventure capital: bungee, ski fields and alpine lakes.",
             "cost": (48, 100, 220), "safety": (92, _LVL.SAFE),
             "aspects": {_AC.ADVENTURE: 96, _AC.MOUNTAINS: 92, _AC.NATURE: 94}},
        ],
    },
]


# --- Additional countries ------------------------

_COUNTRIES_EXTRA = [
    # ---- EUROPE ------------------------------------------------------------
    {
        "name": "Germany", "region": Region.EUROPE,
        "language": "German", "currency": "Euro (€)",
        "cities": [
            {"name": "Berlin", "lat": 52.52, "lon": 13.40, "emoji": "🎨",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.MID_RANGE,
             "featured": True, "summary": "History, nightlife and street art in a restless, reinvented capital.",
             "cost": (45, 95, 210), "safety": (84, _LVL.SAFE),
             "aspects": {_AC.CITY: 90, _AC.CULTURAL: 88, _AC.FOOD: 80}},
            {"name": "Munich", "lat": 48.14, "lon": 11.58, "emoji": "🍺",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "Beer gardens, Baroque squares and the Alps an hour away.",
             "cost": (48, 98, 215), "safety": (88, _LVL.SAFE),
             "aspects": {_AC.CITY: 84, _AC.CULTURAL: 82, _AC.FOOD: 80}},
        ],
    },
    {
        "name": "United Kingdom", "region": Region.EUROPE,
        "language": "English", "currency": "British Pound (£)",
        "cities": [
            {"name": "London", "lat": 51.51, "lon": -0.13, "emoji": "🎡",
             "image": "", "card_pill": "Iconic", "category": _AC.CITY, "budget_tier": _BT.LUXURY,
             "featured": True, "summary": "Global theatre, free museums and every cuisine on earth.",
             "cost": (65, 130, 300), "safety": (80, _LVL.MODERATE),
             "aspects": {_AC.CITY: 96, _AC.CULTURAL: 92, _AC.FOOD: 84}},
            {"name": "Edinburgh", "lat": 55.95, "lon": -3.19, "emoji": "🏴",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A dramatic castle city of festivals, closes and crags.",
             "cost": (50, 100, 220), "safety": (88, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 90, _AC.CITY: 82, _AC.NATURE: 76}},
        ],
    },
    {
        "name": "Ireland", "region": Region.EUROPE,
        "language": "English / Irish", "currency": "Euro (€)",
        "cities": [
            {"name": "Dublin", "lat": 53.35, "lon": -6.26, "emoji": "🍀",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "Literary pubs, Georgian streets and a warm, wet welcome.",
             "cost": (52, 105, 225), "safety": (84, _LVL.SAFE),
             "aspects": {_AC.CITY: 84, _AC.CULTURAL: 82, _AC.FOOD: 76}},
        ],
    },
    {
        "name": "Austria", "region": Region.EUROPE,
        "language": "German", "currency": "Euro (€)",
        "cities": [
            {"name": "Vienna", "lat": 48.21, "lon": 16.37, "emoji": "🎻",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "Imperial palaces, coffee houses and a city built for music.",
             "cost": (48, 98, 210), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 94, _AC.CITY: 86, _AC.FOOD: 80}},
            {"name": "Salzburg", "lat": 47.81, "lon": 13.06, "emoji": "🏔️",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "Mozart's Baroque birthplace framed by alpine peaks.",
             "cost": (45, 92, 195), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 88, _AC.MOUNTAINS: 82, _AC.NATURE: 84}},
        ],
    },
    {
        "name": "Switzerland", "region": Region.EUROPE,
        "language": "German / French", "currency": "Swiss Franc (CHF)",
        "cities": [
            {"name": "Zurich", "lat": 47.37, "lon": 8.54, "emoji": "🏦",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.LUXURY,
             "featured": False, "summary": "A lakeside financial hub with old-town charm and clean everything.",
             "cost": (75, 140, 300), "safety": (94, _LVL.SAFE),
             "aspects": {_AC.CITY: 86, _AC.NATURE: 84, _AC.MOUNTAINS: 86}},
            {"name": "Interlaken", "lat": 46.69, "lon": 7.85, "emoji": "🪂",
             "image": "", "card_pill": "", "category": _AC.MOUNTAINS, "budget_tier": _BT.LUXURY,
             "featured": True, "summary": "The adventure gateway between two lakes under the Jungfrau.",
             "cost": (70, 130, 280), "safety": (94, _LVL.SAFE),
             "aspects": {_AC.MOUNTAINS: 96, _AC.ADVENTURE: 92, _AC.NATURE: 94}},
        ],
    },
    {
        "name": "Poland", "region": Region.EUROPE,
        "language": "Polish", "currency": "Polish Złoty (zł)",
        "cities": [
            {"name": "Krakow", "lat": 50.06, "lon": 19.94, "emoji": "🏰",
             "image": "", "card_pill": "Budget Pick", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A well-preserved medieval capital, sombre history nearby.",
             "cost": (30, 64, 140), "safety": (86, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 90, _AC.CITY: 82, _AC.FOOD: 76}},
            {"name": "Warsaw", "lat": 52.23, "lon": 21.01, "emoji": "🏙️",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A rebuilt capital mixing old-town facades with glass towers.",
             "cost": (32, 66, 145), "safety": (85, _LVL.SAFE),
             "aspects": {_AC.CITY: 82, _AC.CULTURAL: 80, _AC.FOOD: 74}},
        ],
    },
    {
        "name": "Denmark", "region": Region.EUROPE,
        "language": "Danish", "currency": "Danish Krone (kr)",
        "cities": [
            {"name": "Copenhagen", "lat": 55.68, "lon": 12.57, "emoji": "🚲",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.LUXURY,
             "featured": False, "summary": "Design, cycling and New Nordic food in a harbourside capital.",
             "cost": (60, 120, 260), "safety": (92, _LVL.SAFE),
             "aspects": {_AC.CITY: 90, _AC.FOOD: 86, _AC.CULTURAL: 82}},
        ],
    },
    {
        "name": "Sweden", "region": Region.EUROPE,
        "language": "Swedish", "currency": "Swedish Krona (kr)",
        "cities": [
            {"name": "Stockholm", "lat": 59.33, "lon": 18.06, "emoji": "🛥️",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.LUXURY,
             "featured": False, "summary": "A capital spread across fourteen islands, calm and design-led.",
             "cost": (58, 115, 250), "safety": (92, _LVL.SAFE),
             "aspects": {_AC.CITY: 88, _AC.NATURE: 82, _AC.CULTURAL: 84}},
            {"name": "Gothenburg", "lat": 57.71, "lon": 11.97, "emoji": "🦞",
             "image": "", "card_pill": "", "category": _AC.FOOD, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A laid-back seafood-and-canals counterpoint to the capital.",
             "cost": (50, 100, 215), "safety": (91, _LVL.SAFE),
             "aspects": {_AC.FOOD: 84, _AC.CITY: 80, _AC.NATURE: 78}},
        ],
    },
    {
        "name": "Norway", "region": Region.EUROPE,
        "language": "Norwegian", "currency": "Norwegian Krone (kr)",
        "cities": [
            {"name": "Bergen", "lat": 60.39, "lon": 5.32, "emoji": "🏔️",
             "image": "", "card_pill": "", "category": _AC.NATURE, "budget_tier": _BT.LUXURY,
             "featured": True, "summary": "Wooden wharves and the classic gateway to the fjords.",
             "cost": (62, 120, 260), "safety": (93, _LVL.SAFE),
             "aspects": {_AC.NATURE: 94, _AC.MOUNTAINS: 88, _AC.CITY: 74}},
        ],
    },
    {
        "name": "Belgium", "region": Region.EUROPE,
        "language": "Dutch / French", "currency": "Euro (€)",
        "cities": [
            {"name": "Bruges", "lat": 51.21, "lon": 3.22, "emoji": "🍫",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A canal-laced medieval town of chocolate, beer and belfries.",
             "cost": (48, 95, 205), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 90, _AC.CITY: 80, _AC.FOOD: 82}},
        ],
    },
    {
        "name": "Slovenia", "region": Region.EUROPE,
        "language": "Slovenian", "currency": "Euro (€)",
        "cities": [
            {"name": "Ljubljana", "lat": 46.06, "lon": 14.51, "emoji": "🐉",
             "image": "", "card_pill": "", "category": _AC.NATURE, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A green, walkable capital minutes from lakes and caves.",
             "cost": (35, 70, 150), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.NATURE: 86, _AC.CITY: 82, _AC.CULTURAL: 80}},
        ],
    },
    {
        "name": "Montenegro", "region": Region.EUROPE,
        "language": "Montenegrin", "currency": "Euro (€)",
        "cities": [
            {"name": "Kotor", "lat": 42.42, "lon": 18.77, "emoji": "⛵",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A fortified old town wrapped around a dramatic Adriatic bay.",
             "cost": (30, 64, 140), "safety": (86, _LVL.SAFE),
             "aspects": {_AC.BEACH: 86, _AC.NATURE: 84, _AC.CULTURAL: 78}},
        ],
    },
    {
        "name": "Romania", "region": Region.EUROPE,
        "language": "Romanian", "currency": "Romanian Leu (lei)",
        "cities": [
            {"name": "Brasov", "lat": 45.66, "lon": 25.61, "emoji": "🏔️",
             "image": "", "card_pill": "", "category": _AC.MOUNTAINS, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A Transylvanian old town ringed by the Carpathians and castles.",
             "cost": (28, 60, 130), "safety": (84, _LVL.SAFE),
             "aspects": {_AC.MOUNTAINS: 86, _AC.CULTURAL: 82, _AC.NATURE: 84}},
        ],
    },

    # ---- ASIA --------------------------------------------------------------
    {
        "name": "China", "region": Region.ASIA,
        "language": "Mandarin Chinese", "currency": "Chinese Yuan (¥)",
        "cities": [
            {"name": "Beijing", "lat": 39.90, "lon": 116.41, "emoji": "🏯",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.MID_RANGE,
             "featured": True, "summary": "The Forbidden City, the Great Wall and imperial history at scale.",
             "cost": (32, 68, 155), "safety": (76, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 94, _AC.CITY: 86, _AC.FOOD: 84}},
            {"name": "Shanghai", "lat": 31.23, "lon": 121.47, "emoji": "🌃",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A neon skyline over colonial riverfronts and world-class food.",
             "cost": (34, 70, 160), "safety": (78, _LVL.MODERATE),
             "aspects": {_AC.CITY: 92, _AC.FOOD: 84, _AC.CULTURAL: 80}},
        ],
    },
    {
        "name": "South Korea", "region": Region.ASIA,
        "language": "Korean", "currency": "South Korean Won (₩)",
        "cities": [
            {"name": "Seoul", "lat": 37.57, "lon": 126.98, "emoji": "🏙️",
             "image": "", "card_pill": "Trending", "category": _AC.CITY, "budget_tier": _BT.MID_RANGE,
             "featured": True, "summary": "Palaces beside skyscrapers, all-night food and non-stop pop culture.",
             "cost": (42, 85, 185), "safety": (86, _LVL.SAFE),
             "aspects": {_AC.CITY: 90, _AC.FOOD: 90, _AC.CULTURAL: 84}},
            {"name": "Busan", "lat": 35.18, "lon": 129.08, "emoji": "🏖️",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A coastal city of beaches, seafood markets and hillside villages.",
             "cost": (38, 78, 170), "safety": (86, _LVL.SAFE),
             "aspects": {_AC.BEACH: 84, _AC.CITY: 80, _AC.FOOD: 82}},
        ],
    },
    {
        "name": "Malaysia", "region": Region.ASIA,
        "language": "Malay", "currency": "Malaysian Ringgit (RM)",
        "cities": [
            {"name": "Kuala Lumpur", "lat": 3.14, "lon": 101.69, "emoji": "🌆",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "Twin towers, hawker stalls and a mash-up of Asian cultures.",
             "cost": (28, 58, 130), "safety": (80, _LVL.MODERATE),
             "aspects": {_AC.CITY: 84, _AC.FOOD: 90, _AC.CULTURAL: 78}},
            {"name": "George Town", "lat": 5.41, "lon": 100.34, "emoji": "🍜",
             "image": "", "card_pill": "Food Scene", "category": _AC.FOOD, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A heritage port town famous for street art and street food.",
             "cost": (26, 54, 120), "safety": (82, _LVL.SAFE),
             "aspects": {_AC.FOOD: 94, _AC.CULTURAL: 86, _AC.CITY: 76}},
        ],
    },
    {
        "name": "Singapore", "region": Region.ASIA,
        "language": "English / Malay", "currency": "Singapore Dollar (S$)",
        "cities": [
            {"name": "Singapore", "lat": 1.35, "lon": 103.82, "emoji": "🌳",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.LUXURY,
             "featured": True, "summary": "A hyper-green city-state of hawker feasts and futuristic gardens.",
             "cost": (48, 98, 230), "safety": (94, _LVL.SAFE),
             "aspects": {_AC.CITY: 94, _AC.FOOD: 92, _AC.CULTURAL: 80}},
        ],
    },
    {
        "name": "Philippines", "region": Region.ASIA,
        "language": "Filipino / English", "currency": "Philippine Peso (₱)",
        "cities": [
            {"name": "Cebu", "lat": 10.32, "lon": 123.90, "emoji": "🐠",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "Diving, waterfalls and island-hopping from a busy central hub.",
             "cost": (26, 54, 125), "safety": (72, _LVL.MODERATE),
             "aspects": {_AC.BEACH: 90, _AC.NATURE: 84, _AC.ADVENTURE: 80}},
            {"name": "El Nido", "lat": 11.18, "lon": 119.39, "emoji": "🏝️",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.BUDGET,
             "featured": True, "summary": "Limestone lagoons and turquoise bays on Palawan's northern tip.",
             "cost": (28, 58, 130), "safety": (74, _LVL.MODERATE),
             "aspects": {_AC.BEACH: 96, _AC.NATURE: 92, _AC.ADVENTURE: 84}},
        ],
    },
    {
        "name": "Cambodia", "region": Region.ASIA,
        "language": "Khmer", "currency": "Cambodian Riel (៛)",
        "cities": [
            {"name": "Siem Reap", "lat": 13.36, "lon": 103.86, "emoji": "🛕",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": True, "summary": "The base for Angkor's vast temple complex at sunrise.",
             "cost": (22, 48, 110), "safety": (78, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 96, _AC.ADVENTURE: 78, _AC.FOOD: 76}},
            {"name": "Phnom Penh", "lat": 11.56, "lon": 104.92, "emoji": "🏛️",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A riverside capital of royal palaces and sobering recent history.",
             "cost": (22, 48, 108), "safety": (70, _LVL.MODERATE),
             "aspects": {_AC.CITY: 74, _AC.CULTURAL: 80, _AC.FOOD: 76}},
        ],
    },
    {
        "name": "Laos", "region": Region.ASIA,
        "language": "Lao", "currency": "Lao Kip (₭)",
        "cities": [
            {"name": "Luang Prabang", "lat": 19.89, "lon": 102.14, "emoji": "🌅",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A serene riverside town of monks, temples and waterfalls.",
             "cost": (24, 50, 112), "safety": (84, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 90, _AC.NATURE: 84, _AC.FOOD: 78}},
        ],
    },
    {
        "name": "Uzbekistan", "region": Region.ASIA,
        "language": "Uzbek", "currency": "Uzbekistani Som (soʻm)",
        "cities": [
            {"name": "Samarkand", "lat": 39.65, "lon": 66.96, "emoji": "🕌",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "Dazzling Silk-Road tilework and turquoise madrasa domes.",
             "cost": (22, 48, 108), "safety": (82, _LVL.SAFE),
             "aspects": {_AC.CULTURAL: 94, _AC.CITY: 74, _AC.FOOD: 72}},
        ],
    },
    {
        "name": "Taiwan", "region": Region.ASIA,
        "language": "Mandarin Chinese", "currency": "New Taiwan Dollar (NT$)",
        "cities": [
            {"name": "Taipei", "lat": 25.03, "lon": 121.57, "emoji": "🥟",
             "image": "", "card_pill": "Food Scene", "category": _AC.FOOD, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "Night markets, hot springs and mountains at the city's edge.",
             "cost": (32, 66, 150), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.FOOD: 92, _AC.CITY: 84, _AC.CULTURAL: 82}},
        ],
    },

    # ---- MIDDLE EAST -------------------------------------------------------
    {
        "name": "Israel", "region": Region.MIDDLE_EAST,
        "language": "Hebrew", "currency": "Israeli Shekel (₪)",
        "cities": [
            {"name": "Tel Aviv", "lat": 32.08, "lon": 34.78, "emoji": "🏖️",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.LUXURY,
             "featured": False, "summary": "Mediterranean beaches, Bauhaus streets and a big food scene.",
             "cost": (50, 100, 220), "safety": (66, _LVL.MODERATE),
             "aspects": {_AC.BEACH: 86, _AC.CITY: 84, _AC.FOOD: 88}},
        ],
    },
    {
        "name": "Oman", "region": Region.MIDDLE_EAST,
        "language": "Arabic", "currency": "Omani Rial (OMR)",
        "cities": [
            {"name": "Muscat", "lat": 23.59, "lon": 58.41, "emoji": "🏜️",
             "image": "", "card_pill": "", "category": _AC.NATURE, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "Whitewashed forts between dramatic mountains and the sea.",
             "cost": (45, 92, 210), "safety": (88, _LVL.SAFE),
             "aspects": {_AC.NATURE: 84, _AC.CULTURAL: 80, _AC.BEACH: 78}},
        ],
    },
    {
        "name": "Qatar", "region": Region.MIDDLE_EAST,
        "language": "Arabic", "currency": "Qatari Riyal (QR)",
        "cities": [
            {"name": "Doha", "lat": 25.29, "lon": 51.53, "emoji": "🏙️",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.LUXURY,
             "featured": False, "summary": "A fast-rising Gulf capital of museums, souqs and skyline.",
             "cost": (50, 98, 240), "safety": (90, _LVL.SAFE),
             "aspects": {_AC.CITY: 86, _AC.CULTURAL: 80, _AC.FOOD: 78}},
        ],
    },
    {
        "name": "Lebanon", "region": Region.MIDDLE_EAST,
        "language": "Arabic", "currency": "Lebanese Pound (L£)",
        "cities": [
            {"name": "Beirut", "lat": 33.89, "lon": 35.50, "emoji": "🍽️",
             "image": "", "card_pill": "", "category": _AC.FOOD, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A resilient seaside city known for food, nightlife and history.",
             "cost": (35, 72, 155), "safety": (58, _LVL.EXERCISE_CAUTION),
             "aspects": {_AC.FOOD: 90, _AC.CITY: 78, _AC.CULTURAL: 80}},
        ],
    },

    # ---- AFRICA ------------------------------------------------------------
    {
        "name": "Kenya", "region": Region.AFRICA,
        "language": "Swahili / English", "currency": "Kenyan Shilling (KSh)",
        "cities": [
            {"name": "Nairobi", "lat": -1.29, "lon": 36.82, "emoji": "🦁",
             "image": "", "card_pill": "", "category": _AC.NATURE, "budget_tier": _BT.MID_RANGE,
             "featured": True, "summary": "The safari springboard, with a national park on its doorstep.",
             "cost": (35, 72, 165), "safety": (60, _LVL.MODERATE),
             "aspects": {_AC.NATURE: 90, _AC.ADVENTURE: 86, _AC.CITY: 68}},
            {"name": "Mombasa", "lat": -4.04, "lon": 39.67, "emoji": "🏝️",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "Swahili-coast beaches, coral reefs and an old spice-trade port.",
             "cost": (32, 66, 150), "safety": (62, _LVL.MODERATE),
             "aspects": {_AC.BEACH: 90, _AC.NATURE: 80, _AC.CULTURAL: 74}},
        ],
    },
    {
        "name": "Ethiopia", "region": Region.AFRICA,
        "language": "Amharic", "currency": "Ethiopian Birr (Br)",
        "cities": [
            {"name": "Addis Ababa", "lat": 9.03, "lon": 38.74, "emoji": "☕",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A high-altitude capital and the birthplace of the coffee ritual.",
             "cost": (25, 52, 120), "safety": (62, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 84, _AC.CITY: 68, _AC.FOOD: 76}},
        ],
    },
    {
        "name": "Namibia", "region": Region.AFRICA,
        "language": "English", "currency": "Namibian Dollar (N$)",
        "cities": [
            {"name": "Windhoek", "lat": -22.56, "lon": 17.08, "emoji": "🏜️",
             "image": "", "card_pill": "", "category": _AC.NATURE, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "The calm base for desert dunes, canyons and wildlife drives.",
             "cost": (35, 72, 160), "safety": (72, _LVL.MODERATE),
             "aspects": {_AC.NATURE: 92, _AC.ADVENTURE: 84, _AC.CITY: 66}},
        ],
    },
    {
        "name": "Rwanda", "region": Region.AFRICA,
        "language": "Kinyarwanda / English", "currency": "Rwandan Franc (FRw)",
        "cities": [
            {"name": "Kigali", "lat": -1.94, "lon": 30.06, "emoji": "🦍",
             "image": "", "card_pill": "", "category": _AC.NATURE, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A clean, green capital and the gateway to mountain gorillas.",
             "cost": (30, 65, 150), "safety": (82, _LVL.SAFE),
             "aspects": {_AC.NATURE: 90, _AC.ADVENTURE: 84, _AC.CITY: 74}},
        ],
    },
    {
        "name": "Senegal", "region": Region.AFRICA,
        "language": "French", "currency": "West African CFA Franc (CFA)",
        "cities": [
            {"name": "Dakar", "lat": 14.72, "lon": -17.47, "emoji": "🥁",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "West Africa's lively Atlantic capital of music, art and markets.",
             "cost": (30, 62, 140), "safety": (68, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 84, _AC.BEACH: 80, _AC.CITY: 72}},
        ],
    },

    # ---- NORTH AMERICA -----------------------------------------------------
    {
        "name": "Costa Rica", "region": Region.NORTH_AMERICA,
        "language": "Spanish", "currency": "Costa Rican Colón (₡)",
        "cities": [
            {"name": "San Jose", "lat": 9.93, "lon": -84.08, "emoji": "🌿",
             "image": "", "card_pill": "", "category": _AC.NATURE, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "The central hub for rainforests, volcanoes and both coasts.",
             "cost": (38, 78, 175), "safety": (76, _LVL.MODERATE),
             "aspects": {_AC.NATURE: 90, _AC.ADVENTURE: 86, _AC.CITY: 70}},
            {"name": "La Fortuna", "lat": 10.47, "lon": -84.64, "emoji": "🌋",
             "image": "", "card_pill": "", "category": _AC.ADVENTURE, "budget_tier": _BT.MID_RANGE,
             "featured": True, "summary": "Hot springs and zip-lines under the Arenal volcano.",
             "cost": (40, 80, 175), "safety": (80, _LVL.SAFE),
             "aspects": {_AC.ADVENTURE: 92, _AC.NATURE: 94, _AC.MOUNTAINS: 82}},
        ],
    },
    {
        "name": "Cuba", "region": Region.NORTH_AMERICA,
        "language": "Spanish", "currency": "Cuban Peso (CUP)",
        "cities": [
            {"name": "Havana", "lat": 23.11, "lon": -82.37, "emoji": "🚗",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "Classic cars, crumbling grandeur and live son on every corner.",
             "cost": (30, 62, 140), "safety": (76, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 92, _AC.CITY: 82, _AC.FOOD: 72}},
        ],
    },
    {
        "name": "Panama", "region": Region.NORTH_AMERICA,
        "language": "Spanish", "currency": "US Dollar ($)",
        "cities": [
            {"name": "Panama City", "lat": 8.98, "lon": -79.52, "emoji": "🚢",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A skyline capital beside the famous canal and an old quarter.",
             "cost": (35, 70, 155), "safety": (72, _LVL.MODERATE),
             "aspects": {_AC.CITY: 82, _AC.BEACH: 78, _AC.NATURE: 80}},
        ],
    },
    {
        "name": "Belize", "region": Region.NORTH_AMERICA,
        "language": "English", "currency": "Belize Dollar (BZ$)",
        "cities": [
            {"name": "San Ignacio", "lat": 17.16, "lon": -89.07, "emoji": "🌴",
             "image": "", "card_pill": "", "category": _AC.ADVENTURE, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "Jungle base for Maya ruins, caves and river adventures.",
             "cost": (40, 80, 175), "safety": (74, _LVL.MODERATE),
             "aspects": {_AC.ADVENTURE: 90, _AC.NATURE: 88, _AC.CULTURAL: 80}},
        ],
    },

    # ---- SOUTH AMERICA -----------------------------------------------------
    {
        "name": "Ecuador", "region": Region.SOUTH_AMERICA,
        "language": "Spanish / Quechua", "currency": "US Dollar ($)",
        "cities": [
            {"name": "Quito", "lat": -0.18, "lon": -78.47, "emoji": "⛰️",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A high-Andean capital with the best-preserved colonial old town.",
             "cost": (25, 52, 120), "safety": (68, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 88, _AC.NATURE: 84, _AC.CITY: 74}},
        ],
    },
    {
        "name": "Bolivia", "region": Region.SOUTH_AMERICA,
        "language": "Spanish / Quechua", "currency": "Bolivian Boliviano (Bs)",
        "cities": [
            {"name": "La Paz", "lat": -16.50, "lon": -68.15, "emoji": "🚡",
             "image": "", "card_pill": "", "category": _AC.ADVENTURE, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "The world's highest capital, cable cars strung over a canyon city.",
             "cost": (20, 45, 100), "safety": (66, _LVL.MODERATE),
             "aspects": {_AC.ADVENTURE: 90, _AC.MOUNTAINS: 92, _AC.CULTURAL: 84}},
        ],
    },
    {
        "name": "Chile", "region": Region.SOUTH_AMERICA,
        "language": "Spanish", "currency": "Chilean Peso (CLP$)",
        "cities": [
            {"name": "Santiago", "lat": -33.45, "lon": -70.67, "emoji": "🏔️",
             "image": "", "card_pill": "", "category": _AC.CITY, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A modern capital hemmed by the Andes and near-vineyards.",
             "cost": (35, 72, 160), "safety": (78, _LVL.MODERATE),
             "aspects": {_AC.CITY: 82, _AC.NATURE: 80, _AC.FOOD: 80}},
            {"name": "Valparaíso", "lat": -33.05, "lon": -71.61, "emoji": "🎨",
             "image": "", "card_pill": "", "category": _AC.CULTURAL, "budget_tier": _BT.BUDGET,
             "featured": False, "summary": "A bohemian port of funiculars, murals and tumbling hillsides.",
             "cost": (30, 64, 140), "safety": (70, _LVL.MODERATE),
             "aspects": {_AC.CULTURAL: 88, _AC.BEACH: 78, _AC.CITY: 76}},
        ],
    },
    {
        "name": "Uruguay", "region": Region.SOUTH_AMERICA,
        "language": "Spanish", "currency": "Uruguayan Peso ($U)",
        "cities": [
            {"name": "Montevideo", "lat": -34.90, "lon": -56.16, "emoji": "🧉",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "A relaxed riverfront capital of ramblas, markets and mate.",
             "cost": (38, 78, 170), "safety": (80, _LVL.SAFE),
             "aspects": {_AC.BEACH: 82, _AC.CITY: 80, _AC.CULTURAL: 78}},
        ],
    },

    # ---- OCEANIA -----------------------------------------------------------
    {
        "name": "Fiji", "region": Region.OCEANIA,
        "language": "English / Fijian", "currency": "Fijian Dollar (FJ$)",
        "cities": [
            {"name": "Suva", "lat": -18.14, "lon": 178.44, "emoji": "🏝️",
             "image": "", "card_pill": "", "category": _AC.BEACH, "budget_tier": _BT.MID_RANGE,
             "featured": False, "summary": "The lush capital and hub for reef-fringed island escapes.",
             "cost": (45, 90, 200), "safety": (80, _LVL.SAFE),
             "aspects": {_AC.BEACH: 92, _AC.NATURE: 88, _AC.ADVENTURE: 80}},
        ],
    },
]

_COUNTRIES = _COUNTRIES + _COUNTRIES_EXTRA


# --- Weather: fetch + aggregate


def _fetch_open_meteo(
    lat: float, lon: float, timeout: int = 30, retries: int = 4
) -> tuple[dict | None, str]:
    """
    Pull several years of daily history from the Open-Meteo archive API.

    """
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={_WX_START}&end_date={_WX_END}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        "&timezone=auto"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "wanderly-seed/1.0"})
    last_err = "unknown error"

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            daily = payload.get("daily")
            if daily:
                return daily, ""
            last_err = "response had no 'daily' data"
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            # 429 = too many requests: wait longer each time, then retry.
            wait = (6 * (attempt + 1)) if exc.code == 429 else (2 * (attempt + 1))
            time.sleep(wait)
            continue
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            last_err = str(getattr(exc, "reason", exc))[:80]
            time.sleep(2 * (attempt + 1))
            continue

    return None, last_err


def _aggregate_monthly(daily: dict, years: int = _WX_YEARS) -> dict[int, dict]:

    times = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    rains = daily.get("precipitation_sum", [])

    high_acc: dict[int, list[float]] = defaultdict(list)
    low_acc: dict[int, list[float]] = defaultdict(list)
    rain_acc: dict[int, float] = defaultdict(float)

    for i, day in enumerate(times):
        month = int(day[5:7])  # "YYYY-MM-DD" -> MM
        if i < len(highs) and highs[i] is not None:
            high_acc[month].append(highs[i])
        if i < len(lows) and lows[i] is not None:
            low_acc[month].append(lows[i])
        if i < len(rains) and rains[i] is not None:
            rain_acc[month] += rains[i]

    out: dict[int, dict] = {}
    for month in range(1, 13):
        hs, ls = high_acc[month], low_acc[month]
        high = round(sum(hs) / len(hs)) if hs else 0
        low = round(sum(ls) / len(ls)) if ls else 0
        rain = round(rain_acc[month] / max(1, years))
        out[month] = {"high": high, "low": max(low, -60), "rain": max(rain, 0)}
    return out


def _classify_climate(high: int, rain: int) -> str:
    """Map an average monthly high (+rainfall) to a Climate label."""
    C = MonthlyWeather.Climate
    if high >= 30:
        return C.HOT_HUMID if rain >= 100 else C.WARM_SUNNY
    if high >= 24:
        return C.WARM_SUNNY
    if high >= 15:
        return C.MILD
    if high >= 6:
        return C.COOL_DRY
    return C.COLD


def _is_recommended(high: int, low: int, rain: int) -> bool:
    """A month is 'recommended' when it's comfortably warm and not too wet."""
    return 18 <= high <= 32 and low >= 7 and rain < 130




class Command(BaseCommand):
    help = "Populate the database with a curated set of real destinations."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--skip-weather", action="store_true",
            help="Don't call Open-Meteo; seed everything except monthly weather.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Only seed the first N cities (handy for a quick test run).",
        )
        parser.add_argument(
            "--refresh-weather", action="store_true",
            help="Re-fetch weather even for cities that already have it. "
                 "By default, cities that already have weather are skipped, "
                 "so re-running only fills in the ones still missing it.",
        )

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        skip_weather: bool = options["skip_weather"]
        limit: int | None = options["limit"]
        refresh_weather: bool = options["refresh_weather"]

        now = timezone.now()
        cities_seen = 0
        cities_created = 0
        weather_ok = 0
        weather_failed = 0
        weather_skipped = 0

        for country_row in _COUNTRIES:
            country, _ = Country.objects.update_or_create(
                name=country_row["name"],
                defaults={
                    "region": country_row["region"],
                    "language": country_row["language"],
                    "currency": country_row["currency"],
                    "visa_summary": "EU/US citizens: typically visa-free for short stays.",
                },
            )

            for cd in country_row["cities"]:
                if limit is not None and cities_seen >= limit:
                    break
                cities_seen += 1

                city, created = City.objects.update_or_create(
                    country=country,
                    name=cd["name"],
                    defaults={
                        "summary": cd["summary"],
                        "primary_category": cd["category"],
                        "budget_tier": cd["budget_tier"],
                        "emoji": cd.get("emoji", ""),
                        "image": cd.get("image", ""),
                        "card_pill": cd.get("card_pill", ""),
                        "is_featured": cd.get("featured", False),
                    },
                )
                cities_created += int(created)

                # -- Cost (curated estimate)

                budget_d, mid_d, lux_d = cd["cost"]
                CostSnapshot.objects.update_or_create(
                    city=city,
                    source=DataSource.MANUAL,
                    defaults={
                        "captured_at": now,
                        "daily_budget_eur": budget_d,
                        "daily_midrange_eur": mid_d,
                        "daily_luxury_eur": lux_d,
                        "hostel_night_eur": max(10, budget_d // 2),
                        "meal_cheap_eur": max(3, budget_d // 8),
                        "local_transport_day_eur": max(2, budget_d // 10),
                    },
                )

                # -- Safety (curated estimate)
                score, level = cd["safety"]
                SafetyAdvisory.objects.update_or_create(
                    city=city,
                    source=DataSource.MANUAL,
                    defaults={
                        "captured_at": now,
                        "safety_score": score,
                        "level": level,
                        "health_notes": "Standard precautions advised.",
                        "advisory_summary": "No major travel restrictions at seed time.",
                    },
                )

                # -- Aspect scores (curated estimate)
                for aspect, value in cd["aspects"].items():
                    CityAspectScore.objects.update_or_create(
                        city=city,
                        aspect=aspect,
                        defaults={"score": value, "sample_size": 120},
                    )

                # -- Weather (REAL, from Open-Meteo)
                if skip_weather:
                    continue


                if not refresh_weather and city.weather.exists():
                    weather_skipped += 1
                    continue

                daily, reason = _fetch_open_meteo(cd["lat"], cd["lon"])
                if daily is None:
                    weather_failed += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  weather fetch failed for {cd['name']} ({reason})"
                        )
                    )
                else:
                    norms = _aggregate_monthly(daily)
                    for month, m in norms.items():
                        MonthlyWeather.objects.update_or_create(
                            city=city,
                            month=month,
                            defaults={
                                "avg_high_c": m["high"],
                                "avg_low_c": m["low"],
                                "rainfall_mm": m["rain"],
                                "climate_type": _classify_climate(m["high"], m["rain"]),
                                "is_recommended_month": _is_recommended(
                                    m["high"], m["low"], m["rain"]
                                ),
                                "source": DataSource.OPEN_METEO,
                                "captured_at": now,
                            },
                        )
                    weather_ok += 1
                    time.sleep(0.5)

            if limit is not None and cities_seen >= limit:
                break

        total = City.objects.count()
        summary = (
            f"Seed complete: {cities_created} new cities ({total} total), "
            f"with cost, safety and aspect data."
        )
        if not skip_weather:
            summary += (
                f" Weather: {weather_ok} fetched, {weather_skipped} already had it, "
                f"{weather_failed} failed."
            )
        self.stdout.write(self.style.SUCCESS(summary))