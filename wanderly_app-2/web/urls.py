"""URL routes for the presentation layer (names preserved from the MVP)."""

from __future__ import annotations

from django.urls import path

from . import views
from .views_saved import saved

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("destination/<slug:slug>/", views.destination, name="destination"),
    path("compare/", views.compare, name="compare"),
    path("saved/", saved, name="saved"),
]
