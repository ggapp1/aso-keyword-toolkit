"""Derive starter seed keywords from an app that already exists in the store.

Inventing seed keywords from a blank page is the hardest part of starting ASO
work, and getting it wrong quietly caps everything downstream. This reads the
app's own listing and the listings of apps that rank alongside it, then
proposes seeds from what those apps actually call themselves.

Output is a starting point, not an answer — the point is to get a useful first
run in one command instead of a staring contest with an empty config.
"""

import re
from collections import Counter

from . import sources

# Words that carry no targeting value in an app title, across the languages
# most likely to appear in a first run. Not exhaustive by design: over-filtering
# hides real keywords, and the researcher reviews the list anyway.
STOPWORDS = {
    # English
    "the", "a", "an", "and", "or", "for", "your", "my", "app", "free", "pro",
    "plus", "premium", "lite", "best", "new", "with", "to", "of", "in", "on",
    "by", "it", "is", "you", "me", "we", "all", "get", "now", "top", "easy",
    "simple", "daily", "my", "our",
    # German
    "der", "die", "das", "und", "für", "mit", "dein", "deine", "mein", "meine",
    "kostenlos", "einfach",
    # Romance
    "de", "la", "el", "los", "las", "y", "e", "o", "os", "as", "para", "con",
    "du", "le", "les", "des", "et", "pour", "avec", "il", "lo", "gratis",
    "gratuit", "grátis",
    # Nordic / Dutch
    "og", "för", "med", "din", "att", "en", "het", "van", "voor", "je",
}

TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _tokens(text):
    return [word.lower() for word in TOKEN.findall(text or "")]


def _meaningful(words):
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


def _phrases(words):
    """Adjacent pairs — 'expense tracker' matters more than 'expense' and 'tracker'."""
    return [f"{a} {b}" for a, b in zip(words, words[1:])]


def from_app(app_id, country, cache=None, limit=14):
    """Suggest seeds for `app_id` in `country`.

    Returns (seeds, context) where context describes what was read, so the
    caller can show its work rather than presenting magic.
    """
    app = sources.lookup(app_id, country, cache)
    if not app:
        raise LookupError(
            f"app {app_id} is not available in the {country} store. "
            "Check the ID (the number in your App Store URL) and the country."
        )

    own_title = app.get("trackName", "")
    genre = app.get("primaryGenreName", "")
    own_words = _meaningful(_tokens(own_title))

    # The app's own title, minus its brand name, is the most reliable probe we
    # have for "what is this app". Brand is assumed to be the rarest token, so
    # probe with the descriptive remainder.
    probes = []
    if own_words:
        probes.append(" ".join(own_words[:3]))
        if len(own_words) > 1:
            probes.append(" ".join(own_words[:2]))
    if not probes and genre:
        # Last resort only. A category name is not a search term: probing
        # "Finance" for a budgeting app returns banks and trading platforms.
        probes.append(genre.lower())

    title_words = Counter()
    phrase_counts = Counter()
    competitors = []
    seen_probes = set()

    for probe in probes:
        if probe in seen_probes:
            continue
        seen_probes.add(probe)
        for result in sources.search(probe, country, cache, limit=25):
            if result.get("trackId") == app_id:
                continue
            title = result.get("trackName", "")
            competitors.append(title)
            words = _meaningful(_tokens(title))
            title_words.update(set(words))
            phrase_counts.update(set(_phrases(words)))

    seeds = []
    for phrase, count in phrase_counts.most_common():
        if count >= 2 and phrase not in seeds:
            seeds.append(phrase)
        if len(seeds) >= limit // 2:
            break
    for word, count in title_words.most_common():
        if count >= 2 and not any(word in seed.split() for seed in seeds):
            seeds.append(word)
        if len(seeds) >= limit:
            break

    for word in own_words:
        if word not in seeds and len(seeds) < limit + 3:
            seeds.append(word)

    context = {
        "app": own_title,
        "genre": genre,
        "probes": list(seen_probes),
        "competitorsRead": len(competitors),
    }
    return seeds, context
