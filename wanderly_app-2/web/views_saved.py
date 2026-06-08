"""Saved trips page view + shared helper for saved-state context."""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

logger = logging.getLogger(__name__)


def get_saved_trip_map(user) -> dict:
    """Return {destination_slug: trip_id} for all saved trips of authenticated user."""
    if not user.is_authenticated or not getattr(user, "supabase_uid", None):
        return {}
    uid = user.supabase_uid
    print(f"[get_saved_trip_map] fetching trips for uid={uid[:8]}…")
    try:
        from wanderly.supabase_client import get_supabase
        result = (
            get_supabase()
            .table("trips")
            .select("destination, id")
            .eq("user_id", uid)
            .execute()
        )
        print(f"[get_saved_trip_map] result: {result.data}")
        return {
            t["destination"]: t["id"]
            for t in (result.data or [])
            if t.get("destination") and t.get("id")
        }
    except Exception as exc:
        print(f"[get_saved_trip_map] ERROR uid={uid[:8]}: {exc}")
        logger.warning("Could not fetch saved trips for %s: %s", user, exc)
        raise


@login_required
def saved(request):
    from wanderly.supabase_client import get_supabase
    from destinations.models import City

    uid = request.user.supabase_uid
    trips = []
    error_msg = None

    if uid:
        print(f"[saved] fetching trips for uid={uid[:8]}…")
        try:
            sb = get_supabase()
            result = (
                sb.table("trips")
                .select("*")
                .eq("user_id", uid)
                .order("created_at", desc=True)
                .execute()
            )
            print(f"[saved] trips result: {result.data}")
            raw = result.data or []

            slugs = [t["destination"] for t in raw if t.get("destination")]
            cities = {
                c.slug: c
                for c in City.objects.filter(slug__in=slugs).select_related("country")
            }

            for trip in raw:
                trip["city"] = cities.get(trip.get("destination"))

            trips = raw
        except Exception as exc:
            print(f"[saved] ERROR uid={uid[:8]}: {exc}")
            logger.error("Saved page Supabase error for uid %s: %s", uid, exc)
            error_msg = (
                "Could not load your saved trips right now. "
                "Please try again later."
            )

    return render(request, "core/saved.html", {"trips": trips, "error_msg": error_msg})
