# asokit/cpp.py
"""Custom product pages as code: load, expand, validate and plan `cpp.json`.

Pure — no network. `cpp_apply.py` snapshots live state and executes the plans
built here. Format (see the spec for the full schema):

  {"protectedKeywords": {"*": [...], "en-US": [...]},
   "pages": [{"name": "...", "template": "appStoreVersion", "deepLink": null,
              "locales": {"en-US": {"promotionalText": "...", "keywords": [...],
                                    "screenshots": [{"dir", "order", "display"}],
                                    "creative": "<variant>"},
                          "en-GB": {"same": "en-US", "keywords": [...]}}}]}
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from . import creative
from . import screenshots as shots
from .library import HEADER, SEARCH, SCREENSHOT, reference_name

MAX_PAGES = 70
NAME_MAX = 30
PROMO_MAX = 170
EDITABLE = frozenset({"PREPARE_FOR_SUBMISSION", "REJECTED", "READY_FOR_REVIEW"})
LOCKED = frozenset({"WAITING_FOR_REVIEW", "IN_REVIEW"})
LIVE = frozenset({"ACCEPTED", "APPROVED"})
COPIED = ("promotionalText", "screenshots", "creative")
LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$")


class CppError(ValueError):
    pass


def load(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc["_root"] = Path(path).resolve().parent
    return doc


def norm(keyword):
    return " ".join(keyword.split()).casefold()


def expand(doc):
    pages = []
    for raw_page in doc.get("pages", []):
        raw = raw_page.get("locales", {})
        locales = {}
        for locale, entry in raw.items():
            if "same" in entry:
                target = raw.get(entry["same"])
                if target is None or "same" in target:
                    raise CppError(f"{raw_page.get('name')}: {locale} 'same' must name a locale with its own entry")
                resolved = {key: target.get(key) for key in COPIED}
                resolved.update({key: value for key, value in entry.items() if key in COPIED})
            else:
                resolved = {key: entry.get(key) for key in COPIED}
            resolved["keywords"] = [k.strip() for k in entry.get("keywords", []) if k.strip()]
            resolved["screenshots"] = resolved.get("screenshots") or []
            locales[locale] = resolved
        pages.append({"name": raw_page.get("name", ""), "deepLink": raw_page.get("deepLink"),
                      "template": raw_page.get("template"), "locales": locales})
    return pages


def select_screenshots(entry, root):
    directory = Path(root) / entry["dir"]
    if not directory.is_dir():
        raise CppError(f"screenshot dir {entry['dir']} does not exist")
    files = sorted(p for p in directory.iterdir() if p.suffix.lower() == ".png" and not p.name.startswith(("_", ".")))
    if not entry.get("order"):
        return files
    chosen = []
    for prefix in entry["order"]:
        hits = [p for p in files if p.name.startswith(prefix)]
        if len(hits) != 1:
            raise CppError(f"{entry['dir']}: order prefix '{prefix}' matches {len(hits)} files, expected 1")
        chosen.append(hits[0])
    return chosen


def creative_path(doc, creative_root, variant, locale):
    return Path(doc["_root"]) / creative_root / variant / f"{locale}.png"


def _protected(doc, locale):
    table = doc.get("protectedKeywords", {})
    return {norm(k) for k in table.get("*", []) + table.get(locale, [])}


def check(doc, creative_root="assets-out", allow_protected=(), lint=True, online=None):
    problems, warnings = [], []
    try:
        pages = expand(doc)
    except CppError as error:
        return [str(error)], []
    names = [p["name"] for p in pages]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"page name '{name}' appears more than once")
    allow = {norm(k) for k in allow_protected}
    owner = {}
    if online:
        for live_name, by_locale in online["live_keywords"].items():
            if live_name in names:
                continue
            for locale, keywords in by_locale.items():
                for keyword in keywords:
                    owner[(locale, keyword)] = live_name

    for page in pages:
        name = page["name"]
        if not name or len(name) > NAME_MAX:
            problems.append(f"page name '{name}' must be 1–{NAME_MAX} characters")
        if page["deepLink"]:
            if not urlparse(page["deepLink"]).scheme:
                problems.append(f"{name}: deepLink '{page['deepLink']}' has no scheme")
            else:
                warnings.append(f"{name}: deep-link changes require App Review before they work")
        declared_families = set()
        for locale, entry in sorted(page["locales"].items()):
            where = f"{name} {locale}"
            if not LOCALE_RE.match(locale):
                problems.append(f"{where}: '{locale}' is not an App Store Connect locale code")
            promo = entry.get("promotionalText") or ""
            if len(promo) > PROMO_MAX:
                problems.append(f"{where}: promotionalText is {len(promo)} characters, limit {PROMO_MAX}")
            if lint and promo:
                problems += [f"{where}: {hit}" for hit in creative.lint(promo, locale)]
            for shot in entry["screenshots"]:
                declared_families.add(shot.get("display"))
                try:
                    files = select_screenshots(shot, doc["_root"])
                except CppError as error:
                    problems.append(f"{where}: {error}")
                    continue
                problems += [f"{name}: {p}" for p in shots.check({locale: {shot["display"]: files}})]
            if entry.get("creative"):
                path = creative_path(doc, creative_root, entry["creative"], locale)
                if not path.exists():
                    problems.append(f"{where}: creative {path} not found (run `asokit assets render --variant {entry['creative']}`)")
                else:
                    problems += [f"{name}: {p}" for p in creative.check({locale: path})]
            seen = set()
            for keyword in (norm(k) for k in entry["keywords"]):
                if keyword in seen:
                    problems.append(f"{where}: keyword '{keyword}' listed twice")
                seen.add(keyword)
                if keyword in _protected(doc, locale) and keyword not in allow:
                    problems.append(f"{where}: '{keyword}' is protected (it carries the default page) — "
                                    f"pass --allow-protected {keyword} to assign it anyway")
                other = owner.get((locale, keyword))
                if other and other != name:
                    problems.append(f"{where}: keyword '{keyword}' already belongs to page '{other}' in {locale}")
                owner[(locale, keyword)] = name
                if online:
                    pool = online["pools"].get(locale)
                    if pool is not None and keyword not in pool:
                        problems.append(f"{where}: '{keyword}' is not in the {locale} keyword field of the live version "
                                        f"(available: {', '.join(sorted(pool))})")
                    editable = online.get("editable_pools")
                    if editable is not None and locale in editable and keyword not in editable[locale]:
                        warnings.append(f"{where}: '{keyword}' is missing from the next version's keyword field — "
                                        "routing stops when that version ships")
            if online and locale not in online["live_locales"]:
                problems.append(f"{where}: the live version has no {locale} localization")
        if online and page["template"] != "appStoreVersion":
            missing = sorted(online["families"] - declared_families)
            if missing:
                problems.append(f"{name}: no template, so every device family needs screenshots — missing {', '.join(missing)}")
        if online and not online["creative_supported"] and any(e.get("creative") for e in page["locales"].values()):
            warnings.append(f"{name}: Apple's catalog has no header/search placements for custom product pages — creatives skipped")
    total = len(set(names) | set(online["live_pages"])) if online else len(set(names))
    if total > MAX_PAGES:
        problems.append(f"{total} custom product pages (live + file) — App Store Connect allows {MAX_PAGES}")
    return problems, warnings
