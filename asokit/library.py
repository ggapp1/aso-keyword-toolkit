# asokit/library.py
"""App Store Connect App Asset Library.

Upload an image once into the app's library, then *place* it on surfaces: an
App Store version localization or a custom product page localization. Apple
publishes which sizes go where as runtime reference data — read it, never
hard-code placement groups or spec ids (new devices appear there first).

The set-based screenshot API in `asc.py` is deprecated by Apple; this module
is its replacement.
"""
import hashlib
import time
from pathlib import Path
from urllib.parse import quote

from . import asc

SCREENSHOT = "APP_SCREENSHOT"
HEADER = "PRODUCT_PAGE_HEADER_ASSET"
SEARCH = "APP_STORE_SEARCH_RESULTS_ASSET"
CREATIVE = "CREATIVE_ASSETS"
MEDIA = "APP_SCREENSHOTS_AND_PREVIEWS"


class Catalog:
    """Parsed `appAssetLibraryRefData` (one resource, six parallel arrays)."""

    def __init__(self, attributes):
        self.raw = attributes
        self._features = {f["featureId"]: f for f in attributes.get("features", [])}
        self._groups = {g["placementProfileGroupId"]: g for g in attributes.get("placementProfileGroups", [])}
        self._types = {t["placementTypeId"]: t for t in attributes.get("placementTypes", [])}
        self._images = {s["specId"]: s for s in attributes.get("imageSpecs", [])}

    @classmethod
    def fetch(cls, bearer, features=None):
        path = "/appAssetLibraryRefData"
        if features:
            path += "?filter[features]=" + ",".join(features)
        data = asc.call("GET", path, bearer)["data"]
        item = data[0] if isinstance(data, list) else data
        return cls(item["attributes"])

    def features(self):
        return set(self._features)

    def _policy(self, feature, placement_type):
        for policy in self._features.get(feature, {}).get("placementPolicies", []):
            if policy.get("placementType") == placement_type:
                return policy
        return None

    def supports(self, feature, placement_type):
        return self._policy(feature, placement_type) is not None

    def _allowed_groups(self, policy):
        return {g for limit in policy.get("groupLimits", []) for g in limit.get("groupIds", [])}

    def groups_for_spec(self, feature, placement_type, spec_id):
        policy = self._policy(feature, placement_type)
        if policy is None:
            return []
        allowed = self._allowed_groups(policy)
        groups = []
        for mapping in self._types.get(placement_type, {}).get("specMappings", []):
            group = mapping.get("placementGroupId")
            if spec_id in mapping.get("specs", []) and (not allowed or group in allowed) and group not in groups:
                groups.append(group)
        return groups

    def groups_for_display_class(self, feature, placement_type, display_class):
        policy = self._policy(feature, placement_type)
        if policy is None:
            return []
        allowed = self._allowed_groups(policy)
        groups = []
        for mapping in self._types.get(placement_type, {}).get("specMappings", []):
            group = mapping.get("placementGroupId")
            if self.display_class(group) == display_class and (not allowed or group in allowed) and group not in groups:
                groups.append(group)
        return groups

    def specs_matching(self, placement_type, width, height):
        matches = []
        for spec in self._images.values():
            d = spec.get("dimensions", {})
            if (placement_type in spec.get("compatiblePlacementTypes", [])
                    and d.get("minWidth", 0) <= width <= d.get("maxWidth", 0)
                    and d.get("minHeight", 0) <= height <= d.get("maxHeight", 0)):
                matches.append(spec)
        return matches

    def spec(self, spec_id):
        return self._images.get(spec_id)

    def max_count(self, feature, placement_type, group):
        policy = self._policy(feature, placement_type)
        for limit in (policy or {}).get("groupLimits", []):
            if group in limit.get("groupIds", []):
                return limit.get("maxCount")
        return None

    def accepts(self, placement_type):
        return set(self._types.get(placement_type, {}).get("acceptsAssetCategories", []))

    def display_class(self, group):
        return self._groups.get(group, {}).get("displayClassId")

    def summary(self):
        """Human-readable dump for the live read-only check (Phase A step 1)."""
        lines = []
        for feature, body in sorted(self._features.items()):
            lines.append(feature)
            for policy in body.get("placementPolicies", []):
                ptype = policy.get("placementType")
                for limit in policy.get("groupLimits", []):
                    for group in limit.get("groupIds", []):
                        specs = []
                        for mapping in self._types.get(ptype, {}).get("specMappings", []):
                            if mapping.get("placementGroupId") == group:
                                for spec_id in mapping.get("specs", []):
                                    d = (self._images.get(spec_id) or {}).get("dimensions", {})
                                    specs.append(f"{spec_id} {d.get('minWidth')}×{d.get('minHeight')}")
                        lines.append(f"  {ptype:<32} {group:<40} max {limit.get('maxCount')}  "
                                     f"[{self.display_class(group)}]  {', '.join(specs) or '-'}")
        return lines


