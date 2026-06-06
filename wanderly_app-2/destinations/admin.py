"""Admin wiring for the data layer -- lets the team curate seed data."""

from __future__ import annotations

from django.contrib import admin

from .models import (
    Activity,
    City,
    CostSnapshot,
    Country,
    MonthlyWeather,
    SafetyAdvisory,
)


class ActivityInline(admin.TabularInline):
    model = Activity
    extra = 0


class CostSnapshotInline(admin.TabularInline):
    model = CostSnapshot
    extra = 0


class SafetyAdvisoryInline(admin.TabularInline):
    model = SafetyAdvisory
    extra = 0


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "language", "currency")
    list_filter = ("region",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "primary_category", "budget_symbol", "is_featured")
    list_filter = ("primary_category", "budget_tier", "is_featured", "country__region")
    search_fields = ("name", "country__name")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ActivityInline, CostSnapshotInline, SafetyAdvisoryInline]


@admin.register(MonthlyWeather)
class MonthlyWeatherAdmin(admin.ModelAdmin):
    list_display = ("city", "month", "avg_high_c", "climate_type", "source", "is_stale")
    list_filter = ("climate_type", "source")
    search_fields = ("city__name",)


@admin.register(SafetyAdvisory)
class SafetyAdvisoryAdmin(admin.ModelAdmin):
    list_display = ("city", "safety_score", "level", "captured_at", "source", "is_stale")
    list_filter = ("level", "source")
    search_fields = ("city__name",)


@admin.register(CostSnapshot)
class CostSnapshotAdmin(admin.ModelAdmin):
    list_display = ("city", "daily_budget_eur", "captured_at", "source", "is_stale")
    list_filter = ("source",)
    search_fields = ("city__name",)
