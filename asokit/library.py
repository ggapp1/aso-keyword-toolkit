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
    usable = [row for row in rows if row["attributes"].get("state") in REUSABLE]
    if usable:
        return usable[0]
    if any(row["attributes"].get("state") == "REJECTED" for row in rows):
        raise RejectedAsset(f"{reference}: this exact image was rejected by App Review — change it and re-render")
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
    """Batch-poll until every id is processed or terminally bad; backoff 5 → 30 s."""
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
            result = dict(base, asset=row["id"], status="reused", specId=row["attributes"].get("specId"))
        elif not self.apply:
            result = dict(base, asset=f"new:{sha}", status="would-upload", specId=None)
        else:
            asset = upload_image(self.library, file_name, data, category, reference, self.bearer)
            self.new_ids.append(asset)
            result = dict(base, asset=asset, status="uploaded", specId=None)
        self.cache[key] = result
        return result
