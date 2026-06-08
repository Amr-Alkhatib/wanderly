"""
Trip management views — all endpoints return JSON and require an active
Django session (CSRF + session-cookie auth, service-role Supabase client).
"""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST


def _uid(request) -> str | None:
    return request.user.supabase_uid


@login_required
@require_POST
def save_trip(request) -> JsonResponse:
    """Create or mark-as-saved a trip for a destination slug."""
    from wanderly.supabase_client import get_supabase

    uid = _uid(request)
    if not uid:
        return JsonResponse({"error": "No Supabase account linked to your profile."}, status=400)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    destination = (body.get("destination") or "").strip()
    title = (body.get("title") or destination).strip()

    if not destination:
        return JsonResponse({"error": "destination is required."}, status=400)

    sb = get_supabase()

    existing = (
        sb.table("trips")
        .select("id, status")
        .eq("user_id", uid)
        .eq("destination", destination)
        .execute()
    )

    if existing.data:
        trip_id = existing.data[0]["id"]
        sb.table("trips").update({"status": "saved", "title": title}).eq("id", trip_id).execute()
        return JsonResponse({"id": trip_id, "status": "saved", "action": "updated"})

    result = sb.table("trips").insert({
        "user_id": uid,
        "destination": destination,
        "title": title,
        "status": "saved",
    }).execute()
    trip = result.data[0] if result.data else {}
    return JsonResponse({"id": trip.get("id"), "status": "saved", "action": "created"})


@login_required
@require_POST
def unsave_trip(request, trip_id: str) -> JsonResponse:
    from wanderly.supabase_client import get_supabase
    uid = _uid(request)
    if not uid:
        return JsonResponse({"error": "No Supabase account linked."}, status=400)
    get_supabase().table("trips").delete().eq("id", trip_id).eq("user_id", uid).execute()
    return JsonResponse({"status": "deleted"})


@login_required
@require_POST
def complete_trip(request, trip_id: str) -> JsonResponse:
    from wanderly.supabase_client import get_supabase
    uid = _uid(request)
    if not uid:
        return JsonResponse({"error": "No Supabase account linked."}, status=400)
    get_supabase().table("trips").update({"status": "completed"}).eq("id", trip_id).eq("user_id", uid).execute()
    return JsonResponse({"status": "completed"})


@login_required
def profile_api(request) -> JsonResponse:
    """GET/POST the user's Supabase profile (full_name, avatar_url)."""
    from wanderly.supabase_client import get_supabase
    uid = _uid(request)
    if not uid:
        return JsonResponse({"error": "No Supabase account linked."}, status=400)

    sb = get_supabase()

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)
        payload = {k: v for k, v in body.items() if k in ("full_name", "avatar_url")}
        payload["id"] = uid
        result = sb.table("Profiles").upsert(payload).execute()
        return JsonResponse({"profile": result.data[0] if result.data else {}})

    result = sb.table("Profiles").select("*").eq("id", uid).maybe_single().execute()
    return JsonResponse({"profile": result.data or {}})
