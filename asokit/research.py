"""Keyword expansion and scoring.

Two phases:

  expand()  every seed -> Apple's autocomplete suggestions for that storefront,
            recording which seed surfaced each candidate and at what rank.

  score()   every candidate -> the ranked app list for it, reduced to a few
            honest signals.

What the scores are, precisely:

  popularity   Derived from autocomplete rank and how many different seeds
               surfaced a term. This is a RANKING PROXY, not search volume.
               Apple does not publish volume through any free endpoint, and
               any tool claiming otherwise from these sources is guessing.

  competition  Tier 1-5 from the median rating count of the top-5 apps. A
               keyword whose winners have 24 ratings is winnable; one whose
               winners have 100,000 is not.

  opportunity  popularity + (5 - competition) * 2. A blunt sort key, not a
               verdict. Read the table, don't just take the top row.
"""

import statistics

from . import sources

# Punctuation apps use to join a name to a tagline. The full-width and CJK
# marks matter: Japanese and Chinese listings separate with '・' and '：'
# rather than ':' , and missing them lets app names through as keywords.
APP_NAME_PUNCTUATION = (":", "—", " - ", ".", "・", "：", "｜", "|", "–", "、")


def expand(seeds, country, cache=None, progress=None):
    """Returns {candidate: [[seed, rank], ...]} — the autocomplete evidence."""
    evidence = {}
    for seed in seeds:
        suggestions = sources.autocomplete(seed, country, cache)
        if progress:
            progress(seed, len(suggestions))
        for rank, term in enumerate(suggestions, start=1):
            evidence.setdefault(term.lower(), []).append([seed, rank])
    for seed in seeds:
        evidence.setdefault(seed.lower(), [])
    return evidence


def competition_tier(median_ratings):
    """1 (wide open) to 5 (dominated by household names)."""
    for tier, floor in ((5, 100_000), (4, 10_000), (3, 1_000), (2, 100)):
        if median_ratings >= floor:
            return tier
    return 1


def is_app_name(term, top_apps, exact_title_matches, seeds_lower):
    """True when a candidate is really a competitor's app name.

    Autocomplete mixes brand names in with generic queries: in the US store
    `mint` leads with Mint Mobile, a wireless carrier, not a budget app.
    Targeting those chases someone else's brand rather than demand.

    Two signals: app-name punctuation (`Spendee — Budget Tracker`), and a
    top-3 app whose title IS the term while no second app competes for it.

    An exact seed is never treated as a brand query — an app named "Budget
    Tracker" does not make `budget tracker` a brand term. Topical relevance
    (is a phone plan relevant to a budgeting app?) is deliberately left to
    human review; no heuristic settles it.
    """
    candidate = term.lower().strip()
    if any(mark in candidate for mark in APP_NAME_PUNCTUATION):
        return True
    if candidate in seeds_lower or exact_title_matches > 1:
        return False
    for app in top_apps[:3]:
        title = (app.get("trackName") or "").lower()
        head = title.split(":")[0].split(" - ")[0].split("—")[0].strip()
        if head and (
            head == candidate
            or candidate.startswith(head + " ")
            or head.startswith(candidate + " ")
        ):
            return True
    return False


def is_off_category(top_apps, our_genre):
    """True when the apps answering this query are in a different category.

    Catches the false positives no keyword score can: in the US store `moodle`
    looks like a strong mood keyword but returns Education apps, `self-help
    credit union` returns Finance, and `manic emu` returns Games. If none of
    the top-ranked apps share our category, the query belongs to a different
    audience however good its numbers look.

    Needs `our_genre`, so it only applies when an appId is configured.
    """
    if not our_genre:
        return False
    genres = [app.get("primaryGenreName") for app in top_apps[:5] if app.get("primaryGenreName")]
    if not genres:
        return False
    return our_genre not in genres


def score(
    term,
    evidence,
    country,
    app_id=None,
    cache=None,
    seeds_lower=frozenset(),
    our_genre=None,
):
    """Reduce one candidate to its signals. `evidence` is expand()'s value."""
    results = sources.search(term, country, cache)
    top_ten = results[:10]
    top_five_ratings = [app.get("userRatingCount", 0) for app in top_ten[:5]]
    median_ratings = int(statistics.median(top_five_ratings)) if top_five_ratings else 0

    our_rank = None
    if app_id:
        our_rank = next(
            (i for i, app in enumerate(results, start=1) if app.get("trackId") == app_id), None
        )

    exact_title_matches = sum(1 for app in top_ten if term in (app.get("trackName") or "").lower())
    best_rank = min((rank for _, rank in evidence), default=None)
    seed_breadth = len({seed for seed, _ in evidence})

    popularity = (11 - best_rank) if best_rank else 0
    popularity += min(max(seed_breadth - 1, 0), 3)
    competition = competition_tier(median_ratings)

    return {
        "term": term,
        "looksLikeAppName": is_app_name(term, top_ten, exact_title_matches, seeds_lower),
        "offCategory": is_off_category(top_ten, our_genre),
        "topGenres": sorted(
            {app.get("primaryGenreName") for app in top_ten[:5] if app.get("primaryGenreName")}
        ),
        "popularity": popularity,
        "autocompleteBestRank": best_rank,
        "seedBreadth": seed_breadth,
        "competitionTier": competition,
        "medianTop5Ratings": median_ratings,
        "exactTitleMatches": exact_title_matches,
        "ourRank": our_rank,
        "opportunity": popularity + (5 - competition) * 2,
        "topApps": [
            {
                "name": app.get("trackName"),
                "ratings": app.get("userRatingCount", 0),
                "rating": app.get("averageUserRating"),
                "id": app.get("trackId"),
            }
            for app in top_ten[:5]
        ],
    }


def rank_candidates(evidence, limit, seeds_lower=frozenset()):
    """Top `limit` candidates by autocomplete rank, then breadth.

    Seeds are always scored even when they fall outside the limit — you need
    your starting terms in the table to see where you already rank.
    """
    ordered = sorted(
        evidence.items(),
        key=lambda item: (min((rank for _, rank in item[1]), default=99), -len(item[1])),
    )
    chosen = [term for term, _ in ordered[:limit]]
    chosen += [seed for seed in seeds_lower if seed not in chosen and seed in evidence]
    return chosen
