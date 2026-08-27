"""Pack scored keyword candidates into an App Store keyword field.

This is the step between `research` and `metadata check`, and it is where the
real difficulty lives: fitting terms into 100 characters without wasting
budget. Left to the caller, everyone reimplements it and everyone hits the
same four defects — stopwords eating characters, competitor brand fragments
arriving as words split out of rival app names, a tokenizer that destroys
combining-mark scripts, and silent loss of incumbent terms that were already
ranking.

Apple indexes name + subtitle + keywords as one pool and forms combinations
across them, so multi-word phrases in the keyword field waste characters:
listing `stool tracker` and `poop tracker` buys `tracker` twice. This splits
candidates into individual words, drops anything the name or subtitle already
covers, and greedily fills the budget by opportunity.

Matching is stem-based because Apple's is, and stemming is delegated to
`metadata.stem` so it stays per-locale rather than applying English morphology
to every storefront.

Pure: no I/O, no network.
"""

import re

from .metadata import stem

# Split on separators and keep everything else, rather than matching "word
# characters". Python's \\w excludes nonspacing combining marks — 'ู'.isalnum()
# is False — so a \\w-based tokenizer shreds Thai and Devanagari at every tone
# mark and matra ("บันทึกการขับถ่าย" -> ['บ','นท','กการข','บถ','าย']). Splitting
# instead keeps marks attached to their base characters.
#
# Consequence for scripts written without spaces (Thai, Chinese, Japanese): a
# phrase stays ONE token. That is deliberate — segmenting them needs a
# dictionary we do not have, and guessing would produce nonsense keywords.
#
# Digits survive: "bristol 7" and "type 3" are real search terms.
SEPARATORS = re.compile(
    r"[\s,\-‐-―/\\&|:;·・()\[\]{}<>\"'‘’“”_`~!?.。、…+*=@#$%^]+"
)

# Latin letters including Latin-1 Supplement and Latin Extended-A/B. Decides
# whether the Latin-only rules below may touch a word at all.
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")

# CJK terms are legitimately one or two characters, so a blanket minimum guts
# those locales. Gated behind `is_latin`.
MIN_LATIN_LENGTH = 3

# Function words and generic store filler: no targeting value, real character
# cost. Applied to Latin-script words only — there is no comparable list for
# CJK, Arabic, Hebrew, Greek, Cyrillic or Thai, and guessing would delete real
# terms. Under-filtering wastes a few characters; over-filtering deletes the
# keyword you were trying to rank for.
_ENGLISH_FILLER = frozenset({
    "the", "a", "an", "and", "or", "for", "with", "without", "from", "at", "as",
    "your", "my", "our", "free", "app", "pro", "plus", "premium", "lite", "best",
    "new", "to", "of", "in", "on", "by", "it", "is", "are", "be", "this", "that",
    "you", "me", "we", "all", "any", "get", "now", "top", "easy", "simple",
    "daily", "how", "what", "when", "why", "who", "can", "not",
})

# The English set is applied in every Latin-script storefront, not just English
# ones: users in many stores search in English, so English filler turns up in
# any market's candidate pool. Per-language sets are added on top.
_LANGUAGE_FILLER = {
    "de": frozenset({
        "der", "die", "das", "den", "dem", "und", "für", "mit", "dein", "deine",
        "mein", "meine", "kostenlos", "einfach", "app",
    }),
    "es": frozenset({
        "de", "la", "el", "los", "las", "un", "una", "y", "para", "con", "por",
        "gratis", "tu", "mi",
    }),
    "pt": frozenset({
        "de", "da", "do", "das", "dos", "a", "o", "as", "os", "um", "uma", "e",
        "para", "com", "por", "grátis", "gratis", "seu", "sua", "meu", "minha",
    }),
    "fr": frozenset({
        "de", "du", "des", "le", "la", "les", "un", "une", "et", "pour", "avec",
        "votre", "mon", "ma", "gratuit",
    }),
    "it": frozenset({
        "di", "del", "della", "il", "lo", "la", "i", "gli", "le", "un", "una",
        "e", "per", "con", "gratis", "tuo", "mio",
    }),
    "nl": frozenset({
        "de", "het", "een", "en", "van", "voor", "met", "je", "jouw", "mijn",
        "gratis",
    }),
    "sv": frozenset({"och", "för", "med", "din", "att", "en", "ett", "gratis"}),
    "da": frozenset({"og", "for", "med", "din", "at", "en", "et", "gratis"}),
    "no": frozenset({"og", "for", "med", "din", "å", "en", "et", "gratis"}),
    "pl": frozenset({"i", "w", "na", "do", "dla", "za", "darmo", "darmowy"}),
    "tr": frozenset({"ve", "ile", "için", "bir", "ücretsiz"}),
}

# Legal-entity suffixes. These reach the candidate pool as words split out of
# developer and app names in every storefront, and they are Latin-script
# wherever they appear, so they are filtered regardless of locale.
_CORPORATE = frozenset({"inc", "ltd", "llc", "gmbh", "uab", "sarl", "bv", "ab", "oy", "co"})


def language_filler(locale):
    """The stopword set applied to Latin-script words in `locale`."""
    subtag = (locale or "").split("-")[0].split("_")[0].lower()
    return _ENGLISH_FILLER | _CORPORATE | _LANGUAGE_FILLER.get(subtag, frozenset())


