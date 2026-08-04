"""App Store metadata limits and the rules that are easy to get wrong.

The expensive mistake in App Store metadata is repetition. Apple indexes the
app name, subtitle, and keyword field as ONE pool and combines words across
them. Repeating a term in the keyword field that already appears in the title
buys nothing and burns characters you cannot get back — the keyword field is
only 100 characters.

Everything here is pure: no network, no credentials. `check()` is the gate to
run before any upload.
"""

LIMITS = {
    "name": 30,
    "subtitle": 30,
    "keywords": 100,
    "promotionalText": 170,
    "description": 4000,
}

APP_INFO_FIELDS = frozenset({"name", "subtitle", "privacyPolicyUrl"})
VERSION_FIELDS = frozenset({"keywords", "description", "promotionalText", "whatsNew"})
KNOWN_FIELDS = APP_INFO_FIELDS | VERSION_FIELDS

_WORD_SEPARATORS = ":,-–—/&|"

# Apple matches on stems, so `track` in a subtitle already covers `tracker` in
# the keyword field. Comparing exact strings misses the most common form of
# wasted budget. This is deliberately conservative — plurals and agent nouns
# only — because over-stemming would flag genuinely distinct words.
_SUFFIXES = ("ers", "er", "s")


def stem(word):
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _stems(words):
    return {stem(word) for word in words}


def _words(text):
    if not isinstance(text, str):
        return set()
    cleaned = text.lower()
    for separator in _WORD_SEPARATORS:
        cleaned = cleaned.replace(separator, " ")
    return {word for word in cleaned.split() if word}


def keyword_terms(keywords):
    """Terms in a keyword field. Apple splits on commas, not spaces."""
    if not isinstance(keywords, str):
        return []
    return [term.strip().lower() for term in keywords.split(",") if term.strip()]


def check(metadata):
    """Validate {locale: {field: value}}. Returns a list of problem strings."""
    problems = []
    for locale, fields in sorted(metadata.items()):
        for field, value in fields.items():
            if field not in KNOWN_FIELDS:
                problems.append(f"{locale}: unknown field '{field}'")
                continue
            if not isinstance(value, str):
                problems.append(f"{locale}.{field}: expected text, got {type(value).__name__}")
                continue
            limit = LIMITS.get(field)
            if limit and len(value) > limit:
                problems.append(
                    f"{locale}.{field}: {len(value)} characters, limit is {limit}"
                )

        keywords = fields.get("keywords", "")
        if not isinstance(keywords, str):
            keywords = ""
        if " ," in keywords or ", " in keywords:
            problems.append(
                f"{locale}.keywords: spaces around commas waste characters "
                "(use `a,b,c` not `a, b, c`)"
            )

        title_words = _words(fields.get("name", ""))
        subtitle_words = _words(fields.get("subtitle", ""))
        indexed_elsewhere = title_words | subtitle_words
        stems_elsewhere = _stems(indexed_elsewhere)

        for term in keyword_terms(keywords):
            if term in indexed_elsewhere:
                problems.append(
                    f"{locale}: keyword '{term}' already appears in the name or subtitle — "
                    "Apple indexes all three fields together, so this is wasted budget"
                )
            elif stem(term) in stems_elsewhere:
                twin = next(w for w in sorted(indexed_elsewhere) if stem(w) == stem(term))
                problems.append(
                    f"{locale}: keyword '{term}' shares a stem with '{twin}' in the name or "
                    "subtitle — Apple matches on stems, so this adds no new coverage"
                )

        for word in sorted(title_words & subtitle_words):
            problems.append(f"{locale}: '{word}' appears in both name and subtitle")
        for word in sorted(title_words):
            for other in sorted(subtitle_words):
                if word != other and stem(word) == stem(other):
                    problems.append(
                        f"{locale}: '{word}' (name) and '{other}' (subtitle) share a stem — "
                        "Apple matches on stems, so the second one buys nothing"
                    )

        duplicate_keywords = _duplicates(keyword_terms(keywords))
        for term in duplicate_keywords:
            problems.append(f"{locale}: keyword '{term}' listed more than once")

    return problems


def _duplicates(terms):
    seen, repeated = set(), []
    for term in terms:
        if term in seen and term not in repeated:
            repeated.append(term)
        seen.add(term)
    return repeated


def usage(metadata):
    """Character usage per locale per field, for display."""
    report = {}
    for locale, fields in metadata.items():
        report[locale] = {
            field: (len(value), LIMITS.get(field))
            for field, value in fields.items()
            if isinstance(value, str)
        }
    return report
