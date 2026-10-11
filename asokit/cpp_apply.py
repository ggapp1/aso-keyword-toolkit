# asokit/cpp_apply.py
"""Execute `cpp.json` plans against App Store Connect.

Reads live state into the snapshot shape `cpp.plan` consumes, runs the
online half of `cpp.check`, and applies plans: page/version/localization
writes, keyword links, and media via the Asset Library (`library.sync_groups`).
New pages are created hidden; only `publish` changes visibility; only
`submit` (through `review.submit`) sends anything to App Review.
"""
import re

from . import asc, cpp, library, review
from . import screenshots as shots
from .ledger import NULL

LIVE_APP_STATES = frozenset({"READY_FOR_SALE", "READY_FOR_DISTRIBUTION"})
FEATURE = "CUSTOM_PRODUCT_PAGES"


def _app_state(row):
    attrs = row.get("attributes") or {}
    return attrs.get("appStoreState") or attrs.get("appVersionState")


def live_app_version(app_id, bearer):
    for row in asc.call("GET", f"/apps/{app_id}/appStoreVersions?limit=10", bearer).get("data", []):
        if _app_state(row) in LIVE_APP_STATES:
            return row
    return None


def keyword_pool(version_localization_id, bearer):
    rows = asc.call_all("GET", f"/appStoreVersionLocalizations/{version_localization_id}/searchKeywords?limit=200", bearer)
    return {cpp.norm(row["id"]): row["id"] for row in rows}


def list_pages(app_id, bearer):
    return asc.call_all("GET", f"/apps/{app_id}/appCustomProductPages?limit=200", bearer)


def _version_key(row):
    text = (row.get("attributes") or {}).get("version") or ""
    return tuple(int(n) for n in re.findall(r"\d+", text)), text


def latest_version(page_id, bearer):
    rows = [row for row in asc.call_all("GET", f"/appCustomProductPages/{page_id}/appCustomProductPageVersions?limit=200", bearer)
            if (row.get("attributes") or {}).get("state") != "REPLACED_WITH_NEW_VERSION"]
    return max(rows, key=_version_key) if rows else None


def snapshot_page(row, bearer, with_media=True):
    attrs = row.get("attributes") or {}
    snap = {"id": row["id"], "name": attrs.get("name"), "url": attrs.get("url"), "visible": attrs.get("visible"), "version": None}
    version = latest_version(row["id"], bearer)
    if version is None:
        return snap
    localizations = {}
    for loc in asc.call_all("GET", f"/appCustomProductPageVersions/{version['id']}/appCustomProductPageLocalizations?limit=200", bearer):
        loc_attrs = loc.get("attributes") or {}
        keywords = asc.call_all("GET", f"/appCustomProductPageLocalizations/{loc['id']}/searchKeywords?limit=200", bearer)
        localizations[loc_attrs["locale"]] = {
            "id": loc["id"], "promotionalText": loc_attrs.get("promotionalText"),
            "keywords": {cpp.norm(k["id"]): k["id"] for k in keywords},
            "placements": library.surface_placements("appCustomProductPageLocalization", loc["id"], bearer) if with_media else [],
        }
    version_attrs = version.get("attributes") or {}
    snap["version"] = {"id": version["id"], "state": version_attrs.get("state"), "deepLink": version_attrs.get("deepLink"),
                       "localizations": localizations}
    return snap


def _families(live_locs, bearer, catalog):
    if not live_locs:
        return set()
    loc_id = live_locs.get("en-US") or next(iter(live_locs.values()))
    groups = {row["group"] for row in library.surface_placements("appStoreVersionLocalization", loc_id, bearer)
              if row["type"] == library.SCREENSHOT}
    families = {shots.LEGACY_BY_CLASS.get(catalog.display_class(g)) for g in groups} - {None}
    if families:
        return families
    # Screenshots uploaded through the deprecated set API may not appear as placements.
    return set(asc._screenshot_sets(loc_id, bearer))


def online_context(app_id, doc, bearer, catalog):
    live = live_app_version(app_id, bearer)
    if live is None:
        raise asc.ASCError("the app has no version on sale — custom product pages need one Ready for Distribution")
    live_locs = asc._localizations(live["id"], bearer)
    pool_ids = {locale: keyword_pool(loc_id, bearer) for locale, loc_id in live_locs.items()}
    editable = asc.editable_version(app_id, bearer)
    editable_pools = None
    if editable:
        editable_pools = {locale: set(keyword_pool(loc_id, bearer)) for locale, loc_id in asc._localizations(editable["id"], bearer).items()}
    # Raw names, not cpp.expand: a malformed file must still reach cpp.check, which reports it.
    in_file = {p.get("name") for p in doc.get("pages", [])}
    snapshots = {}
    for row in list_pages(app_id, bearer):
        name = (row.get("attributes") or {}).get("name")
        snapshots[name] = snapshot_page(row, bearer, with_media=name in in_file)
    live_keywords = {name: {locale: set(loc["keywords"]) for locale, loc in ((snap["version"] or {}).get("localizations") or {}).items()}
                     for name, snap in snapshots.items()}
    return {
        "pools": {locale: set(ids) for locale, ids in pool_ids.items()}, "pool_ids": pool_ids,
        "editable_pools": editable_pools, "live_locales": set(live_locs), "live_pages": set(snapshots),
        "live_keywords": live_keywords, "families": _families(live_locs, bearer, catalog),
        "creative_supported": catalog.supports(FEATURE, library.HEADER) and catalog.supports(FEATURE, library.SEARCH),
        "snapshots": snapshots, "live_version_id": live["id"],
    }