def words(text):
    """Lowercased tokens. See SEPARATORS for why this is not a \\w match."""
    return [w for w in (token.lower() for token in SEPARATORS.split(text or "")) if w]


def is_latin(word):
    """True when the word contains Latin letters, so Latin-only rules apply.

    Digit-only tokens are deliberately NOT Latin: the `7` of `bristol 7` has to
    survive the minimum-length rule.
    """
    return bool(_LATIN.search(word))


def normalize(text):
    """Lowercase, separators stripped, whitespace collapsed.

    `Poop Tracker - Balloon` and `poop tracker  balloon` both become
    `poop tracker balloon`, so a term can be compared against an app name.
    """
    return " ".join(words(text))


def app_names(candidates):
    """Normalized competitor app names, from flagged terms and `topApps`."""
    names = {normalize(item.get("term")) for item in candidates if item.get("looksLikeAppName")}
    names.update(
        normalize(app.get("name"))
        for item in candidates
        for app in (item.get("topApps") or [])
    )
    names.discard("")
    return names


def names_an_app(term, names):
    """True when this term IS a competitor app name rather than ordinary usage.

    Equality, plus the app name appearing whole inside the term. Containment
    runs in that direction only: a long app name must not swallow a short
    generic term, or `Poop Tracker Pro` disqualifies `poop tracker` and costs
    you your two best words. Containment is limited to multi-word app names for
    the same reason — a competitor merely named `Balloon` should not
    disqualify every term that uses the word.
    """
    if term in names:
        return True
    padded = f" {term} "
    return any(len(name.split()) > 1 and f" {name} " in padded for name in names)


def brand_words(candidates):
    """Words that only ever occur inside app names.

    `looksLikeAppName` filters at term level, so splitting phrases into words
    still leaks fragments of rival app names — `balloon`, `uab`, `couple` — into
    the keyword field, which is where trademark trouble starts.

    A word is brand-ish if it appears in a `looksLikeAppName` term or in any
    candidate's `topApps[].name`, AND never appears in an ordinary candidate
    term. A term that normalizes to a competitor app name does not count as
    ordinary usage — `poop tracker - balloon` is a competitor, so it cannot
    vouch for `balloon`. Words like `poop` and `tracker` still vouch for
    themselves through genuine queries, so they stay.
    """
    names = app_names(candidates)
    from_names = {word for name in names for word in name.split()}
    from_terms = set()
    for item in candidates:
        if item.get("looksLikeAppName"):
            continue
        term = normalize(item.get("term"))
        if names_an_app(term, names):
            continue
        from_terms.update(term.split())
    return frozenset(from_names - from_terms)


def is_noise(word, brands, filler, blocked=frozenset(), locale=None):
    """True when a word should never enter the keyword field."""
    if word in blocked or word in brands:
        return True
    if is_latin(word):
        # Raw and stemmed, so a singular entry in the list also catches its
        # plural. Stemming stays locale-keyed for the same reason it does in
        # `metadata`: English morphology applied to German invents matches.
        if word in filler or stem(word, locale) in filler:
            return True
        if len(word) < MIN_LATIN_LENGTH:
            return True
    return False


def incumbent_candidates(keywords):
    """Live keyword terms as low-priority candidates.

    Research-only selection quietly discards proven vocabulary: a hand-picked
    term that is already live and ranking gets dropped because autocomplete
    never proposed it. Joining the pool at `opportunity: 0` means researched
    terms win the early slots and incumbents fill whatever budget is left.
    Terms the name or subtitle already cover are still dropped by the packer as
    usual, so this does not reintroduce duplication.
    """
    return [
        {
            "term": term.strip(),
            "opportunity": 0,
            "competitionTier": 9,
            "offCategory": False,
            "looksLikeAppName": False,
            "topApps": [],
        }
        for term in (keywords or "").split(",")
        if term.strip()
    ]


def packed_words(candidates, name, subtitle, limit=100, blocked=frozenset(), locale=None):
    """Ordered, deduplicated words that fit the keyword budget.

    `blocked` is a curated set of exact lowercase words to drop, applied in
    every script. It is the lever for junk no heuristic reaches — a beverage
    brand surfacing in a health-category autocomplete is not off-category by
    Apple's genre data and is not an app name, but it is still not a keyword
    you want.
    """
    filler = language_filler(locale)
    covered = {stem(word, locale) for word in words(name) + words(subtitle)}
    brands = brand_words(candidates)
    usable = [
        item
        for item in candidates
        if not item.get("offCategory") and not item.get("looksLikeAppName")
    ]
    usable.sort(key=lambda item: (-item.get("opportunity", 0), item.get("competitionTier", 9)))

    chosen, used = [], 0
    for item in usable:
        for word in words(item.get("term")):
            if is_noise(word, brands, filler, blocked, locale):
                continue
            root = stem(word, locale)
            if root in covered:
                continue
            cost = len(word) + (1 if chosen else 0)
            if used + cost > limit:
                continue
            chosen.append(word)
            covered.add(root)
            used += cost
    return chosen


def select_keywords(candidates, name, subtitle, limit=100, blocked=frozenset(), locale=None):
    """The keyword field itself: comma-separated, no spaces, within `limit`."""
    return ",".join(packed_words(candidates, name, subtitle, limit, blocked, locale))
