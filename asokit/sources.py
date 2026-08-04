"""HTTP access to the two free Apple endpoints, with on-disk caching.

Neither endpoint needs an account or an API key.

  autocomplete()  App Store search hints — Apple's own per-storefront
                  suggestion ranking. Apple no longer exposes the numeric
                  priority score it once did, but the ORDER is still Apple's
                  ranking, which is the signal we use.

  search()        iTunes Search API — the ranked app list for a query in a
                  country. Rate limited to roughly 20 requests/minute, so
                  calls are spaced and cached.

Cached responses make re-runs free, which is what makes before/after rank
comparison practical.
"""

import html
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import storefronts

HINTS_URL = "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"
SEARCH_URL = "https://itunes.apple.com/search"
USER_AGENT = "aso-keyword-toolkit (+https://github.com/ggapp1/aso-keyword-toolkit)"

HINTS_DELAY = 0.7
SEARCH_DELAY = 3.2


class Cache:
    """Keyed JSON cache. Written eagerly so an interrupted run keeps its work."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.data = {}
        if self.path and self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                print(f"warning: corrupt cache at {self.path}, starting fresh", file=sys.stderr)

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data))


def _fetch(url, headers, cache, delay):
    key = url + "|" + json.dumps(headers, sort_keys=True)
    if cache:
        hit = cache.get(key)
        if hit is not None:
            return hit
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
            if cache:
                cache.put(key, body)
            time.sleep(delay)
            return body
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code == 403:
                print(
                    "\nApple returned 403 — the endpoint is rate limiting this IP.\n"
                    "Wait a few minutes and re-run; cached results are kept.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            time.sleep(5 * (attempt + 1))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as error:
            last_error = error
            time.sleep(5 * (attempt + 1))
    print(f"warning: giving up on {url} ({last_error})", file=sys.stderr)
    return None


def _clean(text):
    """Apple returns HTML-escaped names ('Ausgaben &amp; Budget'). Undo that.

    Left escaped, the entity travels into keyword tables and metadata drafts,
    where '&amp;' would be pasted into a real App Store listing.
    """
    return html.unescape(text) if isinstance(text, str) else text


def autocomplete(term, country, cache=None):
    """Apple's search suggestions for `term` in `country`, best-ranked first."""
    query = urllib.parse.urlencode({"clientApplication": "Software", "f": "json", "term": term})
    body = _fetch(
        f"{HINTS_URL}?{query}",
        {"X-Apple-Store-Front": storefronts.header(country)},
        cache,
        HINTS_DELAY,
    )
    if not body:
        return []
    return [_clean(hint["searchTerm"]) for hint in body if "searchTerm" in hint]


def _clean_app(app):
    return {**app, "trackName": _clean(app.get("trackName"))}


def search(term, country, cache=None, limit=50):
    """Ranked apps for `term` in `country`."""
    query = urllib.parse.urlencode(
        {"term": term, "country": country, "entity": "software", "limit": limit}
    )
    body = _fetch(f"{SEARCH_URL}?{query}", {}, cache, SEARCH_DELAY)
    return [_clean_app(app) for app in (body or {}).get("results", [])]


def lookup(app_id, country, cache=None):
    """Current store listing for one app — used to read live metadata."""
    query = urllib.parse.urlencode({"id": app_id, "country": country, "entity": "software"})
    body = _fetch(f"https://itunes.apple.com/lookup?{query}", {}, cache, SEARCH_DELAY)
    results = (body or {}).get("results", [])
    return _clean_app(results[0]) if results else None
