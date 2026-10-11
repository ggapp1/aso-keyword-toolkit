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


def expand(doc, problems=None):
    """Resolve `same` and normalise entries. A `keywords` value that is not a
    list of strings raises CppError, or, when `problems` is a list (as `check`
    passes), is reported there and treated as empty."""
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
            raw_keywords = entry.get("keywords", [])
            if not isinstance(raw_keywords, list) or not all(isinstance(k, str) for k in raw_keywords):
                message = f"{raw_page.get('name')} {locale}: 'keywords' must be a list of strings"
                if problems is None:
                    raise CppError(message)
                problems.append(message)
                raw_keywords = []
            resolved["keywords"] = [k.strip() for k in raw_keywords if k.strip()]
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
        pages = expand(doc, problems)
    except CppError as error:
        return problems + [str(error)], []
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


def desired_media(doc, entry, locale, creative_root):
    screenshots = []
    for shot in entry["screenshots"]:
        screenshots.append([reference_name(p.name, p.read_bytes())[1] for p in select_screenshots(shot, doc["_root"])])
    creative_sha = None
    if entry.get("creative"):
        path = creative_path(doc, creative_root, entry["creative"], locale)
        creative_sha = reference_name(path.name, path.read_bytes())[1]
    return screenshots, creative_sha


def media_differs(media, placements, creative_supported):
    screenshots, creative_sha = media
    groups = {}
    for row in placements:
        if row.get("state") == "FAILED":
            continue  # a failed placement never counts as in sync (submit refuses it)
        groups.setdefault((row["type"], row["group"]), []).append(row.get("sha") or row.get("asset"))
    current_shots = [seq for (ptype, _), seq in groups.items() if ptype == SCREENSHOT]
    if any(seq not in current_shots for seq in screenshots):
        return True
    if creative_sha and creative_supported:
        creative_groups = [seq for (ptype, _), seq in groups.items() if ptype in (HEADER, SEARCH)]
        if not creative_groups or any(seq != [creative_sha] for seq in creative_groups):
            return True
    return False


def _keyword_actions(name, locale, localization, wanted, current, live):
    wanted_set = {norm(k) for k in wanted}
    current_set = set(current)
    actions = []
    add = sorted(wanted_set - current_set)
    remove = sorted(current_set - wanted_set)
    if add:
        actions.append({"op": "add_keywords", "page": name, "locale": locale, "localization": localization, "keywords": add, "live": live})
    if remove:
        actions.append({"op": "remove_keywords", "page": name, "locale": locale, "localization": localization, "keywords": remove, "live": live})
    return actions