def create_page_body(app_id, name, deep_link, locales, template_version_id):
    version_ref = "${new-version}"
    loc_refs = [f"${{new-loc-{index}}}" for index in range(len(locales))]
    included = [{
        "type": "appCustomProductPageVersions", "id": version_ref,
        "attributes": {"deepLink": deep_link} if deep_link else {},
        "relationships": {"appCustomProductPageLocalizations": {"data": [
            {"type": "appCustomProductPageLocalizations", "id": ref} for ref in loc_refs]}},
    }]
    for ref, (locale, promo) in zip(loc_refs, sorted(locales.items())):
        attributes = {"locale": locale}
        if promo:
            attributes["promotionalText"] = promo
        included.append({"type": "appCustomProductPageLocalizations", "id": ref, "attributes": attributes})
    relationships = {
        "app": {"data": {"type": "apps", "id": str(app_id)}},
        "appCustomProductPageVersions": {"data": [{"type": "appCustomProductPageVersions", "id": version_ref}]},
    }
    if template_version_id:
        relationships["appStoreVersionTemplate"] = {"data": {"type": "appStoreVersions", "id": template_version_id}}
    return {"data": {"type": "appCustomProductPages", "attributes": {"name": name}, "relationships": relationships},
            "included": included}


def _visible_body(page_id, visible):
    return {"data": {"type": "appCustomProductPages", "id": page_id, "attributes": {"visible": visible}}}


def describe(action):
    op = action["op"]
    where = f"{action['page']}" + (f" {action['locale']}" if action.get("locale") else "")
    live = " (live, in place)" if action.get("live") else ""
    if op in ("add_keywords", "remove_keywords"):
        return f"  {op:<20} {where}: {', '.join(action['keywords'])}{live}"
    if op == "create_page":
        return f"  create_page          {action['page']} (hidden; locales {', '.join(action['locales'])}; template {action['template']})"
    if op == "skip":
        return f"  skip                 {action['page']}: {action['reason']}"
    return f"  {op:<20} {where}{live}"


def _refresh(app_id, name, bearer):
    for row in list_pages(app_id, bearer):
        if (row.get("attributes") or {}).get("name") == name:
            return snapshot_page(row, bearer)
    return None


def _keyword_body(ids):
    return {"data": [{"type": "appKeywords", "id": i} for i in ids]}


