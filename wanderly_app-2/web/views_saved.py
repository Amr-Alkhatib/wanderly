"""Saved trips page view."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def saved(request):
    from wanderly.supabase_client import get_supabase
    from destinations.models import City

    uid = request.user.supabase_uid
    trips = []

    if uid:
        sb = get_supabase()
        result = (
            sb.table("trips")
            .select("*")
            .eq("user_id", uid)
            .order("created_at", desc=True)
            .execute()
        )
        raw = result.data or []

        slugs = [t["destination"] for t in raw if t.get("destination")]
        cities = {c.slug: c for c in City.objects.filter(slug__in=slugs).select_related("country")}

        for trip in raw:
            trip["city"] = cities.get(trip.get("destination"))

        trips = raw

    return render(request, "core/saved.html", {"trips": trips})