REUSABLE = frozenset({"UPLOAD_COMPLETE", "COMPLETE", "PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW",
                      "WAITING_FOR_REVIEW", "IN_REVIEW", "ACCEPTED", "APPROVED"})
PROCESSED = REUSABLE - {"UPLOAD_COMPLETE"}
TERMINAL_BAD = frozenset({"FAILED", "REJECTED", "ARCHIVED"})
REVIEW_PASSED = frozenset({"ACCEPTED", "APPROVED"})
IN_OR_PAST_REVIEW = frozenset({"WAITING_FOR_REVIEW", "IN_REVIEW"}) | REVIEW_PASSED
TIMEOUT = "TIMEOUT"


class RejectedAsset(asc.ASCError):
    pass


def reference_name(file_name, data):
    sha = hashlib.sha256(data).hexdigest()[:16]
    return f"asokit:{sha}:{Path(file_name).name[:40]}", sha


def sha_of(reference):
    """The content hash inside an asokit referenceName, else None."""
    if reference and reference.startswith("asokit:"):
        return reference.split(":")[1]
    return None


def library_id(app_id, bearer):
    return asc.call("GET", f"/apps/{app_id}/assetLibrary", bearer)["data"]["id"]


def find_reusable(library, reference, category, bearer):
    rows = asc.call_all(
        "GET",
        f"/appAssetLibraries/{library}/images?filter[referenceName]={quote(reference, safe='')}"
        f"&filter[category]={category}&limit=200",
        bearer,
    )

    def state(row):
        return row["attributes"].get("state")

    usable = [row for row in rows if state(row) in REUSABLE]
    if any(state(row) == "REJECTED" for row in rows):
        # A rejected twin means App Review has seen these bytes: only a twin
        # that review has since accepted is safe; anything still unreviewed
        # would most likely be rejected again.
        reviewed = [row for row in usable if state(row) in REVIEW_PASSED]
        if reviewed:
            return reviewed[0]
        raise RejectedAsset(f"{reference}: this exact image was rejected by App Review — change it and re-render")
    if usable:
        # Prefer a processed row (it carries a specId) over UPLOAD_COMPLETE.
        return next((row for row in usable if state(row) in PROCESSED), usable[0])
    return None


def upload_image(library, file_name, data, category, reference, bearer):
    reserved = asc.call("POST", "/appAssetLibraryImages", bearer, {"data": {
        "type": "appAssetLibraryImages",
        "attributes": {"fileName": Path(file_name).name, "fileSize": len(data), "category": category, "referenceName": reference},
        "relationships": {"assetLibrary": {"data": {"type": "appAssetLibraries", "id": library}}},
    }})["data"]
    for op in reserved["attributes"]["uploadOperations"]:
        chunk = data[op["offset"]: op["offset"] + op["length"]]
        asc._raw(op["method"], op["url"], {h["name"]: h["value"] for h in op.get("requestHeaders", [])}, chunk)
    asc.call("PATCH", f"/appAssetLibraryImages/{reserved['id']}", bearer, {"data": {
        "type": "appAssetLibraryImages", "id": reserved["id"], "attributes": {"uploaded": True},
    }})
    return reserved["id"]


def wait_processed(library, ids, bearer, timeout_s=900):
    """Batch-poll until every id is processed or terminally bad; backoff 5 → 30 s.

    Ids still unfinished at the deadline (or never returned by the API) come
    back with state TIMEOUT, so callers checking against PROCESSED treat them
    as failures rather than silently missing them.
    """
    states, pending = {}, set(ids)
    delay, deadline = 5, time.time() + timeout_s
    while pending:
        ordered = sorted(pending)
        for start in range(0, len(ordered), 50):
            chunk = ",".join(ordered[start:start + 50])
            for row in asc.call_all("GET", f"/appAssetLibraries/{library}/images?filter[id]={chunk}&limit=200", bearer):
                attrs = row["attributes"]
                states[row["id"]] = {"state": attrs.get("state"), "specId": attrs.get("specId"), "stateDetails": attrs.get("stateDetails")}
        pending = {i for i in pending if states.get(i, {}).get("state") not in PROCESSED | TERMINAL_BAD}
        if not pending or time.time() >= deadline:
            break
        time.sleep(delay)
        delay = min(delay * 2, 30)
    for image_id in pending:
        last = states.get(image_id, {})
        states[image_id] = {"state": TIMEOUT, "specId": last.get("specId"), "stateDetails": last.get("stateDetails")}
    return states


