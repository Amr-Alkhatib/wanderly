"""
Supabase clients for backend use.

Two clients:
- get_supabase()      — service-role key preferred (bypasses RLS).
                        Falls back to anon key with a warning when
                        SUPABASE_SERVICE_KEY is not set.
- get_supabase_auth() — anon key always, for sign_up / sign_in_with_password.

Never pass either client or any key to the frontend.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_client = None
_auth_client = None


def get_supabase():
    """Return the lazily-initialised Supabase client for DB operations."""
    global _client
    if _client is None:
        from supabase import create_client
        key = settings.SUPABASE_SERVICE_KEY
        if not key:
            logger.warning(
                "SUPABASE_SERVICE_KEY is not set — falling back to anon key. "
                "DB operations are subject to Row Level Security. "
                "Set SUPABASE_SERVICE_KEY env var for full access."
            )
            key = settings.SUPABASE_ANON_KEY
        _client = create_client(settings.SUPABASE_URL, key)
    return _client


def get_supabase_auth():
    """Return a Supabase client using the anon key — for sign_up/sign_in only."""
    global _auth_client
    if _auth_client is None:
        from supabase import create_client
        _auth_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    return _auth_client


def reset_clients():
    """Force re-initialisation (useful after settings change in tests)."""
    global _client, _auth_client
    _client = None
    _auth_client = None
