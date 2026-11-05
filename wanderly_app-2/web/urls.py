"""URL routes for the presentation layer (names preserved from the MVP)."""

from __future__ import annotations

from django.urls import path

from . import views
from .views_saved import saved

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("country/<slug:slug>/", views.country_profile, name="country_profile"),
    path("destination/<slug:slug>/", views.destination, name="destination"),
    path("destination/<slug:slug>/itinerary/", views.itinerary_fragment, name="itinerary_fragment"),
    path("compare/", views.compare, name="compare"),
    path("saved/", saved, name="saved"),
]
