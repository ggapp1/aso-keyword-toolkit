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
            included = set(query.get("include", "").split(","))
            if {"appStoreVersionExperiment", "appStoreVersionExperimentV2"} <= included:
                # Apple: "cannot include appStoreVersionExperiment and appStoreVersionExperimentV2 at the same time"
                raise asc.ASCError("App Store Connect returned 400: include has both experiment versions")
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
                 "attributes": {"placementType": p["type"], "placementGroup": p["group"],
                                "state": p.get("state", "PARENT_PREPARE_FOR_SUBMISSION")},
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


class FakeCppConnect(FakeConnect):
    """FakeConnect plus custom product pages, keyword pools and legacy screenshot sets."""

    POOL_US = ["mania", "depression", "hypomania", "episode", "medication", "mental", "health",
               "borderline", "cyclothymia", "bpd", "triggers", "adhd"]
    POOL_GB = ["symptom", "depression", "hypomania", "diary", "medication", "mental", "health",
               "borderline", "cyclothymia", "bpd", "triggers", "adhd"]

    def __init__(self):
        super().__init__()
        self.versions.append({"id": "v0", "attributes": {"appStoreState": "READY_FOR_SALE", "versionString": "2.2.0"}})
        self.version_locs["v0"] = {"en-US": "vl0-en", "en-GB": "vl0-gb"}
        self.version_locs["v1"] = {"en-US": "vl-en", "en-GB": "vl-gb"}
        self.pool = {"vl0-en": list(self.POOL_US), "vl0-gb": list(self.POOL_GB),
                     "vl-en": list(self.POOL_US), "vl-gb": list(self.POOL_GB)}
        self.legacy_sets = {"vl0-en": ["APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"]}
        self.pages = {}       # id -> {"name", "visible", "template"}
        self.cpp_versions = {}  # id -> {"page", "state", "deepLink", "version"}
        self.cpp_locs = {}      # id -> {"version", "locale", "promotionalText", "keywords": [ids]}
        self.create_visible = True
        self.prepopulate = False
        self.hide_created = False     # pages made by POST stay invisible to reads (eventual consistency)
        self.created_pages = set()
        self.new_version_state = "PREPARE_FOR_SUBMISSION"

    LIVE_STATES = frozenset({"ACCEPTED", "APPROVED"})
    EDITABLE_STATES = frozenset({"PREPARE_FOR_SUBMISSION", "REJECTED", "READY_FOR_REVIEW"})

    def _live_loc(self, loc_id):
        loc = self.cpp_locs.get(loc_id)
        return loc is not None and self.cpp_versions[loc["version"]]["state"] in self.LIVE_STATES

    def _refuse(self, message):
        raise asc.ASCError(f"App Store Connect returned 409: {message}")

    def _place(self, body):
        parent = body["data"]["relationships"].get("appCustomProductPageLocalization")
        if parent and self._live_loc(parent["data"]["id"]):
            self._refuse("cannot place media on a live custom product page version")
        return super()._place(body)

    def add_page(self, name, state="APPROVED", locales=None, visible=True):
        page_id = self.next_id("page")
        self.pages[page_id] = {"name": name, "visible": visible, "template": None}
        version_id = self._new_version(page_id, state)
        loc_ids = {}
        for locale, spec in (locales or {}).items():
            loc_ids[locale] = self._new_loc(version_id, locale, spec.get("promo", ""), spec.get("keywords", []))
        return page_id, version_id, loc_ids

    def _new_version(self, page_id, state, deep_link=None):
        version_id = self.next_id("cv")
        number = 1 + sum(1 for v in self.cpp_versions.values() if v["page"] == page_id)
        self.cpp_versions[version_id] = {"page": page_id, "state": state, "deepLink": deep_link, "version": str(number)}
        return version_id

    def _new_loc(self, version_id, locale, promo, keywords):
        loc_id = self.next_id("cl")
        self.cpp_locs[loc_id] = {"version": version_id, "locale": locale, "promotionalText": promo, "keywords": list(keywords)}
        return loc_id

    def page_named(self, name):
        return next(pid for pid, p in self.pages.items() if p["name"] == name)

    def route(self, method, parts, query, body):
        self._guard(method, parts, body)
        result = super().route(method, parts, query, body)
        return result if result is not None else self.route_cpp(method, parts, query, body)

    def _guard(self, method, parts, body):
        """Media on a live CPP version cannot change (only promo/keywords are editable in place)."""
        if method == "DELETE" and parts[:1] == ["appAssetLibraryPlacements"] and len(parts) == 2:
            placement = self.placements.get(parts[1])
            if placement and self._live_loc(placement["parent_id"]):
                self._refuse("cannot remove media from a live custom product page version")
        if method == "POST" and parts == ["appAssetLibraryPlacementOrderingRequests"]:
            parent = body["data"]["relationships"].get("appCustomProductPageLocalization")
            if parent and self._live_loc(parent["data"]["id"]):
                self._refuse("cannot reorder media on a live custom product page version")

    def route_cpp(self, method, parts, query, body):
        if method == "GET" and len(parts) == 3 and parts[0] == "appStoreVersionLocalizations" and parts[2] == "searchKeywords":
            return {"data": [{"type": "appKeywords", "id": k} for k in self.pool.get(parts[1], [])]}
        if method == "GET" and len(parts) == 3 and parts[0] == "appStoreVersionLocalizations" and parts[2] == "appScreenshotSets":
            return {"data": [{"id": f"set-{t}", "attributes": {"screenshotDisplayType": t}} for t in self.legacy_sets.get(parts[1], [])]}
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "appCustomProductPages":
            return {"data": [self._page_row(pid) for pid in self.pages if not self._hidden(pid)]}
        if method == "GET" and len(parts) == 2 and parts[0] == "appCustomProductPages":
            if parts[1] not in self.pages or self._hidden(parts[1]):
                raise asc.ASCError(f"App Store Connect returned 404 for GET /appCustomProductPages/{parts[1]}")
            return {"data": self._page_row(parts[1])}

        if method == "POST" and parts == ["appCustomProductPages"]:
            return self._create_page(body)
        if method == "PATCH" and parts[:1] == ["appCustomProductPages"]:
            self.pages[parts[1]]["visible"] = body["data"]["attributes"]["visible"]
            return {"data": {"id": parts[1]}}
        if method == "GET" and len(parts) == 3 and parts[0] == "appCustomProductPages" and parts[2] == "appCustomProductPageVersions":
            return {"data": [{"id": vid, "type": "appCustomProductPageVersions",
                              "attributes": {"state": v["state"], "deepLink": v["deepLink"], "version": v["version"]}}
                             for vid, v in self.cpp_versions.items() if v["page"] == parts[1]]}
        if method == "POST" and parts == ["appCustomProductPageVersions"]:
            page_id = body["data"]["relationships"]["appCustomProductPage"]["data"]["id"]
            previous = [vid for vid, v in self.cpp_versions.items() if v["page"] == page_id]
            if any(self.cpp_versions[vid]["state"] in self.EDITABLE_STATES for vid in previous):
                self._refuse("the custom product page already has an editable version")
            version_id = self._new_version(page_id, self.new_version_state, body["data"].get("attributes", {}).get("deepLink"))
            if self.prepopulate and previous:
                for loc in [l for l in self.cpp_locs.values() if l["version"] == previous[-1]]:
                    self._new_loc(version_id, loc["locale"], loc["promotionalText"], loc["keywords"])
            return {"data": {"id": version_id, "type": "appCustomProductPageVersions"}}
        if method == "PATCH" and parts[:1] == ["appCustomProductPageVersions"]:
            self.cpp_versions[parts[1]]["deepLink"] = body["data"]["attributes"].get("deepLink")
            return {"data": {"id": parts[1]}}
        if method == "GET" and len(parts) == 3 and parts[0] == "appCustomProductPageVersions" and parts[2] == "appCustomProductPageLocalizations":
            return {"data": [{"id": lid, "type": "appCustomProductPageLocalizations",
                              "attributes": {"locale": l["locale"], "promotionalText": l["promotionalText"]}}
                             for lid, l in self.cpp_locs.items() if l["version"] == parts[1]]}
        if method == "POST" and parts == ["appCustomProductPageLocalizations"]:
            version_id = body["data"]["relationships"]["appCustomProductPageVersion"]["data"]["id"]
            if self.cpp_versions[version_id]["state"] in self.LIVE_STATES:
                self._refuse("cannot add a localization to a live custom product page version")
            attrs = body["data"]["attributes"]
            return {"data": {"id": self._new_loc(version_id, attrs["locale"], attrs.get("promotionalText", ""), [])}}
        if method == "PATCH" and parts[:1] == ["appCustomProductPageLocalizations"]:
            self.cpp_locs[parts[1]]["promotionalText"] = body["data"]["attributes"]["promotionalText"]
            return {"data": {"id": parts[1]}}
        if method == "DELETE" and parts[:1] == ["appCustomProductPageLocalizations"] and len(parts) == 2:
            if self._live_loc(parts[1]):
                self._refuse("cannot delete a localization of a live custom product page version")
            self.cpp_locs.pop(parts[1])
            return {}
        if method == "GET" and len(parts) == 3 and parts[0] == "appCustomProductPageLocalizations" and parts[2] == "searchKeywords":
            return {"data": [{"type": "appKeywords", "id": k} for k in self.cpp_locs[parts[1]]["keywords"]]}
        if len(parts) == 4 and parts[0] == "appCustomProductPageLocalizations" and parts[2:] == ["relationships", "searchKeywords"]:
            ids = [item["id"] for item in body["data"]]
            keywords = self.cpp_locs[parts[1]]["keywords"]
            if method == "POST":
                keywords.extend(i for i in ids if i not in keywords)
            elif method == "DELETE":
                self.cpp_locs[parts[1]]["keywords"] = [k for k in keywords if k not in ids]
            return {}
        return None

    def _page_row(self, pid):
        p = self.pages[pid]
        return {"id": pid, "type": "appCustomProductPages",
                "attributes": {"name": p["name"], "visible": p["visible"], "url": f"https://apps.apple.com/app/id1?ppid={pid}"}}

    def _hidden(self, pid):
        return self.hide_created and pid in self.created_pages

    def _create_page(self, body):
        data = body["data"]
        page_id = self.next_id("page")
        self.created_pages.add(page_id)
        template = data["relationships"].get("appStoreVersionTemplate")
        self.pages[page_id] = {"name": data["attributes"]["name"], "visible": self.create_visible,
                               "template": template and template["data"]["id"]}
        included = body.get("included", [])
        version_item = next(i for i in included if i["type"] == "appCustomProductPageVersions")
        assert data["relationships"]["appCustomProductPageVersions"]["data"][0]["id"] == version_item["id"]
        version_id = self._new_version(page_id, "PREPARE_FOR_SUBMISSION", version_item.get("attributes", {}).get("deepLink"))
        wanted = {ref["id"] for ref in version_item["relationships"]["appCustomProductPageLocalizations"]["data"]}
        for item in included:
            if item["type"] == "appCustomProductPageLocalizations":
                assert item["id"] in wanted and item["id"].startswith("${")
                self._new_loc(version_id, item["attributes"]["locale"], item["attributes"].get("promotionalText", ""), [])
        return {"data": {"id": page_id, "type": "appCustomProductPages", "attributes": {"visible": self.create_visible}}}


