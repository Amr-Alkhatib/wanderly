"""
Trip management views — JSON endpoints, CSRF + session auth.
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def _uid(request) -> str | None:
    return getattr(request.user, "supabase_uid", None)


@login_required
@require_POST
def save_trip(request) -> JsonResponse:
    """Create or re-save a trip for a destination slug."""
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

    print(f"[save_trip] uid={uid[:8] if uid else None} destination={destination} title={title}")
    try:
        sb = get_supabase()

        existing = (
            sb.table("trips")
            .select("id, status")
            .eq("user_id", uid)
            .eq("destination", destination)
            .execute()
        )
        print(f"[save_trip] existing rows: {existing.data}")

        if existing.data:
            trip_id = existing.data[0]["id"]
            sb.table("trips").update({"status": "saved", "title": title}).eq("id", trip_id).execute()
            print(f"[save_trip] updated existing trip {trip_id}")
            return JsonResponse({"id": trip_id, "status": "saved", "action": "updated"})

        insert_payload = {"user_id": uid, "destination": destination, "title": title, "status": "saved"}
        print(f"[save_trip] inserting: {insert_payload}")
        result = sb.table("trips").insert(insert_payload).execute()
        print(f"[save_trip] insert result: {result.data}")
        trip = result.data[0] if result.data else {}
        return JsonResponse({"id": trip.get("id"), "status": "saved", "action": "created"})

    except Exception as exc:
        print(f"[save_trip] ERROR uid={uid} dest={destination}: {exc}")
        logger.error("save_trip error uid=%s dest=%s: %s", uid, destination, exc)
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@require_POST
def unsave_trip(request, trip_id: str) -> JsonResponse:
    from wanderly.supabase_client import get_supabase
    uid = _uid(request)
    if not uid:
        return JsonResponse({"error": "No Supabase account linked."}, status=400)
    print(f"[unsave_trip] uid={uid[:8] if uid else None} trip_id={trip_id}")
    try:
        result = get_supabase().table("trips").delete().eq("id", trip_id).eq("user_id", uid).execute()
        print(f"[unsave_trip] delete result: {result.data}")
        return JsonResponse({"status": "deleted"})
    except Exception as exc:
        print(f"[unsave_trip] ERROR: {exc}")
        logger.error("unsave_trip error uid=%s trip=%s: %s", uid, trip_id, exc)
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@require_POST
def complete_trip(request, trip_id: str) -> JsonResponse:
    from wanderly.supabase_client import get_supabase
    uid = _uid(request)
    if not uid:
        return JsonResponse({"error": "No Supabase account linked."}, status=400)
    print(f"[complete_trip] uid={uid[:8] if uid else None} trip_id={trip_id}")
    try:
        result = get_supabase().table("trips").update({"status": "completed"}).eq("id", trip_id).eq("user_id", uid).execute()
        print(f"[complete_trip] update result: {result.data}")
        return JsonResponse({"status": "completed"})
    except Exception as exc:
        print(f"[complete_trip] ERROR: {exc}")
        logger.error("complete_trip error uid=%s trip=%s: %s", uid, trip_id, exc)
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
def profile_api(request) -> JsonResponse:
    """GET/POST the user's Supabase profile (full_name, avatar_url)."""
    from wanderly.supabase_client import get_supabase
    uid = _uid(request)
    if not uid:
        return JsonResponse({"error": "No Supabase account linked."}, status=400)

    try:
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

        result = sb.table("Profiles").select("*").eq("id", uid).limit(1).execute()
        return JsonResponse({"profile": result.data[0] if result and result.data else {}})

    except Exception as exc:
        logger.error("profile_api error uid=%s: %s", uid, exc)
        return JsonResponse({"error": "Profile service unavailable."}, status=500)
