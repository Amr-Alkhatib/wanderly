from __future__ import annotations

import logging

from django.contrib.auth import get_user_model, login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .form_auth import LoginForm, SignupForm

User = get_user_model()
logger = logging.getLogger(__name__)


def _supabase_sign_up(email: str, password: str):
    """Call Supabase Auth sign_up using the anon key. Returns (supabase_user, error_str)."""
    from wanderly.supabase_client import get_supabase_auth
    try:
        resp = get_supabase_auth().auth.sign_up({"email": email, "password": password})
        if resp.user is None:
            return None, "Please check your email to confirm your account before signing in."
        # Email confirmation may be required — user exists but email not confirmed.
        if resp.user.identities is not None and len(resp.user.identities) == 0:
            return None, "Check your inbox to confirm your email address before signing in."
        return resp.user, None
    except Exception as exc:
        msg = str(exc)
        logger.error("Supabase sign_up error for %s: %s", email, msg)
        if "already registered" in msg.lower() or "already exists" in msg.lower() or "user already registered" in msg.lower():
            return None, "An account with this email already exists. Try signing in instead."
        return None, f"Sign-up failed: {msg}"


def _supabase_sign_in(email: str, password: str):
    """Call Supabase Auth sign_in_with_password using the anon key. Returns (supabase_user, session, error_str)."""
    from wanderly.supabase_client import get_supabase_auth
    try:
        resp = get_supabase_auth().auth.sign_in_with_password({"email": email, "password": password})
        if resp.user is None:
            return None, None, "Invalid email or password."
        return resp.user, resp.session, None
    except Exception as exc:
        msg = str(exc)
        logger.error("Supabase sign_in error for %s: %s", email, msg)
        if "email not confirmed" in msg.lower():
            return None, None, "Please confirm your email address before signing in."
        return None, None, "Invalid email or password."


def _upsert_profile(supabase_uid: str, email: str, first_name: str = "", last_name: str = "") -> None:
    """Write/update the Profiles row in Supabase. Never raises — logs on failure."""
    from wanderly.supabase_client import get_supabase
    try:
        full_name = f"{first_name} {last_name}".strip()
        # Profiles columns: id, created_at, updated_at, full_name, avatar_url — no email column
        payload = {"id": supabase_uid}
        if full_name:
            payload["full_name"] = full_name
        masked = f"{supabase_uid[:8]}…"
        print(f"[_upsert_profile] uid={masked} payload={payload}")
        logger.info("Upserting Profiles row for uid=%s", masked)
        result = get_supabase().table("Profiles").upsert(payload).execute()
        print(f"[_upsert_profile] result={result.data}")
        logger.info("Profiles upsert OK for uid=%s", masked)
    except Exception as exc:
        print(f"[_upsert_profile] ERROR uid={supabase_uid[:8]}: {exc}")
        logger.error("Profiles upsert failed for uid=%s: %s", supabase_uid[:8], exc)


def _get_or_create_django_user(email: str, supabase_uid: str) -> User:
    """Get or create a Django User linked to the given Supabase UID."""
    try:
        user = User.objects.get(supabase_uid=supabase_uid)
        if user.email != email:
            user.email = email
            user.save(update_fields=["email"])
        return user
    except User.DoesNotExist:
        pass

    user, created = User.objects.get_or_create(
        email=email,
        defaults={"supabase_uid": supabase_uid},
    )
    if not created and not user.supabase_uid:
        user.supabase_uid = supabase_uid
        user.save(update_fields=["supabase_uid"])

    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])

    return user


