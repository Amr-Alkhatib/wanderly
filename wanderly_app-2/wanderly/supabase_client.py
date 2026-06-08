"""
Singleton service-role Supabase client for backend use.

The service-role key bypasses Row Level Security — keep it backend-only.
Never pass this client or its key to the frontend.
"""
from __future__ import annotations

from django.conf import settings

_client = None


def get_supabase():
    """Return the lazily-initialised service-role Supabase client."""
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _client
