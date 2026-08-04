"""App Store storefront IDs and locale mapping.

The autocomplete endpoint selects a country via the `X-Apple-Store-Front`
header, formatted `<storefrontId>-<languageIndex>,29`. The language index is
not meaningful for keyword hints: `143462-1,29` and `143462-4,29` (Japan)
return byte-identical results, as do `143444-2,29` and `143444-4,29` (UK).
So this module emits `-4,29` universally. Verified 2026-08-03 across US, GB,
DE, FR, ES, IT, BR, MX, NL, SE, DK, PL, JP, KR, CN.

The `cc=` query parameter that appears in older blog posts does NOT work — it
is accepted and silently returns US results.
"""

# country code -> (storefront id, display name, default App Store Connect locale)
STOREFRONTS = {
    "us": (143441, "United States", "en-US"),
    "gb": (143444, "United Kingdom", "en-GB"),
    "ca": (143455, "Canada", "en-CA"),
    "au": (143460, "Australia", "en-AU"),
    "nz": (143461, "New Zealand", "en-AU"),
    "ie": (143449, "Ireland", "en-GB"),
    "de": (143443, "Germany", "de-DE"),
    "at": (143445, "Austria", "de-DE"),
    "ch": (143459, "Switzerland", "de-DE"),
    "fr": (143442, "France", "fr-FR"),
    "be": (143446, "Belgium", "fr-FR"),
    "lu": (143451, "Luxembourg", "fr-FR"),
    "it": (143450, "Italy", "it"),
    "es": (143454, "Spain", "es-ES"),
    "pt": (143453, "Portugal", "pt-PT"),
    "nl": (143452, "Netherlands", "nl-NL"),
    "se": (143456, "Sweden", "sv"),
    "dk": (143458, "Denmark", "da"),
    "no": (143457, "Norway", "no"),
    "fi": (143447, "Finland", "fi"),
    "is": (143558, "Iceland", "en-US"),
    "pl": (143478, "Poland", "pl"),
    "cz": (143489, "Czechia", "cs"),
    "sk": (143496, "Slovakia", "sk"),
    "hu": (143482, "Hungary", "hu"),
    "ro": (143487, "Romania", "ro"),
    "bg": (143526, "Bulgaria", "en-US"),
    "hr": (143494, "Croatia", "hr"),
    "si": (143499, "Slovenia", "en-US"),
    "gr": (143448, "Greece", "el"),
    "ee": (143518, "Estonia", "en-US"),
    "lv": (143519, "Latvia", "en-US"),
    "lt": (143520, "Lithuania", "en-US"),
    "ua": (143492, "Ukraine", "uk"),
    "ru": (143469, "Russia", "ru"),
    "tr": (143480, "Turkey", "tr"),
    "il": (143491, "Israel", "he"),
    "sa": (143479, "Saudi Arabia", "ar-SA"),
    "ae": (143481, "United Arab Emirates", "ar-SA"),
    "eg": (143516, "Egypt", "ar-SA"),
    "za": (143472, "South Africa", "en-GB"),
    "jp": (143462, "Japan", "ja"),
    "kr": (143466, "South Korea", "ko"),
    "cn": (143465, "China mainland", "zh-Hans"),
    "tw": (143470, "Taiwan", "zh-Hant"),
    "hk": (143463, "Hong Kong", "zh-Hant"),
    "sg": (143464, "Singapore", "en-GB"),
    "my": (143473, "Malaysia", "ms"),
    "id": (143476, "Indonesia", "id"),
    "th": (143475, "Thailand", "th"),
    "vn": (143471, "Vietnam", "vi"),
    "ph": (143474, "Philippines", "en-GB"),
    "in": (143467, "India", "hi"),
    "br": (143503, "Brazil", "pt-BR"),
    "mx": (143468, "Mexico", "es-MX"),
    "ar": (143505, "Argentina", "es-MX"),
    "cl": (143483, "Chile", "es-MX"),
    "co": (143501, "Colombia", "es-MX"),
    "pe": (143507, "Peru", "es-MX"),
    "ve": (143502, "Venezuela", "es-MX"),
}


class UnknownStorefront(Exception):
    pass


def header(country):
    """X-Apple-Store-Front header value for a two-letter country code."""
    code = country.lower()
    if code not in STOREFRONTS:
        raise UnknownStorefront(
            f"unknown country '{country}'. Known: {', '.join(sorted(STOREFRONTS))}.\n"
            "Storefront IDs are numeric and stable; add one to STOREFRONTS if missing, "
            "then confirm it with `asokit storefronts --check <cc>`."
        )
    return f"{STOREFRONTS[code][0]}-4,29"


def name(country):
    return STOREFRONTS[country.lower()][1]


def default_locale(country):
    """Best-guess App Store Connect locale. Override per market in config."""
    return STOREFRONTS[country.lower()][2]
