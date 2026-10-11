# tests/fakes.py
"""In-memory App Store Connect for library / CPP / review / nomination tests."""
import json
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

from asokit import asc


def _spec(spec_id, w, h, types, universal=False):
    return {"specId": spec_id, "shortName": spec_id, "aspectRatio": "",
            "dimensions": {"minWidth": w, "maxWidth": w, "minHeight": h, "maxHeight": h},
            "compatiblePlacementTypes": types, "alphaAllowed": False, "fileExtensions": [".png"],
            "mimeTypes": ["image/png"], "maxFileSize": 524288000, "universalAsset": universal}


def _policies():
    return [
        {"placementType": "APP_SCREENSHOT", "groupLimits": [{"groupIds": ["G_IPHONE_L", "G_IPAD_13", "G_WATCH_U", "G_WATCH_10"], "maxCount": 10}]},
        {"placementType": "PRODUCT_PAGE_HEADER_ASSET", "groupLimits": [{"groupIds": ["G_HEADER"], "maxCount": 1}]},
        {"placementType": "APP_STORE_SEARCH_RESULTS_ASSET", "groupLimits": [{"groupIds": ["G_SEARCH"], "maxCount": 1}]},
    ]


REFDATA = {"data": [{"type": "appAssetLibraryRefData", "id": "ref", "attributes": {
    "features": [
        {"featureId": "APP_STORE_VERSIONS", "placementPolicies": _policies()},
        {"featureId": "CUSTOM_PRODUCT_PAGES", "placementPolicies": _policies()},
    ],
    "placementProfileGroups": [
        {"placementProfileGroupId": "G_IPHONE_L", "displayClassId": "IPHONE_DYNAMIC_ISLAND_LARGE_DISPLAY", "platform": "IOS"},
        {"placementProfileGroupId": "G_IPAD_13", "displayClassId": "IPAD_13_DISPLAY", "platform": "IOS"},
        {"placementProfileGroupId": "G_WATCH_U", "displayClassId": "WATCH_ULTRA", "platform": "WATCH_OS"},
        {"placementProfileGroupId": "G_WATCH_10", "displayClassId": "WATCH_SERIES_10", "platform": "WATCH_OS"},
        {"placementProfileGroupId": "G_HEADER", "displayClassId": "DEFAULT", "platform": "IOS"},
        {"placementProfileGroupId": "G_SEARCH", "displayClassId": "DEFAULT", "platform": "IOS"},
    ],
    "placementTypes": [
        {"placementTypeId": "APP_SCREENSHOT", "acceptsAssetCategories": ["APP_SCREENSHOTS_AND_PREVIEWS"], "specMappings": [
            {"placementGroupId": "G_IPHONE_L", "specs": ["S_1290"]},
            {"placementGroupId": "G_IPAD_13", "specs": ["S_2064"]},
            {"placementGroupId": "G_WATCH_U", "specs": ["S_410"]},
            {"placementGroupId": "G_WATCH_10", "specs": ["S_410"]}]},
        {"placementTypeId": "PRODUCT_PAGE_HEADER_ASSET", "acceptsAssetCategories": ["CREATIVE_ASSETS"], "specMappings": [
            {"placementGroupId": "G_HEADER", "specs": ["S_UNIV", "S_HEADER"]}]},
        {"placementTypeId": "APP_STORE_SEARCH_RESULTS_ASSET", "acceptsAssetCategories": ["CREATIVE_ASSETS"], "specMappings": [
            {"placementGroupId": "G_SEARCH", "specs": ["S_UNIV"]}]},
    ],
    "imageSpecs": [
        _spec("S_1290", 1290, 2796, ["APP_SCREENSHOT", "IMESSAGE_APP_SCREENSHOT"]),
        _spec("S_2064", 2064, 2752, ["APP_SCREENSHOT"]),
        _spec("S_410", 410, 502, ["APP_SCREENSHOT"]),
        _spec("S_UNIV", 5244, 2950, ["PRODUCT_PAGE_HEADER_ASSET", "APP_STORE_SEARCH_RESULTS_ASSET"], universal=True),
        _spec("S_HEADER", 3840, 1646, ["PRODUCT_PAGE_HEADER_ASSET"]),
    ],
    "videoSpecs": [], "displayClasses": [],
}}]}

PARENT_COLLECTIONS = {
    "appStoreVersionLocalizations": "appStoreVersionLocalization",
    "appCustomProductPageLocalizations": "appCustomProductPageLocalization",
}


