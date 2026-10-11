# asokit/cpp_apply.py
"""Execute `cpp.json` plans against App Store Connect.

Reads live state into the snapshot shape `cpp.plan` consumes, runs the
online half of `cpp.check`, and applies plans: page/version/localization
writes, keyword links, and media via the Asset Library (`library.prepare` +
`library.place_prepared`).
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


CREATES = ("create_page", "create_version")


def _reread(name, page_id, bearer, version_id=None):
    """Snapshot a page we just created (or gave a new version) by id; never by name.

    Raises instead of returning something the planner would answer with a second create.
    """
    try:
        row = asc.call("GET", f"/appCustomProductPages/{page_id}", bearer)["data"]
    except asc.ASCError as error:
        raise asc.ASCError(f"{name}: created page {page_id} but could not read it back — re-run `cpp push` "
                           f"in a minute (it will find the page; nothing is created twice).\n{error}") from error
    snap = snapshot_page(row, bearer)
    version = snap.get("version")
    if version is None or (version_id and version["id"] != version_id):
        found = version and version["id"]
        raise asc.ASCError(f"{name}: the new version {version_id or ''} is not the page's latest (found {found}) — "
                           "re-run `cpp push` in a minute")
    if version["state"] not in cpp.EDITABLE:
        raise asc.ASCError(f"{name}: the new version {version['id']} is {version['state']}, not editable — nothing more written")
    return snap


def _keyword_body(ids):
    return {"data": [{"type": "appKeywords", "id": i} for i in ids]}


def _remove_keywords(name, action, snap, bearer, ledger):
    localizations = ((snap or {}).get("version") or {}).get("localizations") or {}
    ids = [localizations[action["locale"]]["keywords"][k] for k in action["keywords"]]
    asc.call("DELETE", f"/appCustomProductPageLocalizations/{action['localization']}/relationships/searchKeywords",
             bearer, _keyword_body(ids))
    ledger.record("cpp push", "remove_keywords", page_name=name, locale=action["locale"], live=action.get("live") or None,
                  keywords=action["keywords"])


def _media_requests(page, actions, doc, ctx, creative_root, locales):
    """{locale: [library request]} for every locale of this plan that will need media placed.

    A create (page or version) means every in-scope locale gets filled on the new surface.
    """
    if any(a["op"] in CREATES for a in actions):
        needed = [loc for loc in page["locales"] if not locales or loc in locales]
    else:
        needed = [a["locale"] for a in actions if a["op"] == "sync_media"]
    media = {}
    for locale in needed:
        entry = page["locales"][locale]
        requests = []
        for shot in entry["screenshots"]:
            files = cpp.select_screenshots(shot, doc["_root"])
            requests.append({"locale": locale, "parent_kind": "appCustomProductPageLocalization", "parent_id": None,
                             "placement_types": [library.SCREENSHOT], "category": library.MEDIA,
                             "display_class": shots.LEGACY_DISPLAY_CLASS.get(shot["display"]),
                             "files": [(p.name, p.read_bytes()) for p in files]})
        if entry.get("creative") and ctx["creative_supported"]:
            path = cpp.creative_path(doc, creative_root, entry["creative"], locale)
            requests.append({"locale": locale, "parent_kind": "appCustomProductPageLocalization", "parent_id": None,
                             "placement_types": [library.HEADER, library.SEARCH], "category": library.CREATIVE,
                             "files": [(path.name, path.read_bytes())]})
        if requests:
            media[locale] = requests
    return media


def _execute(app_id, page, snap, actions, media, ctx, catalog, bearer, ledger, out):
    """Apply one plan's actions in order (removals already ran in push's first write phase).

    Returns (executed actions, created) where created is None or ("page"|"version", id).
    Media is placed from assets `library.prepare` already uploaded and checked.
    """
    name = page["name"]
    localizations = ((snap or {}).get("version") or {}).get("localizations") or {}
    loc_ids = {locale: loc["id"] for locale, loc in localizations.items()}
    executed, placing = [], []
    for action in actions:
        op = action["op"]
        if op == "skip":
            executed.append(action)
            continue
        if op == "create_page":
            template = ctx["live_version_id"] if action["template"] else None
            created = asc.call("POST", "/appCustomProductPages", bearer,
                               create_page_body(app_id, name, action["deepLink"], action["locales"], template))["data"]
            if (created.get("attributes") or {}).get("visible") is not False:
                asc.call("PATCH", f"/appCustomProductPages/{created['id']}", bearer, _visible_body(created["id"], False))
            ledger.record("cpp push", "create_page", page_name=name, page_id=created["id"])
            return executed + [action], ("page", created["id"])
        if op == "create_version":
            attributes = {"deepLink": action["deepLink"]} if action["deepLink"] else {}
            created = asc.call("POST", "/appCustomProductPageVersions", bearer, {"data": {
                "type": "appCustomProductPageVersions", "attributes": attributes,
                "relationships": {"appCustomProductPage": {"data": {"type": "appCustomProductPages", "id": action["page_id"]}}},
            }})["data"]
            ledger.record("cpp push", "create_version", page_name=name, page_id=action["page_id"], version_id=created["id"])
            return executed + [action], ("version", created["id"])
        locale = action.get("locale")
        executed.append(action)
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
            _remove_keywords(name, action, snap, bearer, ledger)
            continue
        elif op == "sync_media":
            if locale not in media:
                raise asc.ASCError(f"{name} {locale}: media was not prepared before writing — nothing placed for it")
            for request in media[locale]:
                request["parent_id"] = action["localization"] or loc_ids[locale]
                placing.append(request)
            continue
        ledger.record("cpp push", op, page_name=name, locale=locale, live=action.get("live") or None,
                      keywords=action.get("keywords"))
    if placing:
        library.place_prepared(placing, catalog, FEATURE, bearer, True, ledger=ledger, command="cpp push",
                               progress=lambda a: out(f"    {a.get('locale', ''):<8} {a['type']:<32} {a['mode']}"))
    return executed, None


def push(app_id, doc, bearer, apply, creative_root="assets-out", pages=None, locales=None, prune=False,
         allow_protected=(), lint=True, ledger=NULL, out=print):
    """Validate, plan every in-scope page, then (with apply) write in three phases:

    1. prepare — upload/reuse, processing wait and spec/group/limit checks for ALL pages' media;
       no surface (metadata or placement) write happens before this succeeds;
    2. keyword removals on every page, so a keyword moving between pages is freed before it is linked;
    3. per page: metadata, keyword links, placements of the prepared assets. A created page or
       version is re-read by id and re-planned once; a re-plan never creates again.
    """
    catalog = library.Catalog.fetch(bearer)
    ctx = online_context(app_id, doc, bearer, catalog)
    problems, warnings = cpp.check(doc, creative_root, allow_protected, lint, online=ctx, scope=pages)
    result = {"problems": problems, "warnings": warnings, "actions": [], "context": ctx}
    selected = [p for p in cpp.expand(doc) if not pages or p["name"] in pages] if not problems else []
    unknown = sorted(set(pages or []) - {p["name"] for p in cpp.expand(doc)}) if not problems else []
    if unknown:
        result["problems"].append(f"not in the file: {', '.join(unknown)}")
    if result["problems"]:
        return result

    plans = []
    for page in selected:
        snap = ctx["snapshots"].get(page["name"])
        actions = cpp.plan(page, snap, doc, creative_root, locales, prune, ctx["creative_supported"])
        for action in actions:
            out(describe(action))
        plans.append((page, snap, actions, _media_requests(page, actions, doc, ctx, creative_root, locales)))
    if not apply:
        result["actions"] = [a for _, _, actions, _ in plans for a in actions]
        return result

    requests = [r for *_, media in plans for rs in media.values() for r in rs]
    if requests:
        library.prepare(requests, catalog, FEATURE, library.library_id(app_id, bearer), bearer, True)

    for page, snap, actions, _ in plans:
        for action in actions:
            if action["op"] == "remove_keywords":
                _remove_keywords(page["name"], action, snap, bearer, ledger)

    for page, snap, actions, media in plans:
        if not actions or all(a["op"] == "skip" for a in actions):
            result["actions"] += actions
            continue
        removed = [a for a in actions if a["op"] == "remove_keywords"]
        executed, created = _execute(app_id, page, snap, [a for a in actions if a["op"] != "remove_keywords"],
                                     media, ctx, catalog, bearer, ledger, out)
        result["actions"] += removed + executed
        if created is None:
            continue
        kind, created_id = created
        if kind == "page":
            snap = _reread(page["name"], created_id, bearer)
        else:
            snap = _reread(page["name"], snap["id"], bearer, version_id=created_id)
        actions = cpp.plan(page, snap, doc, creative_root, locales, prune, ctx["creative_supported"])
        for action in actions:
            out(describe(action))
        if any(a["op"] in CREATES for a in actions):
            raise asc.ASCError(f"{page['name']}: still needs a new page/version after creating one — stopping")
        executed, _ = _execute(app_id, page, snap, actions, media, ctx, catalog, bearer, ledger, out)
        result["actions"] += executed
    return result


class PublishError(asc.ASCError):
    pass


def _page_row(app_id, name, bearer, rows=None):
    for row in rows if rows is not None else list_pages(app_id, bearer):
        if (row.get("attributes") or {}).get("name") == name:
            return row
    raise PublishError(f"no custom product page named '{name}' in App Store Connect")


def publish(app_id, names, bearer, apply, hide=False, ledger=NULL, out=print):
    """Make pages visible (organic routing goes live) or hide them.

    Every named page is resolved and checked before the first write, so one
    unapproved page in the list leaves all of them untouched.
    """
    rows = list_pages(app_id, bearer)
    target = not hide
    planned = []
    for name in dict.fromkeys(names):
        row = _page_row(app_id, name, bearer, rows)
        snap = snapshot_page(row, bearer, with_media=False)
        state = (snap["version"] or {}).get("state")
        if not hide and state not in cpp.LIVE:
            raise PublishError(f"'{name}' latest version is {state} — publish only after Apple approves it (`asokit cpp submit` first)")
        keywords = {locale: sorted(loc["keywords"]) for locale, loc in ((snap["version"] or {}).get("localizations") or {}).items()}
        planned.append((row, {"page": name, "from": bool(snap["visible"]), "to": target, "keywords": keywords}))
    verb = "hide" if hide else "publish"
    for row, change in planned:
        name, keywords = change["page"], change["keywords"]
        if change["from"] == target:
            out(f"  {name}: already {'visible' if target else 'hidden'}")
            continue
        effect = "stops routing" if hide else "starts routing"
        for locale, kws in sorted(keywords.items()):
            out(f"  {name} {locale}: {effect} organic search for {', '.join(kws) or '(no keywords)'}")
        if apply:
            asc.call("PATCH", f"/appCustomProductPages/{row['id']}", bearer, _visible_body(row["id"], target))
            ledger.record("cpp publish", verb, page_name=name, page_id=row["id"], keywords=keywords)
    return [change for _, change in planned]


SUBMITTABLE = cpp.EDITABLE
BAD_PLACEMENT = frozenset({"ASSET_PROCESSING", "FAILED"})


def _check_declared(name, file_page, localizations, catalog, creative_supported):
    """Every locale the file declares for this page must exist on the version
    with the declared media placed: one screenshot placement per declared
    display family (matched by catalog display class) and both a header and a
    search placement when a creative is declared and the catalog supports
    them (the same condition push uses to place creatives)."""
    if not file_page:
        return
    for locale, declared in sorted(file_page.get("locales", {}).items()):
        loc = localizations.get(locale)
        if loc is None:
            raise review.SubmissionBlocked(f"'{name}' {locale}: declared in the file but missing from the version — run cpp push")
        shot_classes = {catalog.display_class(p["group"]) for p in loc["placements"] if p["type"] == library.SCREENSHOT}
        for entry in declared.get("screenshots") or []:
            wanted = shots.LEGACY_DISPLAY_CLASS.get(entry.get("display"))
            if wanted is None or wanted not in shot_classes:
                raise review.SubmissionBlocked(f"'{name}' {locale}: the file declares {entry.get('display')} screenshots but none are placed — run cpp push")
        if declared.get("creative") and creative_supported:
            placed = {p["type"] for p in loc["placements"]}
            for ptype, label in ((library.HEADER, "header"), (library.SEARCH, "search")):
                if ptype not in placed:
                    raise review.SubmissionBlocked(f"'{name}' {locale}: the file declares a creative but no {label} "
                                                   "placement is on the version — run cpp push")


def submit(app_id, doc, names, bearer, apply, ledger=NULL, out=print):
    """Send the named pages' latest versions to App Review via review.submit."""
    # Cheap read-only guard first: an in-flight submission or a foreign draft
    # item stops us before any snapshot work.
    review.preflight(app_id, bearer, {"appCustomProductPageVersion"})
    catalog = library.Catalog.fetch(bearer)
    supported = catalog.supports(FEATURE, library.HEADER) and catalog.supports(FEATURE, library.SEARCH)
    pages = {p["name"]: p for p in cpp.expand(doc)}
    rows = list_pages(app_id, bearer)
    items = []
    for name in dict.fromkeys(names):
        row = _page_row(app_id, name, bearer, rows)
        snap = snapshot_page(row, bearer)
        version = snap["version"]
        if version is None or version["state"] not in SUBMITTABLE:
            raise review.SubmissionBlocked(f"'{name}' has nothing to submit (latest version {version and version['state']})")
        for locale, loc in version["localizations"].items():
            states = {p["state"] for p in loc["placements"]}
            if states & BAD_PLACEMENT:
                raise review.SubmissionBlocked(f"'{name}' {locale}: placements still {sorted(states & BAD_PLACEMENT)} — wait or re-push")
        _check_declared(name, pages.get(name), version["localizations"], catalog, supported)
        items.append(("appCustomProductPageVersion", "appCustomProductPageVersions", version["id"]))
        out(f"  {name}: version {version['id']} ({version['state']})")
    return review.submit(app_id, items, bearer, apply, ledger=ledger, command="cpp submit")