def plan(page, snap, doc, creative_root="assets-out", locales=None, prune=False, creative_supported=True):
    name = page["name"]
    wanted = {loc: entry for loc, entry in page["locales"].items() if not locales or loc in locales}
    if snap is None or snap.get("version") is None:
        if snap is None:
            if not wanted:
                return [{"op": "skip", "page": name, "reason": "no locales in scope", "live": False}]
            actions = [{"op": "create_page", "page": name, "deepLink": page["deepLink"], "live": False,
                        "template": page["template"] == "appStoreVersion",
                        "locales": {loc: entry.get("promotionalText") for loc, entry in sorted(wanted.items())}}]
            synthetic = {"id": None, "name": name, "url": None, "visible": False, "version": {
                "id": None, "state": "PREPARE_FOR_SUBMISSION", "deepLink": page["deepLink"],
                "localizations": {loc: {"id": None, "promotionalText": entry.get("promotionalText"), "keywords": {}, "placements": []}
                                  for loc, entry in wanted.items()}}}
            return actions + plan(page, synthetic, doc, creative_root, locales, prune, creative_supported)
        return [{"op": "create_version", "page": name, "page_id": snap["id"], "deepLink": page["deepLink"], "live": False}]

    version = snap["version"]
    state = version["state"]
    if state in LOCKED:
        return [{"op": "skip", "page": name, "reason": f"version {state} — in review; re-run after review", "live": False}]
    if state not in EDITABLE and state not in LIVE:
        return [{"op": "skip", "page": name, "reason": f"version {state} — not editable", "live": False}]
    current = version["localizations"]
    media = {loc: desired_media(doc, entry, loc, creative_root) for loc, entry in wanted.items()}
    deep_link_changed = (page["deepLink"] or None) != (version.get("deepLink") or None)
    extras = [loc for loc in current if loc not in page["locales"]] if (prune and not locales) else []
    added = [loc for loc in wanted if loc not in current]
    if extras and len(current) - len(extras) + len(added) < 1:
        extras = []  # never delete the last localization, so never version for it either

    if state in LIVE:
        actions = []
        for loc, entry in sorted(wanted.items()):
            if loc not in current:
                continue
            here = current[loc]
            if (entry.get("promotionalText") or "") != (here.get("promotionalText") or ""):
                actions.append({"op": "update_promo", "page": name, "locale": loc, "localization": here["id"],
                                "promotionalText": entry.get("promotionalText") or "", "live": True})
            actions += _keyword_actions(name, loc, here["id"], entry["keywords"], here["keywords"], live=True)
        needs_version = (deep_link_changed or extras or added
                         or any(media_differs(media[loc], current[loc]["placements"], creative_supported) for loc in wanted if loc in current))
        if needs_version:
            actions.append({"op": "create_version", "page": name, "page_id": snap["id"], "deepLink": page["deepLink"], "live": False})
        return actions

    actions = []
    if deep_link_changed and version["id"]:
        actions.append({"op": "update_deep_link", "page": name, "version": version["id"], "deepLink": page["deepLink"], "live": False})
    for loc, entry in sorted(wanted.items()):
        here = current.get(loc)
        if here is None:
            actions.append({"op": "create_localization", "page": name, "version": version["id"], "locale": loc,
                            "promotionalText": entry.get("promotionalText") or "", "live": False})
            here = {"id": None, "keywords": {}, "placements": []}
        elif (entry.get("promotionalText") or "") != (here.get("promotionalText") or ""):
            actions.append({"op": "update_promo", "page": name, "locale": loc, "localization": here["id"],
                            "promotionalText": entry.get("promotionalText") or "", "live": False})
        actions += _keyword_actions(name, loc, here["id"], entry["keywords"], here["keywords"], live=False)
        if media_differs(media[loc], here["placements"], creative_supported):
            actions.append({"op": "sync_media", "page": name, "locale": loc, "localization": here["id"], "live": False})
    created = sum(1 for a in actions if a["op"] == "create_localization")
    if extras and len(current) - len(extras) + created >= 1:
        for loc in sorted(extras):
            actions.append({"op": "delete_localization", "page": name, "locale": loc, "localization": current[loc]["id"], "live": False})
    return actions


def ads_rows(pages, snapshots):
    rows = []
    names = [p["name"] for p in pages] + sorted(n for n in snapshots if n not in {p["name"] for p in pages})
    by_name = {p["name"]: p for p in pages}
    for name in names:
        snap = snapshots.get(name) or {}
        version = snap.get("version") or {}
        page = by_name.get(name)
        locales = sorted(set((page or {}).get("locales", {})) | set(version.get("localizations", {})))
        for loc in locales:
            if page and loc in page["locales"]:
                keywords = [norm(k) for k in page["locales"][loc]["keywords"]]
            else:
                keywords = sorted(version["localizations"][loc]["keywords"])
            rows.append({"page_name": name, "page_id": snap.get("id") or "", "page_url": snap.get("url") or "",
                         "visible": snap.get("visible", ""), "latest_state": version.get("state", ""), "locale": loc,
                         "keywords": ";".join(keywords), "deep_link": (page or {}).get("deepLink") or version.get("deepLink") or ""})
    return rows