class FakeConnect:
    def __init__(self):
        self.log = []
        self.seq = 0
        self.images = {}          # id -> attrs
        self.placements = {}      # id -> {parent_kind, parent_id, type, group, image, pos}
        self.spec_by_file = {}    # fileName -> specId override; otherwise matched by dimensions
        self.default_spec = "S_UNIV"  # used when no bytes were uploaded
        self.after_commit = "PREPARE_FOR_SUBMISSION"
        self.versions = [{"id": "v1", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION", "versionString": "2.3.0"}}]
        self.version_locs = {"v1": {"en-US": "vl-en", "de-DE": "vl-de"}}
        self.experiments = []
        self.submissions = {}     # id -> {"state": str, "items": [(rel, type, id)]}
        self.fail_on = None       # (method, path prefix)
        self.uploaded = {}        # upload URL -> bytes received

    # ---- plumbing -------------------------------------------------------
    def next_id(self, prefix):
        self.seq += 1
        return f"{prefix}{self.seq}"

    def raw(self, method, url, headers, data):
        self.log.append((method, url))
        self.uploaded[url] = self.uploaded.get(url, b"") + (data or b"")
        return b""

    def call(self, method, path, bearer, body=None):
        self.log.append((method, path) if body is None else (method, path, json.dumps(body, sort_keys=True)))
        if self.fail_on and method == self.fail_on[0] and path.startswith(self.fail_on[1]):
            raise asc.ASCError(f"injected failure for {method} {path}")
        url = urlparse(path)
        parts = [p for p in url.path.split("/") if p]
        if parts and parts[0] == "v1":
            parts = parts[1:]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        result = self.route(method, parts, query, body)
        if result is None:
            raise AssertionError(f"unexpected {method} {path}")
        return result

    def writes(self):
        return [entry for entry in self.log if entry[0] in ("POST", "PATCH", "DELETE")]

    # ---- routes -----------------------------------------------------------
    def route(self, method, parts, query, body):
        if method == "GET" and parts == ["appAssetLibraryRefData"]:
            return json.loads(json.dumps(REFDATA))
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "assetLibrary":
            return {"data": {"type": "appAssetLibraries", "id": "lib1"}}
        if method == "GET" and parts[:1] == ["appAssetLibraries"] and parts[2:] == ["images"]:
            return {"data": self._list_images(query), "links": {}}
        if method == "POST" and parts == ["appAssetLibraryImages"]:
            return self._reserve(body)
        if method == "PATCH" and parts[:1] == ["appAssetLibraryImages"]:
            return self._commit(parts[1], body)
        if method == "GET" and parts[:1] == ["appAssetLibraryImages"] and len(parts) == 2:
            return {"data": self._image_row(parts[1])}
        if method == "POST" and parts == ["appAssetLibraryPlacements"]:
            return self._place(body)
        if method == "DELETE" and parts[:1] == ["appAssetLibraryPlacements"]:
            self.placements.pop(parts[1])
            return {}
        if method == "GET" and len(parts) == 3 and parts[0] in PARENT_COLLECTIONS and parts[2] == "placements":
            return self._surface(PARENT_COLLECTIONS[parts[0]], parts[1])
        if method == "POST" and parts == ["appAssetLibraryPlacementOrderingRequests"]:
            for position, item in enumerate(body["data"]["relationships"]["orderedPlacements"]["data"]):
                self.placements[item["id"]]["pos"] = position
            return {"data": {"type": "appAssetLibraryPlacementOrderingRequests", "id": self.next_id("ord")}}
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "appStoreVersions":
            return {"data": self.versions}
        if method == "GET" and len(parts) == 3 and parts[0] == "appStoreVersions" and parts[2] == "appStoreVersionLocalizations":
            return {"data": [{"id": lid, "attributes": {"locale": loc}} for loc, lid in self.version_locs.get(parts[1], {}).items()]}
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "appStoreVersionExperimentsV2":
            return {"data": self.experiments}
        return self.route_review(method, parts, query, body)

    def route_review(self, method, parts, query, body):
        if method == "GET" and parts == ["reviewSubmissions"]:
            wanted = set(query.get("filter[state]", "").split(","))
            return {"data": [{"id": sid, "type": "reviewSubmissions", "attributes": {"state": s["state"]}}
                             for sid, s in self.submissions.items() if s["state"] in wanted]}
        if method == "POST" and parts == ["reviewSubmissions"]:
            sid = self.next_id("sub")
            self.submissions[sid] = {"state": "READY_FOR_REVIEW", "items": []}
            return {"data": {"id": sid, "type": "reviewSubmissions"}}
        if method == "POST" and parts == ["reviewSubmissionItems"]:
            rels = body["data"]["relationships"]
            sid = rels.pop("reviewSubmission")["data"]["id"]
            (rel, value), = rels.items()
            self.submissions[sid]["items"].append((rel, value["data"]["type"], value["data"]["id"]))
            return {"data": {"id": self.next_id("item")}}
        if method == "GET" and len(parts) == 3 and parts[0] == "reviewSubmissions" and parts[2] == "items":
            return {"data": [{"id": f"i{n}", "type": "reviewSubmissionItems",
                              "relationships": {rel: {"data": {"type": rtype, "id": rid}}}}
                             for n, (rel, rtype, rid) in enumerate(self.submissions[parts[1]]["items"])]}
        if method == "PATCH" and parts[:1] == ["reviewSubmissions"]:
            if body["data"]["attributes"].get("submitted"):
                self.submissions[parts[1]]["state"] = "WAITING_FOR_REVIEW"
            return {"data": {"id": parts[1]}}
        return None

    # ---- library internals -----------------------------------------------
    def _image_row(self, image_id):
        return {"id": image_id, "type": "appAssetLibraryImages", "attributes": dict(self.images[image_id])}

    def _list_images(self, query):
        rows = []
        for image_id, attrs in self.images.items():
            if "filter[referenceName]" in query and attrs.get("referenceName") != unquote(query["filter[referenceName]"]):
                continue
            if "filter[category]" in query and attrs.get("category") != query["filter[category]"]:
                continue
            if "filter[id]" in query and image_id not in query["filter[id]"].split(","):
                continue
            rows.append(self._image_row(image_id))
        return rows

    def _reserve(self, body):
        attrs = body["data"]["attributes"]
        assert body["data"]["relationships"]["assetLibrary"]["data"] == {"type": "appAssetLibraries", "id": "lib1"}
        image_id = self.next_id("img")
        self.images[image_id] = {"fileName": attrs["fileName"], "fileSize": attrs["fileSize"], "category": attrs["category"],
                                 "referenceName": attrs.get("referenceName"), "state": "AWAITING_UPLOAD", "specId": None}
        return {"data": {"id": image_id, "type": "appAssetLibraryImages", "attributes": dict(self.images[image_id], uploadOperations=[
            {"method": "PUT", "url": f"https://upload.invalid/{image_id}", "offset": 0, "length": attrs["fileSize"], "requestHeaders": [
                {"name": "Content-Type", "value": "image/png"}]}])}}

    def _commit(self, image_id, body):
        assert body["data"]["attributes"] == {"uploaded": True}
        image = self.images[image_id]
        image["state"] = self.after_commit
        image["specId"] = self.spec_by_file.get(image["fileName"]) or self._spec_for(self.uploaded.get(f"https://upload.invalid/{image_id}"))
        return {"data": self._image_row(image_id)}

    def _spec_for(self, data):
        """Match uploaded bytes to a spec by exact dimensions, like Apple does."""
        if data:
            from asokit.creative import png_info
            info = png_info(data)
            for spec in REFDATA["data"][0]["attributes"]["imageSpecs"]:
                d = spec["dimensions"]
                if (d["minWidth"], d["minHeight"]) == (info["width"], info["height"]):
                    return spec["specId"]
        return self.default_spec

    def _place(self, body):
        data = body["data"]
        rels = dict(data["relationships"])
        image = rels.pop("image")["data"]["id"]
        (parent_kind, parent), = rels.items()
        assert image in self.images, f"placing unknown image {image}"
        pid = self.next_id("pl")
        siblings = [p for p in self.placements.values() if p["parent_id"] == parent["data"]["id"] and p["group"] == data["attributes"]["placementGroup"]]
        self.placements[pid] = {"parent_kind": parent_kind, "parent_id": parent["data"]["id"], "type": data["attributes"]["placementType"],
                                "group": data["attributes"]["placementGroup"], "image": image, "pos": len(siblings)}
        return {"data": {"id": pid, "type": "appAssetLibraryPlacements", "attributes": {"state": "PARENT_PREPARE_FOR_SUBMISSION"}}}

    def _surface(self, parent_kind, parent_id):
        rows = sorted((p for p in self.placements.values() if p["parent_id"] == parent_id), key=lambda p: (p["group"], p["pos"]))
        ids = {id(p): pid for pid, p in self.placements.items()}
        data = [{"id": ids[id(p)], "type": "appAssetLibraryPlacements",
                 "attributes": {"placementType": p["type"], "placementGroup": p["group"], "state": "PARENT_PREPARE_FOR_SUBMISSION"},
                 "relationships": {"image": {"data": {"type": "appAssetLibraryImages", "id": p["image"]}}}} for p in rows]
        included = [self._image_row(i) for i in {p["image"] for p in rows}]
        return {"data": data, "included": included, "links": {}}

    # ---- helpers for tests -------------------------------------------------
    def group(self, parent_id, group):
        rows = sorted((p for p in self.placements.values() if p["parent_id"] == parent_id and p["group"] == group), key=lambda p: p["pos"])
        return [self.images[p["image"]]["fileName"] for p in rows]


def install(testcase, fake):
    patches = [mock.patch.object(asc, "call", fake.call), mock.patch.object(asc, "_raw", fake.raw),
               mock.patch("time.sleep", lambda seconds: None)]
    for patch in patches:
        patch.start()
        testcase.addCleanup(patch.stop)
    return fake