class FakeNominationConnect(FakeConnect):
    def __init__(self):
        super().__init__()
        self.nominations = {}   # id -> attributes (incl. "state")

    def route(self, method, parts, query, body):
        if parts[:1] == ["nominations"]:
            if method == "GET" and len(parts) == 1:
                assert "filter[state]" in query, "GET /v1/nominations requires filter[state]"
                wanted = set(query["filter[state]"].split(","))
                return {"data": [{"id": nid, "type": "nominations", "attributes": dict(attrs)}
                                 for nid, attrs in self.nominations.items() if attrs["state"] in wanted]}
            if method == "POST":
                attrs = dict(body["data"]["attributes"])
                assert all(isinstance(a["id"], str) for a in body["data"]["relationships"]["relatedApps"]["data"])
                attrs["state"] = "SUBMITTED" if attrs.pop("submitted") else "DRAFT"
                nid = self.next_id("nom")
                self.nominations[nid] = attrs
                return {"data": {"id": nid, "type": "nominations", "attributes": attrs}}
            if method == "PATCH":
                attrs = dict(body["data"]["attributes"])
                if attrs.pop("submitted", False):
                    self.nominations[parts[1]]["state"] = "SUBMITTED"
                self.nominations[parts[1]].update(attrs)
                return {"data": {"id": parts[1]}}
        return super().route(method, parts, query, body)