def signup(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")

    form = SignupForm(request.POST or None)
    error = None

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]

        sb_user, error = _supabase_sign_up(email, password)
        if sb_user:
            django_user = _get_or_create_django_user(email, str(sb_user.id))
            first_name = form.cleaned_data.get("first_name", "")
            last_name = form.cleaned_data.get("last_name", "")
            django_user.first_name = first_name
            django_user.last_name = last_name
            django_user.save(update_fields=["first_name", "last_name"])

            _upsert_profile(str(sb_user.id), email, first_name, last_name)

            login(request, django_user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("home")

    return render(request, "auth/signup.html", {"form": form, "error": error})


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")

    form = LoginForm(request.POST or None)
    error = None

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]

        sb_user, sb_session, error = _supabase_sign_in(email, password)
        if sb_user:
            django_user = _get_or_create_django_user(email, str(sb_user.id))
            if sb_session:
                request.session["supabase_access_token"] = sb_session.access_token

            _upsert_profile(str(sb_user.id), email, django_user.first_name, django_user.last_name)

            login(request, django_user, backend="django.contrib.auth.backends.ModelBackend")
            next_url = request.GET.get("next") or request.POST.get("next")
            return redirect(next_url) if next_url else redirect("home")

    return render(request, "auth/login.html", {
        "form": form,
        "error": error,
        "reset_success": request.GET.get("reset") == "1",
    })


def logout_view(request: HttpRequest) -> HttpResponse:
    request.session.pop("supabase_access_token", None)
    logout(request)
    return redirect("login")


def account(request: HttpRequest) -> HttpResponse:
    from intelligence.models import UserProfile
    from destinations.models import ActivityCategory

    if not request.user.is_authenticated:
        return redirect("login")

    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    # Fetch Supabase profile if linked (get-or-create)
    supabase_profile = {}
    if request.user.supabase_uid:
        from wanderly.supabase_client import get_supabase
        uid = request.user.supabase_uid
        print(f"[account GET] Fetching Profiles row for uid={uid[:8]}…")
        try:
            result = (
                get_supabase()
                .table("Profiles")
                .select("*")
                .eq("id", uid)
                .limit(1)
                .execute()
            )
            print(f"[account GET] Profiles fetch result: {result.data if result else None}")
            supabase_profile = (result.data[0] if result and result.data else {})
            if not supabase_profile:
                print(f"[account GET] No Profiles row — creating one for uid={uid[:8]}…")
                full_name = f"{request.user.first_name} {request.user.last_name}".strip()
                create_payload = {"id": uid}
                if full_name:
                    create_payload["full_name"] = full_name
                print(f"[account GET] Profiles create payload: {create_payload}")
                create_result = get_supabase().table("Profiles").upsert(create_payload).execute()
                print(f"[account GET] Profiles create result: {create_result.data}")
                supabase_profile = create_payload
        except Exception as exc:
            print(f"[account GET] Profiles error: {exc}")
            raise

    if request.method == "POST":
        profile.max_daily_budget_eur = int(request.POST.get("max_daily_budget_eur", 100))
        profile.safety_priority = int(request.POST.get("safety_priority", 3))
        profile.travel_month = request.POST.get("travel_month") or None
        profile.interests = request.POST.getlist("interests")
        profile.save()

        user = request.user
        user.first_name = request.POST.get("first_name", user.first_name)
        user.last_name = request.POST.get("last_name", user.last_name)
        user.save(update_fields=["first_name", "last_name"])

        # Update Supabase profile
        if user.supabase_uid:
            full_name = f"{user.first_name} {user.last_name}".strip()
            avatar_url = request.POST.get("avatar_url", "").strip()
            from wanderly.supabase_client import get_supabase
            upsert_payload = {"id": user.supabase_uid, "full_name": full_name}
            if avatar_url:
                upsert_payload["avatar_url"] = avatar_url
            print(f"[account POST] Upserting Profiles for uid={user.supabase_uid[:8]}… payload={upsert_payload}")
            try:
                result = get_supabase().table("Profiles").upsert(upsert_payload).execute()
                print(f"[account POST] Profiles upsert result: {result.data}")
            except Exception as exc:
                print(f"[account POST] Profiles upsert ERROR: {exc}")
                raise

        from django.urls import reverse
        return redirect(reverse("account") + "?saved=1")

    context = {
        "profile": profile,
        "supabase_profile": supabase_profile,
        "activity_categories": ActivityCategory.choices,
        "saved_ok": request.GET.get("saved") == "1",
        "months": [
            (1, "January"), (2, "February"), (3, "March"), (4, "April"),
            (5, "May"), (6, "June"), (7, "July"), (8, "August"),
            (9, "September"), (10, "October"), (11, "November"), (12, "December"),
        ],
    }
    return render(request, "auth/profile.html", context)


