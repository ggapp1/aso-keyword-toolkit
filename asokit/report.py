"""Markdown rendering of a research run."""

METHODOLOGY = """\
Methodology: `pop` is an autocomplete-derived ranking proxy (best suggestion
rank across seeds, plus a breadth bonus) — Apple's own per-storefront ordering.
It is **not** search volume; no free Apple endpoint exposes volume. `comp` is a
1-5 tier from the median rating count of the top-5 ranked apps. `opp` is
`pop + (5 - comp) * 2`, a sort key rather than a verdict.

Terms flagged as competitor app names are listed separately — they are intel,
not targets. Topical relevance is still yours to judge: a keyword can look
strong and serve an entirely different audience.\
"""

TABLE_HEADER = (
    "| # | keyword | pop | ac-rank | seeds | comp | median top-5 ratings | "
    "exact-title | our rank | opp |\n"
    "|---|---------|-----|---------|-------|------|----------------------|"
    "-------------|----------|-----|"
)


def render(country_name, country_code, app_label, scores):
    lines = [
        f"# App Store keyword research — {country_name} ({country_code})",
        "",
        f"App: {app_label}",
        "",
        METHODOLOGY,
        "",
        "## Targetable keywords",
        "",
        TABLE_HEADER,
    ]

    generic = [
        score
        for score in scores
        if not score["looksLikeAppName"] and not score.get("offCategory")
    ]
    brand = [score for score in scores if score["looksLikeAppName"]]
    off_category = [
        score
        for score in scores
        if score.get("offCategory") and not score["looksLikeAppName"]
    ]

    for index, score in enumerate(sorted(generic, key=lambda s: -s["opportunity"]), start=1):
        lines.append(
            f"| {index} | {score['term']} | {score['popularity']} "
            f"| {score['autocompleteBestRank'] or '—'} | {score['seedBreadth']} "
            f"| {score['competitionTier']} | {score['medianTop5Ratings']:,} "
            f"| {score['exactTitleMatches']} | {score['ourRank'] or '—'} "
            f"| {score['opportunity']} |"
        )

    if off_category:
        lines += [
            "",
            "## Off-category (excluded — different audience)",
            "",
            "Scored well, but the apps answering these queries are in another App Store",
            "category. Ranking here buys traffic that will not convert.",
            "",
            "| term | pop | comp | who actually ranks |",
            "|------|-----|------|--------------------|",
        ]
        for score in sorted(off_category, key=lambda s: -s["opportunity"]):
            genres = ", ".join(score.get("topGenres") or []) or "—"
            lines.append(
                f"| {score['term']} | {score['popularity']} | {score['competitionTier']} | {genres} |"
            )

    if brand:
        lines += [
            "",
            "## Competitor app names (excluded from targeting)",
            "",
            "| term | our rank | top result |",
            "|------|----------|------------|",
        ]
        for score in sorted(brand, key=lambda s: -s["opportunity"]):
            top = score["topApps"][0]["name"] if score["topApps"] else "—"
            lines.append(f"| {score['term']} | {score['ourRank'] or '—'} | {top} |")

    lines += [
        "",
        "## Competitors seen across these queries",
        "",
        "A rival's title is their keyword bet — read this as strategy, not just ranking.",
        "",
        "| app | ratings | top-5 appearances | best rank |",
        "|-----|---------|-------------------|-----------|",
    ]
    for competitor in _competitors(scores):
        lines.append(
            f"| {competitor['name']} | {competitor['ratings']:,} "
            f"| {competitor['hits']} | {competitor['bestRank']} |"
        )

    return "\n".join(lines) + "\n"


def _competitors(scores, limit=20):
    seen = {}
    for score in scores:
        for rank, app in enumerate(score["topApps"], start=1):
            entry = seen.setdefault(
                app["id"],
                {"name": app["name"], "ratings": app["ratings"], "hits": 0, "bestRank": rank},
            )
            entry["hits"] += 1
            entry["bestRank"] = min(entry["bestRank"], rank)
    return sorted(seen.values(), key=lambda item: -item["hits"])[:limit]
