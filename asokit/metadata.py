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
VERSION_FIELDS = frozenset(
    {"keywords", "description", "promotionalText", "whatsNew", "supportUrl", "marketingUrl"}
)
KNOWN_FIELDS = APP_INFO_FIELDS | VERSION_FIELDS

_WORD_SEPARATORS = ":,-–—/&|"

# Apple matches on stems, so `track` in a subtitle already covers `tracker` in
# the keyword field. Comparing exact strings misses the most common form of
# wasted budget.
#
# Morphology is per-language, so the rules are keyed by language. Applying
# English suffixes to every locale is worse than not stemming at all: it
# truncates German `zucker` to `zuck` and `wasser` to `wass`, inventing
# collisions between unrelated words while still missing the real German
# plurals, which are formed in `-en` and with umlaut. Languages we have no
# reliable rule for fall back to exact matching, and `metadata check` says so
# rather than presenting an English verdict on Greek.
#
# Rules are (suffix, replacement) tried in order. Kept deliberately
# conservative — regular plurals and agent nouns only — because over-stemming
# discards genuinely distinct words.
_RULES = {
    "en": (("ers", ""), ("er", ""), ("s", "")),
    # Regular -s / -es plurals. The 4-character remainder guard below keeps
    # short invariant nouns (Spanish `crisis`, `análisis`) intact.
    "es": (("es", ""), ("s", "")),
    "ca": (("es", ""), ("s", "")),
    "gl": (("es", ""), ("s", "")),
    # Portuguese -ção/-ções is the one irregular plural common enough in app
    # vocabulary to be worth a rule: without it `dejeções` never meets
    # `dejeção`.
    "pt": (("ões", "ão"), ("ães", "ão"), ("ãos", "ão"), ("es", ""), ("s", "")),
    "fr": (("x", ""), ("s", "")),
    # Dutch also pluralizes in -en, but stripping it wrecks ordinary stems
    # (`regen` -> `reg`), so only the -s plural is claimed.
    "nl": (("s", ""),),
    # Languages that do not mark plurals with a suffix at all. An empty rule
    # set is a positive statement — exact matching is CORRECT here, not a gap —
    # so these locales are not reported as unstemmed.
    "ja": (),
    "ko": (),
    "zh": (),
    "th": (),
    "vi": (),
    "id": (),
    "ms": (),
}


def language(locale):
    """The language subtag of an App Store locale: `pt-BR` -> `pt`."""
    if not isinstance(locale, str):
        return ""
    return locale.split("-")[0].split("_")[0].lower()


def stems_by_rule(locale):
    """True when we have morphology rules for `locale` — see `stem`."""
    return language(locale) in _RULES


def stem(word, locale=None):
    """Reduce `word` to the form Apple would match, per `locale`'s morphology.

    With no locale, or one we have no rules for, the word is returned unchanged.
    Exact matching under-reports collisions; guessing invents them.
    """
    for suffix, replacement in _RULES.get(language(locale), ()):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)] + replacement
    return word


def _stems(words, locale):
    return {stem(word, locale) for word in words}


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


# Any of these present means the locale is being localized rather than left to
# the primary language, so App Store Connect will store it — empty description
# included. See `_submission_problems`.
_LOCALIZED_MARKERS = ("name", "subtitle", "keywords")


def _submission_problems(locale, fields, strict):
    """Problems that block submission rather than merely wasting budget.

    App Store Connect does NOT fall back to the primary locale for fields you
    leave unfilled — it stores them empty, and a localization with an empty
    description cannot be submitted. The research -> metadata workflow produces
    exactly this state, because you localize name/subtitle/keywords from
    research data and leave the long-form copy alone. Nothing surfaces it until
    submission fails.
    """
    problems = []
    if not any(fields.get(field) for field in _LOCALIZED_MARKERS):
        return problems

    description = fields.get("description")
    if not (isinstance(description, str) and description.strip()):
        problems.append(
            f"{locale}: no description — App Store Connect stores localizations empty "
            "rather than falling back to your primary locale, and an empty description "
            "blocks submission. Run `asokit metadata pull` to capture what is already "
            "live, or pass --allow-partial if you are only updating other fields"
        )
    if strict:
        whats_new = fields.get("whatsNew")
        if not (isinstance(whats_new, str) and whats_new.strip()):
            problems.append(
                f"{locale}: no whatsNew — required on every localization of an update "
                "(not of a first version), and --strict asks for it"
            )
    return problems


def check(metadata, strict=False, allow_partial=False):
    """Validate {locale: {field: value}}. Returns a list of problem strings.

    `strict` also requires release notes. `allow_partial` drops the
    submission-completeness rules, for deliberately updating a subset of fields
    on a locale whose description is already live.
    """
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
        stems_elsewhere = _stems(indexed_elsewhere, locale)

        for term in keyword_terms(keywords):
            if term in indexed_elsewhere:
                problems.append(
                    f"{locale}: keyword '{term}' already appears in the name or subtitle — "
                    "Apple indexes all three fields together, so this is wasted budget"
                )
            elif stem(term, locale) in stems_elsewhere:
                twin = next(
                    w for w in sorted(indexed_elsewhere) if stem(w, locale) == stem(term, locale)
                )
                problems.append(
                    f"{locale}: keyword '{term}' shares a stem with '{twin}' in the name or "
                    "subtitle — Apple matches on stems, so this adds no new coverage"
                )

        for word in sorted(title_words & subtitle_words):
            problems.append(f"{locale}: '{word}' appears in both name and subtitle")
        for word in sorted(title_words):
            for other in sorted(subtitle_words):
                if word != other and stem(word, locale) == stem(other, locale):
                    problems.append(
                        f"{locale}: '{word}' (name) and '{other}' (subtitle) share a stem — "
                        "Apple matches on stems, so the second one buys nothing"
                    )

        duplicate_keywords = _duplicates(keyword_terms(keywords))
        for term in duplicate_keywords:
            problems.append(f"{locale}: keyword '{term}' listed more than once")

        if not allow_partial:
            problems.extend(_submission_problems(locale, fields, strict))

    return problems


def unstemmed_locales(metadata):
    """Locales checked by exact match because we have no morphology for them.

    `check` reports collisions for these too, but only identical words — the
    caller should say so rather than let silence read as a clean bill.
    """
    return sorted(locale for locale in metadata if not stems_by_rule(locale))


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
