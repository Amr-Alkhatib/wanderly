"""Root URL configuration for Wanderly."""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from web import views_auth

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/signup/", views_auth.signup, name="signup"),
    path("accounts/login/", views_auth.login_view, name="login"),
    path("accounts/logout/", views_auth.logout_view, name="logout"),
    path("accounts/password-reset/",
         auth_views.PasswordResetView.as_view(template_name="auth/password_reset.html"),
         name="password_reset"),
    path("accounts/password-reset/done/",
         auth_views.PasswordResetDoneView.as_view(template_name="auth/password_reset_done.html"),
         name="password_reset_done"),
    path("accounts/password-reset/<uidb64>/<token>/",
         auth_views.PasswordResetConfirmView.as_view(template_name="auth/password_reset_confirm.html"),
         name="password_reset_confirm"),
    path("accounts/password-reset/complete/",
         auth_views.PasswordResetCompleteView.as_view(template_name="auth/password_reset_complete.html"),
         name="password_reset_complete"),
    path("", include("web.urls")),
]