class Uploader:
    """Upload-or-reuse, with an in-run cache keyed by (sha, category)."""

    def __init__(self, library, bearer, apply):
        self.library, self.bearer, self.apply = library, bearer, apply
        self.cache = {}
        self.new_ids = []

    def ensure(self, file_name, data, category):
        from .creative import png_info
        reference, sha = reference_name(file_name, data)
        info = png_info(data)
        base = {"sha": sha, "name": Path(file_name).name, "width": info["width"], "height": info["height"]}
        key = (sha, category)
        if key in self.cache:
            return dict(self.cache[key], **{k: base[k] for k in ("name",)})
        row = find_reusable(self.library, reference, category, self.bearer)
        if row:
            result = dict(base, asset=row["id"], status="reused", specId=row["attributes"].get("specId"),
                          state=row["attributes"].get("state"))
        elif not self.apply:
            result = dict(base, asset=f"new:{sha}", status="would-upload", specId=None, state=None)
        else:
            asset = upload_image(self.library, file_name, data, category, reference, self.bearer)
            self.new_ids.append(asset)
            result = dict(base, asset=asset, status="uploaded", specId=None, state=None)
        self.cache[key] = result
        return result


PARENTS = {
    "appStoreVersionLocalization": "appStoreVersionLocalizations",
    "appCustomProductPageLocalization": "appCustomProductPageLocalizations",
}
VERSION_PLACEABLE = frozenset({"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY"})


FAILED_PLACEMENT = "FAILED"


class PartialPlacement(asc.ASCError):
    pass


def surface_placements(parent_kind, parent_id, bearer):
    """Every placement on one localization, with each placement's asset hash."""
    url = f"/{PARENTS[parent_kind]}/{parent_id}/placements?include=image&sort=placementGroupPosition&limit=200"
    rows, images = [], {}
    while url:
        page = asc.call("GET", url, bearer)
        rows.extend(page.get("data", []))
        for item in page.get("included", []) or []:
            if item.get("type") == "appAssetLibraryImages":
                images[item["id"]] = item.get("attributes") or {}
        url = (page.get("links") or {}).get("next")
    placements = []
    for row in rows:
        attrs = row.get("attributes") or {}
        image = (((row.get("relationships") or {}).get("image") or {}).get("data") or {}).get("id")
        placements.append({"id": row["id"], "type": attrs.get("placementType"), "group": attrs.get("placementGroup"),
                           "state": attrs.get("state"), "asset": image,
                           "sha": sha_of((images.get(image) or {}).get("referenceName"))})
    return placements


def place(asset_id, placement_type, group, parent_kind, parent_id, bearer):
    return asc.call("POST", "/appAssetLibraryPlacements", bearer, {"data": {
        "type": "appAssetLibraryPlacements",
        "attributes": {"placementType": placement_type, "placementGroup": group},
        "relationships": {
            "image": {"data": {"type": "appAssetLibraryImages", "id": asset_id}},
            parent_kind: {"data": {"type": PARENTS[parent_kind], "id": parent_id}},
        },
    }})["data"]["id"]


def unplace(placement_id, bearer):
    asc.call("DELETE", f"/appAssetLibraryPlacements/{placement_id}", bearer)


def order(group, placement_ids, parent_kind, parent_id, bearer):
    asc.call("POST", "/appAssetLibraryPlacementOrderingRequests", bearer, {"data": {
        "type": "appAssetLibraryPlacementOrderingRequests",
        "attributes": {"placementGroup": group},
        "relationships": {
            "orderedPlacements": {"data": [{"type": "appAssetLibraryPlacements", "id": pid} for pid in placement_ids]},
            parent_kind: {"data": {"type": PARENTS[parent_kind], "id": parent_id}},
        },
    }})


