from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .form_auth import SignupForm, LoginForm


def signup(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("home")
    return render(request, "auth/signup.html", {"form": form})


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        if user:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            next_url = request.GET.get("next") or request.POST.get("next")
            return redirect(next_url) if next_url else redirect("home")
        error = "Invalid email or password."
    return render(request, "auth/login.html", {"form": form, "error": error})


def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("login")


def account(request: HttpRequest) -> HttpResponse:
    from intelligence.models import UserProfile, SavedTrip
    from destinations.models import ActivityCategory

    if not request.user.is_authenticated:
        return redirect("login")

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    saved_trips = SavedTrip.objects.filter(user=request.user).select_related("city__country")[:6]

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
        return redirect("account")

    context = {
        "profile": profile,
        "saved_trips": saved_trips,
        "activity_categories": ActivityCategory.choices,
        "months": [
            (1,"January"),(2,"February"),(3,"March"),(4,"April"),
            (5,"May"),(6,"June"),(7,"July"),(8,"August"),
            (9,"September"),(10,"October"),(11,"November"),(12,"December"),
        ],
    }
    return render(request, "auth/profile.html", context)