def _execute(app_id, page, snap, actions, doc, ctx, catalog, lib, bearer, creative_root, ledger, out):
    """Apply one plan. Returns True when a page/version was created and the caller must re-plan."""
    name = page["name"]
    localizations = ((snap or {}).get("version") or {}).get("localizations") or {}
    loc_ids = {locale: loc["id"] for locale, loc in localizations.items()}
    media = []
    for action in actions:
        op = action["op"]
        if op == "skip":
            continue
        if op == "create_page":
            template = ctx["live_version_id"] if action["template"] else None
            created = asc.call("POST", "/appCustomProductPages", bearer,
                               create_page_body(app_id, name, action["deepLink"], action["locales"], template))["data"]
            if (created.get("attributes") or {}).get("visible"):
                asc.call("PATCH", f"/appCustomProductPages/{created['id']}", bearer, _visible_body(created["id"], False))
            ledger.record("cpp push", "create_page", page_name=name, page_id=created["id"])
            return True
        if op == "create_version":
            attributes = {"deepLink": action["deepLink"]} if action["deepLink"] else {}
            created = asc.call("POST", "/appCustomProductPageVersions", bearer, {"data": {
                "type": "appCustomProductPageVersions", "attributes": attributes,
                "relationships": {"appCustomProductPage": {"data": {"type": "appCustomProductPages", "id": action["page_id"]}}},
            }})["data"]
            ledger.record("cpp push", "create_version", page_name=name, page_id=action["page_id"], version_id=created["id"])
            return True
        locale = action.get("locale")
        if op == "update_deep_link":
            asc.call("PATCH", f"/appCustomProductPageVersions/{action['version']}", bearer, {"data": {
                "type": "appCustomProductPageVersions", "id": action["version"], "attributes": {"deepLink": action["deepLink"]}}})
        elif op == "create_localization":
            created = asc.call("POST", "/appCustomProductPageLocalizations", bearer, {"data": {
                "type": "appCustomProductPageLocalizations",
                "attributes": {"locale": locale, "promotionalText": action["promotionalText"]},
                "relationships": {"appCustomProductPageVersion": {"data": {"type": "appCustomProductPageVersions", "id": action["version"]}}},
            }})["data"]
            loc_ids[locale] = created["id"]
        elif op == "update_promo":
            asc.call("PATCH", f"/appCustomProductPageLocalizations/{action['localization']}", bearer, {"data": {
                "type": "appCustomProductPageLocalizations", "id": action["localization"],
                "attributes": {"promotionalText": action["promotionalText"]}}})
        elif op == "delete_localization":
            asc.call("DELETE", f"/appCustomProductPageLocalizations/{action['localization']}", bearer)
        elif op == "add_keywords":
            ids = [ctx["pool_ids"][locale][k] for k in action["keywords"]]
            target = action["localization"] or loc_ids[locale]
            asc.call("POST", f"/appCustomProductPageLocalizations/{target}/relationships/searchKeywords", bearer, _keyword_body(ids))
        elif op == "remove_keywords":
            ids = [localizations[locale]["keywords"][k] for k in action["keywords"]]
            asc.call("DELETE", f"/appCustomProductPageLocalizations/{action['localization']}/relationships/searchKeywords",
                     bearer, _keyword_body(ids))
        elif op == "sync_media":
            media.append(action)
            continue
        ledger.record("cpp push", op, page_name=name, locale=locale, live=action.get("live") or None,
                      keywords=action.get("keywords"))

    requests = []
    for action in media:
        entry = page["locales"][action["locale"]]
        parent = action["localization"] or loc_ids[action["locale"]]
        for shot in entry["screenshots"]:
            files = cpp.select_screenshots(shot, doc["_root"])
            requests.append({"locale": action["locale"], "parent_kind": "appCustomProductPageLocalization", "parent_id": parent,
                             "placement_types": [library.SCREENSHOT], "category": library.MEDIA,
                             "display_class": shots.LEGACY_DISPLAY_CLASS.get(shot["display"]),
                             "files": [(p.name, p.read_bytes()) for p in files]})
        if entry.get("creative") and ctx["creative_supported"]:
            path = cpp.creative_path(doc, creative_root, entry["creative"], action["locale"])
            requests.append({"locale": action["locale"], "parent_kind": "appCustomProductPageLocalization", "parent_id": parent,
                             "placement_types": [library.HEADER, library.SEARCH], "category": library.CREATIVE,
                             "files": [(path.name, path.read_bytes())]})
    if requests:
        library.sync_groups(requests, catalog, FEATURE, lib, bearer, True, ledger=ledger, command="cpp push",
                            progress=lambda a: out(f"    {a.get('locale', ''):<8} {a['type']:<32} {a['mode']}"))
    return False


def push(app_id, doc, bearer, apply, creative_root="assets-out", pages=None, locales=None, prune=False,
         allow_protected=(), lint=True, ledger=NULL, out=print):
    catalog = library.Catalog.fetch(bearer)
    ctx = online_context(app_id, doc, bearer, catalog)
    problems, warnings = cpp.check(doc, creative_root, allow_protected, lint, online=ctx)
    result = {"problems": problems, "warnings": warnings, "actions": [], "context": ctx}
    selected = [p for p in cpp.expand(doc) if not pages or p["name"] in pages] if not problems else []
    unknown = sorted(set(pages or []) - {p["name"] for p in cpp.expand(doc)}) if not problems else []
    if unknown:
        result["problems"].append(f"not in the file: {', '.join(unknown)}")
    if result["problems"]:
        return result
    lib = library.library_id(app_id, bearer)
    for page in selected:
        snap = ctx["snapshots"].get(page["name"])
        for _ in range(3):
            actions = cpp.plan(page, snap, doc, creative_root, locales, prune, ctx["creative_supported"])
            for action in actions:
                out(describe(action))
            if not apply or not actions or all(a["op"] == "skip" for a in actions):
                result["actions"] += actions
                break
            replan = _execute(app_id, page, snap, actions, doc, ctx, catalog, lib, bearer, creative_root, ledger, out)
            if not replan:
                result["actions"] += actions
                break
            # Everything up to and including the create ran (live in-place edits precede create_version).
            cut = next(i for i, a in enumerate(actions) if a["op"] in ("create_page", "create_version"))
            result["actions"] += actions[:cut + 1]
            snap = _refresh(app_id, page["name"], bearer)
    return result
