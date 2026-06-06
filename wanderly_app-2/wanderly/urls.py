"""Root URL configuration for Wanderly."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

from web import views_auth

from web.views_auth import signup_view, login_view, logout_view
from django.contrib import admin
from django.urls import path

# ✅ Import your auth views
from web.views_auth import signup_view, login_view, logout_view


urlpatterns = [
    # Django admin
    path('admin/', admin.site.urls),

    # ✅ Authentication routes
    path("accounts/login/",
         views_auth.LoginView.as_view(template_name="auth/login.html"),
         name="login"),
    path("accounts/logout/",
         views_auth.LogoutView.as_view(next_page="home"),
         name="logout"),
    path("accounts/signup/", signup, name="signup"),
    path("accounts/password-reset/",
         views_auth.PasswordResetView.as_view(
             template_name="auth/password_reset.html",
             email_template_name="auth/emails/password_reset_email.txt",
             subject_template_name="auth/emails/password_reset_subject.txt",
         ),
         name="password_reset"),
    path("accounts/password-reset/done/",
         views_auth.PasswordResetDoneView.as_view(
             template_name="auth/password_reset_done.html",
         ),
         name="password_reset_done"),
    path("accounts/password-reset/<uidb64>/<token>/",
         views_auth.PasswordResetConfirmView.as_view(
             template_name="auth/password_reset_confirm.html",
         ),
         name="password_reset_confirm"),
    path("accounts/password-reset/complete/",
         views_auth.PasswordResetCompleteView.as_view(
             template_name="auth/password_reset_complete.html",
         ),
         name="password_reset_complete"),

]