def replace_group(desired, placement_type, group, parent_kind, parent_id, max_count, bearer, apply, current):
    """Make one placement group hold exactly `desired`, in order, with minimal writes.

    Placements that already show a desired asset are kept. Missing ones are
    placed BEFORE extras are removed whenever the group's limit allows, so an
    abort never leaves the surface emptier than it started; at the limit the
    extras go first and an abort reports the gap.
    """
    if max_count is not None and len(desired) > max_count:
        raise asc.ASCError(f"{parent_id} {group}: {len(desired)} assets exceed the group limit of {max_count}")
    # A FAILED placement never counts as showing its asset (submit refuses it):
    # it is an extra to unplace, and the asset gets a fresh placement.
    pool = [row for row in current if row.get("state") != FAILED_PLACEMENT]
    failed = [row for row in current if row.get("state") == FAILED_PLACEMENT]
    final = []
    for want in desired:
        # Exact placement of this asset first; only then any placement of the same bytes.
        match = next((row for row in pool if row.get("asset") == want.get("asset")), None)
        if match is None and want.get("sha"):
            match = next((row for row in pool if row.get("sha") == want["sha"]), None)
        if match:
            pool.remove(match)
        final.append([match["id"] if match else None, want])
    extras = failed + pool
    missing = [slot for slot in final if slot[0] is None]
    action = {"type": placement_type, "group": group, "parent_id": parent_id, "place": len(missing), "unplace": len(extras)}
    if not missing and not extras:
        action["mode"] = "unchanged" if [s[0] for s in final] == [row["id"] for row in current] else "reorder"
    else:
        place_first = max_count is None or len(current) + len(missing) <= max_count
        action["mode"] = "place-first" if place_first else "unplace-first"
    if not apply or action["mode"] == "unchanged":
        return action

    placed = 0
    try:
        if action["mode"] == "unplace-first":
            for row in extras:
                unplace(row["id"], bearer)
        for slot in missing:
            slot[0] = place(slot[1]["asset"], placement_type, group, parent_kind, parent_id, bearer)
            placed += 1
        if action["mode"] == "place-first":
            for row in extras:
                unplace(row["id"], bearer)
    except asc.ASCError as error:
        raise PartialPlacement(
            f"{parent_id} {group}: {placed} of {len(missing)} new placements made before the failure — "
            f"the group may be incomplete; re-run to converge.\n{error}"
        ) from error
    ids = [slot[0] for slot in final]
    if len(ids) > 1:
        order(group, ids, parent_kind, parent_id, bearer)
        actual = [row["id"] for row in surface_placements(parent_kind, parent_id, bearer)
                  if row["type"] == placement_type and row["group"] == group]
        if actual != ids:
            raise asc.ASCError(f"{parent_id} {group}: order did not stick (got {actual}, wanted {ids})")
    return action


