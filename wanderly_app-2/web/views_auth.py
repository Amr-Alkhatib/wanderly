from __future__ import annotations

from django.contrib.auth import get_user_model, login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .form_auth import LoginForm, SignupForm

User = get_user_model()


def _supabase_sign_up(email: str, password: str):
    """Call Supabase Auth sign_up. Returns (supabase_user, error_str)."""
    from wanderly.supabase_client import get_supabase
    try:
        resp = get_supabase().auth.sign_up({"email": email, "password": password})
        if resp.user is None:
            return None, "Please check your email to confirm your account before signing in."
        return resp.user, None
    except Exception as exc:
        msg = str(exc)
        if "already registered" in msg.lower() or "already exists" in msg.lower():
            return None, "An account with this email already exists."
        return None, "Sign-up failed. Please try again."


def _supabase_sign_in(email: str, password: str):
    """Call Supabase Auth sign_in_with_password. Returns (supabase_user, session, error_str)."""
    from wanderly.supabase_client import get_supabase
    try:
        resp = get_supabase().auth.sign_in_with_password({"email": email, "password": password})
        if resp.user is None:
            return None, None, "Invalid email or password."
        return resp.user, resp.session, None
    except Exception:
        return None, None, "Invalid email or password."


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
        password = form.cleaned_data["password1"]

        sb_user, error = _supabase_sign_up(email, password)
        if sb_user:
            django_user = _get_or_create_django_user(email, str(sb_user.id))
            # Carry over any name fields from the form
            if hasattr(form, "cleaned_data"):
                django_user.first_name = form.cleaned_data.get("first_name", "")
                django_user.last_name = form.cleaned_data.get("last_name", "")
                django_user.save(update_fields=["first_name", "last_name"])
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
            login(request, django_user, backend="django.contrib.auth.backends.ModelBackend")
            next_url = request.GET.get("next") or request.POST.get("next")
            return redirect(next_url) if next_url else redirect("home")

    return render(request, "auth/login.html", {"form": form, "error": error})


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

    # Fetch Supabase profile if linked
    supabase_profile = {}
    if request.user.supabase_uid:
        from wanderly.supabase_client import get_supabase
        try:
            result = (
                get_supabase()
                .table("Profiles")
                .select("*")
                .eq("id", request.user.supabase_uid)
                .maybe_single()
                .execute()
            )
            supabase_profile = result.data or {}
        except Exception:
            pass

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
            from wanderly.supabase_client import get_supabase
            try:
                get_supabase().table("Profiles").upsert({
                    "id": user.supabase_uid,
                    "full_name": full_name,
                }).execute()
            except Exception:
                pass

        return redirect("account")

    context = {
        "profile": profile,
        "supabase_profile": supabase_profile,
        "activity_categories": ActivityCategory.choices,
        "months": [
            (1, "January"), (2, "February"), (3, "March"), (4, "April"),
            (5, "May"), (6, "June"), (7, "July"), (8, "August"),
            (9, "September"), (10, "October"), (11, "November"), (12, "December"),
        ],
    }
    return render(request, "auth/profile.html", context)
