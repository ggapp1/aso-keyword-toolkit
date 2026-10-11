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