def sync_groups(requests, catalog, feature, library, bearer, apply, ledger=None, command="", progress=None):
    """Upload/reuse every file, wait once, then replace each request's groups.

    A request is a dict:
      locale, parent_kind, parent_id (None for a surface that doesn't exist yet — dry run only),
      placement_types: [type, ...]  (one asset sequence is placed under each type),
      category: CREATIVE or MEDIA,
      files: [(file_name, bytes), ...]  OR  assets: [{"asset", "sha", "specId"}] (re-place existing assets),
      display_class: optional tie-breaker when a spec maps to several groups (e.g. Watch 410×502),
      groups: optional explicit group list (mirroring copies the source group).
    Phase 1 (no surface writes): uploads + one processing wait + spec checks.
    Phase 2: replace_group per (request, type, group).
    """
    uploader = Uploader(library, bearer, apply)
    for request in requests:
        if "assets" not in request:
            request["assets"] = [uploader.ensure(name, data, request["category"]) for name, data in request["files"]]
    # Every asset without a specId — fresh uploads and reused UPLOAD_COMPLETE
    # rows alike — must finish processing and pass the spec check.
    unprocessed = sorted({a["asset"] for r in requests for a in r["assets"] if not a.get("specId")})
    if apply and unprocessed:
        states = wait_processed(library, unprocessed, bearer)
        bad = {i: s for i, s in states.items() if s.get("state") not in PROCESSED}
        if bad:
            details = ", ".join(f"{i}: {s.get('state')} {s.get('stateDetails') or ''}".strip() for i, s in bad.items())
            raise asc.ASCError(f"Apple did not accept {len(bad)} upload(s) — nothing placed. {details}")
        for request in requests:
            for asset in request["assets"]:
                if asset["asset"] in states:
                    asset["specId"] = states[asset["asset"]]["specId"]

    plans = []
    for request in requests:
        for ptype in request["placement_types"]:
            if not catalog.supports(feature, ptype):
                plans.append((request, ptype, None))
                continue
            groups = request.get("groups") or _resolve_groups(catalog, feature, ptype, request)
            for group in groups:
                plans.append((request, ptype, group))

    for request, ptype, group in plans:
        limit = catalog.max_count(feature, ptype, group) if group else None
        if limit is not None and len(request["assets"]) > limit:
            raise asc.ASCError(f"{request['locale']} {group}: {len(request['assets'])} assets exceed the group limit "
                               f"of {limit} — nothing placed")

    actions, surfaces = [], {}
    for request, ptype, group in plans:
        if group is None:
            actions.append({"locale": request["locale"], "type": ptype, "group": None, "mode": "unsupported",
                            "parent_id": request["parent_id"], "place": 0, "unplace": 0})
            continue
        parent = request["parent_id"]
        if parent not in surfaces:
            surfaces[parent] = surface_placements(request["parent_kind"], parent, bearer) if parent else []
        current = [row for row in surfaces[parent] if row["type"] == ptype and row["group"] == group]
        desired = [{"asset": a["asset"], "sha": a["sha"]} for a in request["assets"]]
        action = replace_group(desired, ptype, group, request["parent_kind"], parent,
                               catalog.max_count(feature, ptype, group), bearer, apply and parent is not None, current)
        action["locale"] = request["locale"]
        actions.append(action)
        if apply and parent and action["mode"] != "unchanged":
            surfaces[parent] = surface_placements(request["parent_kind"], parent, bearer)
        if apply and ledger and action["mode"] != "unchanged":
            ledger.record(command, "place", locale=request["locale"], surface=request["parent_kind"], parent_id=parent,
                          placement_type=ptype, group=group, asset_sha=[a["sha"] for a in request["assets"]], mode=action["mode"])
        if progress:
            progress(action)
    return actions


def _resolve_groups(catalog, feature, ptype, request):
    """Groups every asset of the request can go to; screenshots need exactly one."""
    per_asset = []
    for asset in request["assets"]:
        if asset.get("specId"):
            groups = catalog.groups_for_spec(feature, ptype, asset["specId"])
            if not groups:
                raise asc.ASCError(f"{request['locale']}: {asset['name']} matched spec {asset['specId']}, "
                                   f"which has no {ptype} group under {feature}")
        else:   # dry run, or reused row without a spec: infer from dimensions
            groups = []
            for spec in catalog.specs_matching(ptype, asset["width"], asset["height"]):
                groups += [g for g in catalog.groups_for_spec(feature, ptype, spec["specId"]) if g not in groups]
            if not groups:
                raise asc.ASCError(f"{request['locale']}: {asset['name']} is {asset['width']}×{asset['height']}; "
                                   f"no {ptype} spec under {feature} accepts that size")
        per_asset.append(groups)
    common = [g for g in per_asset[0] if all(g in groups for groups in per_asset[1:])] if per_asset else []
    if request.get("display_class"):
        common = [g for g in common if catalog.display_class(g) == request["display_class"]] or common
    if ptype == SCREENSHOT and len(common) != 1:
        raise asc.ASCError(f"{request['locale']}: screenshots map to {len(common)} groups {common}; pass a display class")
    return common


EXPERIMENT_REVIEW = frozenset({"READY_FOR_REVIEW", "WAITING_FOR_REVIEW", "IN_REVIEW"})
EXPERIMENT_LIVE = frozenset({"ACCEPTED", "APPROVED"})


def active_experiment(app_id, bearer):
    """Name of a product page optimization test that is in review or running, else None.

    Field reports say a running test blocks placements on the default page.
    Apple has no RUNNING state: running = approved/accepted, started, not ended.
    """
    states = ",".join(sorted(EXPERIMENT_REVIEW | EXPERIMENT_LIVE))
    rows = asc.call_all("GET", f"/apps/{app_id}/appStoreVersionExperimentsV2?filter[state]={states}&limit=200", bearer)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for row in rows:
        attrs = row.get("attributes") or {}
        state = attrs.get("state")
        if state in EXPERIMENT_REVIEW:
            return attrs.get("name") or row["id"]
        end = attrs.get("endDate")
        if state in EXPERIMENT_LIVE and (attrs.get("startDate") or "") <= now and not (end and end <= now):
            return attrs.get("name") or row["id"]
    return None
