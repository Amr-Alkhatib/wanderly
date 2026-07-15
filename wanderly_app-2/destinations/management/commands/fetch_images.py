
from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError

from destinations.models import City

_SEARCH_URL = "https://api.pexels.com/v1/search"
_UA = "wanderly-images/1.0"


# --- Pexels helpers ----------------------------------------------------------


def _pick_image_url(payload: dict) -> str | None:

    photos = payload.get("photos") or []
    if not photos:
        return None
    src = photos[0].get("src") or {}
    # Prefer a landscape crop for cards; fall back through sensible sizes.
    for key in ("landscape", "large", "medium", "original"):
        if src.get(key):
            return src[key]
    return None


def _pexels_search(
    query: str, api_key: str, timeout: int = 30, retries: int = 4
) -> tuple[str | None, str]:

    url = (
        f"{_SEARCH_URL}?query={urllib.parse.quote(query)}"
        "&per_page=1&orientation=landscape"
    )
    req = urllib.request.Request(
        url, headers={"Authorization": api_key, "User-Agent": _UA}
    )
    last_err = "unknown error"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return _pick_image_url(payload), ""
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise CommandError(
                    "Pexels rejected the API key (HTTP 401). "
                    "Double-check the value passed to --api-key."
                )
            last_err = f"HTTP {exc.code}"
            time.sleep((6 * (attempt + 1)) if exc.code == 429 else (2 * (attempt + 1)))
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            last_err = str(getattr(exc, "reason", exc))[:80]
            time.sleep(2 * (attempt + 1))
    return None, last_err


def _download(url: str, timeout: int = 30, retries: int = 3) -> tuple[bytes | None, str]:

    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    last_err = "unknown error"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), ""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = str(getattr(exc, "reason", exc))[:80]
            time.sleep(2 * (attempt + 1))
    return None, last_err


def _save_png(data: bytes, path: str) -> None:

    try:
        from PIL import Image  # optional

        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.save(path, "PNG")
    except ImportError:
        with open(path, "wb") as handle:
            handle.write(data)


def _resolve_dest_dir(override: str | None) -> str:

    if override:
        if not os.path.isdir(override):
            raise CommandError(f"--dest is not a folder: {override}")
        return override
    # Use a file we know already exists to locate the folder reliably.
    probe = finders.find("images/dest/albania.png") or finders.find("images/dest")
    if probe:
        return probe if os.path.isdir(probe) else os.path.dirname(probe)
    raise CommandError(
        "Couldn't locate static/images/dest automatically. "
        "Pass the full path with --dest /path/to/static/images/dest"
    )


# --- Command -----------------------------------------------------------------


class Command(BaseCommand):
    help = "Download a real photo per city from Pexels into static/images/dest/."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--api-key", default=None,
            help="Pexels API key. If omitted, uses the PEXELS_API_KEY env var.",
        )
        parser.add_argument(
            "--dest", default=None,
            help="Override the target folder (defaults to static/images/dest).",
        )
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Re-download even for cities that already have an image file.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Only process the first N cities (handy for a quick test).",
        )
        parser.add_argument(
            "--own-photos", action="store_true",
            help="First clear every city's 'image' field so all cities fall back "
                 "to their own '<slug>.png'. Fixes cities that were sharing a "
                 "country image (e.g. Tirana and Saranda both on albania.png), "
                 "then fetches the ones now missing a photo.",
        )

    def handle(self, *args: object, **options: object) -> None:
        api_key = options["api_key"] or os.environ.get("PEXELS_API_KEY")
        if not api_key:
            raise CommandError(
                "No Pexels API key. Pass --api-key YOUR_KEY (get one free at "
                "https://www.pexels.com/api/) or set PEXELS_API_KEY."
            )

        dest_dir = _resolve_dest_dir(options["dest"])
        overwrite: bool = options["overwrite"]
        limit: int | None = options["limit"]

        # Make every city use its own "<slug>.png" instead of a shared country
        # image. Cities that had a country image will now look for a slug file
        # that doesn't exist yet, so the fetch below downloads a distinct photo
        # for each one.
        if options["own_photos"]:
            cleared = City.objects.exclude(image="").update(image="")
            self.stdout.write(
                self.style.WARNING(
                    f"Cleared the 'image' field on {cleared} cities; "
                    "all cities will now use their own <slug>.png."
                )
            )

        downloaded = skipped = failed = 0
        seen = 0

        for city in City.objects.select_related("country").all():
            if limit is not None and seen >= limit:
                break
            seen += 1

            filename = city.image_file
            path = os.path.join(dest_dir, filename)

            if not overwrite and os.path.exists(path):
                skipped += 1
                continue

            query = f"{city.name} {city.country.name}"
            url, reason = _pexels_search(query, api_key)
            if not url:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  no photo for {city.name} ({reason or 'no results'})"
                    )
                )
                continue

            data, reason = _download(url)
            if data is None:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(f"  download failed for {city.name} ({reason})")
                )
                continue

            try:
                _save_png(data, path)
            except OSError as exc:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(f"  save failed for {city.name} ({exc})")
                )
                continue

            downloaded += 1
            self.stdout.write(f"  saved {filename}")
            time.sleep(0.5)  

        self.stdout.write(
            self.style.SUCCESS(
                f"Images done: {downloaded} downloaded, {skipped} already had one, "
                f"{failed} failed. Folder: {dest_dir}"
            )
        )