def forgot_password(request: HttpRequest) -> HttpResponse:
    success = False
    error = None

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        if not email:
            error = "Please enter your email address."
        else:
            from wanderly.supabase_client import get_supabase_auth
            # Must match exactly what's in Supabase dashboard → Authentication → URL Configuration → Redirect URLs
            redirect_to = "http://127.0.0.1:8000/accounts/reset-password/confirm/"
            print(f"[forgot_password] sending reset to {email}, redirect_to={redirect_to}")
            try:
                resp = get_supabase_auth().auth.reset_password_for_email(
                    email,
                    options={"redirect_to": redirect_to},
                )
                print(f"[forgot_password] Supabase response: {resp}")
                success = True
            except Exception as exc:
                print(f"[forgot_password] ERROR: {exc}")
                error = str(exc)

    return render(request, "auth/password_reset.html", {"success": success, "error": error})


def reset_password_confirm(request: HttpRequest) -> HttpResponse:
    # Supabase redirects here with ?token_hash=...&type=email (query string)
    # OR with #access_token=...&refresh_token=...&type=recovery (URL fragment — JS must extract)
    token_hash = (
        request.GET.get("token_hash") or request.POST.get("token_hash") or ""
    ).strip()
    # Supabase sends type=email (not recovery) after its own verify redirect
    token_type = (
        request.GET.get("type") or request.POST.get("token_type") or "email"
    ).strip()
    error = None

    print(f"[reset_confirm GET] token_hash={'…' + token_hash[:12] if token_hash else 'NONE'} type={token_type}")
    print(f"[reset_confirm GET] all GET params: {dict(request.GET)}")

    if request.method == "POST":
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")
        access_token = request.POST.get("access_token", "").strip()
        refresh_token = request.POST.get("refresh_token", "").strip()

        print(f"[reset_confirm POST] token_hash={'…' + token_hash[:12] if token_hash else 'NONE'} "
              f"access_token={'YES' if access_token else 'NO'} type={token_type}")

        if len(new_password) < 8:
            error = "Password must be at least 8 characters."
        elif new_password != confirm_password:
            error = "Passwords do not match."
        elif not token_hash and not access_token:
            error = "Invalid or missing reset token. Please request a new reset link."
        else:
            from django.conf import settings
            from supabase import create_client
            try:
                client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

                if token_hash:
                    print(f"[reset_confirm POST] verify_otp token_hash=…{token_hash[:12]} type={token_type}")
                    verify_resp = client.auth.verify_otp({
                        "token_hash": token_hash,
                        "type": token_type,
                    })
                    print(f"[reset_confirm POST] verify_otp response: {verify_resp}")
                    if not verify_resp.session:
                        error = "Reset link has expired or is invalid. Please request a new one."
                    else:
                        update_resp = client.auth.update_user({"password": new_password})
                        print(f"[reset_confirm POST] update_user response: {update_resp}")
                        from django.urls import reverse
                        return redirect(reverse("login") + "?reset=1")

                else:
                    # Fragment format: access_token was extracted by JS and posted as hidden field
                    print(f"[reset_confirm POST] set_session from access_token")
                    client.auth.set_session(access_token, refresh_token or access_token)
                    update_resp = client.auth.update_user({"password": new_password})
                    print(f"[reset_confirm POST] update_user (fragment path) response: {update_resp}")
                    from django.urls import reverse
                    return redirect(reverse("login") + "?reset=1")

            except Exception as exc:
                print(f"[reset_confirm POST] ERROR: {exc}")
                error = f"Password reset failed: {exc}"

    return render(request, "auth/reset_password_confirm.html", {
        "token_hash": token_hash,
        "token_type": token_type,
        "error": error,
    })
