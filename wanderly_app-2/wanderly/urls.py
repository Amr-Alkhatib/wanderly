"""Root URL configuration for Wanderly."""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

from web import views_auth, views_trips

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/signup/", views_auth.signup, name="signup"),
    path("accounts/login/", views_auth.login_view, name="login"),
    path("accounts/logout/", views_auth.logout_view, name="logout"),
    path("accounts/account/", views_auth.account, name="account"),
    # Password reset (Supabase-backed)
    path("accounts/password-reset/", views_auth.forgot_password, name="password_reset"),
    path("accounts/reset-password/confirm/", views_auth.reset_password_confirm, name="reset_password_confirm"),
    # Trip API endpoints (JSON)
    path("api/trips/save/", views_trips.save_trip, name="api_save_trip"),
    path("api/trips/<str:trip_id>/unsave/", views_trips.unsave_trip, name="api_unsave_trip"),
    path("api/trips/<str:trip_id>/complete/", views_trips.complete_trip, name="api_complete_trip"),
    path("api/profile/", views_trips.profile_api, name="api_profile"),
    path("", include("web.urls")),
]