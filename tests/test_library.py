# tests/test_library.py
import unittest

from asokit import asc, library
from tests.fakes import REFDATA, FakeConnect, install
from tests.test_creative import png_bytes


def catalog():
    return library.Catalog(REFDATA["data"][0]["attributes"])


class CatalogTests(unittest.TestCase):
    def test_fetch_reads_the_single_ref_datum(self):
        install(self, FakeConnect())
        cat = library.Catalog.fetch("t")
        self.assertEqual(cat.features(), {"APP_STORE_VERSIONS", "CUSTOM_PRODUCT_PAGES"})

    def test_groups_for_spec_respects_policy(self):
        cat = catalog()
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.HEADER, "S_UNIV"), ["G_HEADER"])
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.SEARCH, "S_UNIV"), ["G_SEARCH"])
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.SEARCH, "S_HEADER"), [])
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.SCREENSHOT, "S_410"), ["G_WATCH_U", "G_WATCH_10"])

    def test_unsupported_feature_or_type(self):
        cat = catalog()
        self.assertFalse(cat.supports("IN_APP_EVENTS", library.HEADER))
        self.assertEqual(cat.groups_for_spec("IN_APP_EVENTS", library.HEADER, "S_UNIV"), [])

    def test_specs_matching_by_dimensions(self):
        cat = catalog()
        self.assertEqual([s["specId"] for s in cat.specs_matching(library.HEADER, 5244, 2950)], ["S_UNIV"])
        self.assertEqual(cat.specs_matching(library.SEARCH, 3840, 1646), [])

    def test_limits_categories_and_display_class(self):
        cat = catalog()
        self.assertEqual(cat.max_count("APP_STORE_VERSIONS", library.SCREENSHOT, "G_IPHONE_L"), 10)
        self.assertEqual(cat.max_count("APP_STORE_VERSIONS", library.HEADER, "G_HEADER"), 1)
        self.assertIsNone(cat.max_count("APP_STORE_VERSIONS", library.HEADER, "G_NOPE"))
        self.assertEqual(cat.accepts(library.HEADER), {"CREATIVE_ASSETS"})
        self.assertEqual(cat.display_class("G_WATCH_U"), "WATCH_ULTRA")
        self.assertEqual(cat.groups_for_display_class("APP_STORE_VERSIONS", library.SCREENSHOT, "WATCH_ULTRA"), ["G_WATCH_U"])

    def test_summary_mentions_every_policy(self):
        text = "\n".join(catalog().summary())
        self.assertIn("CUSTOM_PRODUCT_PAGES", text)
        self.assertIn("G_SEARCH", text)
        self.assertIn("5244×2950", text)


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())

    def test_upload_reserves_puts_and_commits(self):
        data = png_bytes(5244, 2950)
        ref, sha = library.reference_name("en-US.png", data)
        self.assertTrue(ref.startswith(f"asokit:{sha}:"))
        image_id = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        self.assertEqual(self.fake.images[image_id]["state"], "PREPARE_FOR_SUBMISSION")
        self.assertIn(("PUT", f"https://upload.invalid/{image_id}"), self.fake.log)

    def test_reuse_states(self):
        data = png_bytes(5244, 2950)
        ref, _ = library.reference_name("en-US.png", data)
        image_id = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        for state, expected in [("APPROVED", image_id), ("UPLOAD_COMPLETE", image_id), ("FAILED", None), ("ARCHIVED", None)]:
            with self.subTest(state=state):
                self.fake.images[image_id]["state"] = state
                found = library.find_reusable("lib1", ref, library.CREATIVE, "t")
                self.assertEqual(found and found["id"], expected)

    def test_awaiting_upload_is_not_reused(self):
        data = png_bytes(5244, 2950)
        ref, _ = library.reference_name("en-US.png", data)
        orphan = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        self.fake.images[orphan]["state"] = "AWAITING_UPLOAD"
        uploader = library.Uploader("lib1", "t", apply=True)
        result = uploader.ensure("en-US.png", data, library.CREATIVE)
        self.assertEqual(result["status"], "uploaded")
        self.assertNotEqual(result["asset"], orphan)
        states = library.wait_processed("lib1", uploader.new_ids, "t", timeout_s=5)
        self.assertEqual(states[result["asset"]]["state"], "PREPARE_FOR_SUBMISSION")

    def test_rejected_match_stops(self):
        data = png_bytes(5244, 2950)
        ref, _ = library.reference_name("en-US.png", data)
        image_id = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        self.fake.images[image_id]["state"] = "REJECTED"
        with self.assertRaises(library.RejectedAsset):
            library.Uploader("lib1", "t", apply=True).ensure("en-US.png", data, library.CREATIVE)

    def test_in_run_cache_uploads_identical_bytes_once(self):
        data = png_bytes(5244, 2950)
        uploader = library.Uploader("lib1", "t", apply=True)
        first = uploader.ensure("en-US.png", data, library.CREATIVE)
        second = uploader.ensure("en-US.png", data, library.CREATIVE)
        self.assertEqual(first["asset"], second["asset"])
        self.assertEqual(sum(1 for e in self.fake.log if e[:2] == ("POST", "/appAssetLibraryImages")), 1)

    def test_dry_run_never_writes(self):
        uploader = library.Uploader("lib1", "t", apply=False)
        result = uploader.ensure("en-US.png", png_bytes(5244, 2950), library.CREATIVE)
        self.assertEqual(result["status"], "would-upload")
        self.assertTrue(result["asset"].startswith("new:"))
        self.assertEqual(self.fake.writes(), [])

    def test_wait_reports_failed_without_hanging(self):
        self.fake.after_commit = "FAILED"
        uploader = library.Uploader("lib1", "t", apply=True)
        result = uploader.ensure("en-US.png", png_bytes(5244, 2950), library.CREATIVE)
        states = library.wait_processed("lib1", uploader.new_ids, "t", timeout_s=5)
        self.assertEqual(states[result["asset"]]["state"], "FAILED")


class ReuseRulingTests(unittest.TestCase):
    """Fix round 1: rejected twins, preference for processed rows, wait timeout."""

    def setUp(self):
        self.fake = install(self, FakeConnect())
        self.data = png_bytes(5244, 2950)
        self.ref, _ = library.reference_name("en-US.png", self.data)

    def twins(self, *states):
        ids = []
        for state in states:
            image_id = library.upload_image("lib1", "en-US.png", self.data, library.CREATIVE, self.ref, "t")
            self.fake.images[image_id]["state"] = state
            ids.append(image_id)
        return ids

    def test_rejected_with_unreviewed_twin_stops(self):
        for twin in ("WAITING_FOR_REVIEW", "PREPARE_FOR_SUBMISSION", "UPLOAD_COMPLETE", "IN_REVIEW"):
            with self.subTest(twin=twin):
                self.fake.images.clear()
                self.twins("REJECTED", twin)
                with self.assertRaises(library.RejectedAsset):
                    library.find_reusable("lib1", self.ref, library.CREATIVE, "t")

    def test_rejected_with_approved_twin_reuses_approved(self):
        for twin in ("APPROVED", "ACCEPTED"):
            with self.subTest(twin=twin):
                self.fake.images.clear()
                _, waiting, good = self.twins("REJECTED", "WAITING_FOR_REVIEW", twin)
                found = library.find_reusable("lib1", self.ref, library.CREATIVE, "t")
                self.assertEqual(found["id"], good)

    def test_prefers_processed_over_upload_complete(self):
        pending, processed = self.twins("UPLOAD_COMPLETE", "PREPARE_FOR_SUBMISSION")
        self.fake.images[pending]["specId"] = None  # Apple assigns specId only once processed
        found = library.find_reusable("lib1", self.ref, library.CREATIVE, "t")
        self.assertEqual(found["id"], processed)
        self.assertIsNotNone(found["attributes"]["specId"])

    def test_upload_complete_alone_is_still_reused(self):
        (only,) = self.twins("UPLOAD_COMPLETE")
        self.assertEqual(library.find_reusable("lib1", self.ref, library.CREATIVE, "t")["id"], only)

    def test_wait_marks_unfinished_ids_as_timeout(self):
        self.fake.after_commit = "UPLOAD_COMPLETE"
        uploader = library.Uploader("lib1", "t", apply=True)
        result = uploader.ensure("en-US.png", self.data, library.CREATIVE)
        states = library.wait_processed("lib1", uploader.new_ids + ["img-missing"], "t", timeout_s=0)
        self.assertEqual(states[result["asset"]]["state"], "TIMEOUT")
        self.assertEqual(states["img-missing"]["state"], "TIMEOUT")
        self.assertNotIn("TIMEOUT", library.PROCESSED)

    def test_wait_keeps_final_states_alongside_timeouts(self):
        uploader = library.Uploader("lib1", "t", apply=True)
        done = uploader.ensure("en-US.png", self.data, library.CREATIVE)["asset"]
        states = library.wait_processed("lib1", [done, "img-missing"], "t", timeout_s=0)
        self.assertEqual(states[done]["state"], "PREPARE_FOR_SUBMISSION")
        self.assertEqual(states["img-missing"]["state"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()


class ReplaceGroupTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())
        self.fake.default_spec = "S_1290"
        self.uploader = library.Uploader("lib1", "t", apply=True)

    def asset(self, name):
        return self.uploader.ensure(name, png_bytes(1290, 2796) + name.encode(), library.MEDIA)

    def current(self):
        return [p for p in library.surface_placements("appStoreVersionLocalization", "vl-en", "t") if p["group"] == "G_IPHONE_L"]

    def replace(self, names, max_count=10):
        desired = [{"asset": a["asset"], "sha": a["sha"]} for a in (self.asset(n) for n in names)]
        return library.replace_group(desired, library.SCREENSHOT, "G_IPHONE_L", "appStoreVersionLocalization", "vl-en",
                                     max_count, "t", apply=True, current=self.current())

    def test_first_fill_then_unchanged_is_zero_writes(self):
        self.replace(["a.png", "b.png"])
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["a.png", "b.png"])
        before = len(self.fake.writes())
        result = self.replace(["a.png", "b.png"])
        self.assertEqual(result["mode"], "unchanged")
        self.assertEqual(len(self.fake.writes()), before)

    def test_reorder_only_issues_one_ordering_request(self):
        self.replace(["a.png", "b.png"])
        before = len(self.fake.writes())
        result = self.replace(["b.png", "a.png"])
        self.assertEqual(result["mode"], "reorder")
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["b.png", "a.png"])
        self.assertEqual(len(self.fake.writes()), before + 1)

    def test_place_first_under_capacity_keeps_shared_assets(self):
        self.replace(["a.png", "b.png"])
        c, a = self.asset("c.png"), self.asset("a.png")
        start = len(self.fake.log)
        result = library.replace_group([{"asset": c["asset"], "sha": c["sha"]}, {"asset": a["asset"], "sha": a["sha"]}],
                                       library.SCREENSHOT, "G_IPHONE_L", "appStoreVersionLocalization", "vl-en",
                                       10, "t", apply=True, current=self.current())
        self.assertEqual(result["mode"], "place-first")
        self.assertEqual((result["place"], result["unplace"]), (1, 1))
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["c.png", "a.png"])
        tail = [entry[:2] for entry in self.fake.log[start:]]
        first_place = tail.index(("POST", "/appAssetLibraryPlacements"))
        first_delete = next(i for i, entry in enumerate(tail) if entry[0] == "DELETE")
        self.assertLess(first_place, first_delete)

    def test_unplace_first_at_capacity(self):
        self.replace(["a.png"], max_count=1)
        result = self.replace(["b.png"], max_count=1)
        self.assertEqual(result["mode"], "unplace-first")
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["b.png"])

    def test_abort_between_unplace_and_place_reports_gap(self):
        self.replace(["a.png"], max_count=1)
        b = self.asset("b.png")
        self.fake.fail_on = ("POST", "/appAssetLibraryPlacements")
        with self.assertRaises(library.PartialPlacement) as caught:
            library.replace_group([{"asset": b["asset"], "sha": b["sha"]}], library.SCREENSHOT, "G_IPHONE_L",
                                  "appStoreVersionLocalization", "vl-en", 1, "t", apply=True, current=self.current())
        self.assertIn("0 of 1", str(caught.exception))

    def test_never_deletes_assets(self):
        self.replace(["a.png", "b.png"])
        self.replace(["c.png"])
        self.assertFalse(any(e[0] == "DELETE" and "/appAssetLibraryImages" in e[1] for e in self.fake.log))


class SyncGroupsTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())
        self.catalog = library.Catalog.fetch("t")

    def creative_request(self, locale, parent):
        return {"locale": locale, "parent_kind": "appStoreVersionLocalization", "parent_id": parent,
                "placement_types": [library.HEADER, library.SEARCH], "category": library.CREATIVE,
                "files": [(f"{locale}.png", png_bytes(5244, 2950) + locale.encode())]}

    def test_creative_lands_in_header_and_search(self):
        actions = library.sync_groups([self.creative_request("en-US", "vl-en"), self.creative_request("de-DE", "vl-de")],
                                      self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertEqual(self.fake.group("vl-en", "G_HEADER"), ["en-US.png"])
        self.assertEqual(self.fake.group("vl-en", "G_SEARCH"), ["en-US.png"])
        self.assertEqual(self.fake.group("vl-de", "G_HEADER"), ["de-DE.png"])
        self.assertEqual({a["group"] for a in actions}, {"G_HEADER", "G_SEARCH"})

    def test_uploads_all_before_any_placement(self):
        library.sync_groups([self.creative_request("en-US", "vl-en"), self.creative_request("de-DE", "vl-de")],
                            self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        kinds = [e[1] for e in self.fake.log if e[0] == "POST"]
        last_upload = max(i for i, k in enumerate(kinds) if k == "/appAssetLibraryImages")
        first_place = min(i for i, k in enumerate(kinds) if k == "/appAssetLibraryPlacements")
        self.assertLess(last_upload, first_place)

    def test_processing_failure_places_nothing(self):
        self.fake.after_commit = "FAILED"
        with self.assertRaises(asc.ASCError):
            library.sync_groups([self.creative_request("en-US", "vl-en")], self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertFalse(any(e[:2] == ("POST", "/appAssetLibraryPlacements") for e in self.fake.log))

    def test_spec_mismatch_is_reported(self):
        self.fake.spec_by_file = {"en-US.png": "S_HEADER"}   # Apple matched the file to the header-only spec
        with self.assertRaises(asc.ASCError) as caught:
            library.sync_groups([self.creative_request("en-US", "vl-en")], self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertIn("S_HEADER", str(caught.exception))

    def test_dry_run_plans_new_parent_without_reads(self):
        request = dict(self.creative_request("en-US", None))
        actions = library.sync_groups([request], self.catalog, "CUSTOM_PRODUCT_PAGES", "lib1", "t", apply=False)
        self.assertEqual(len(actions), 2)
        self.assertEqual(self.fake.writes(), [])

    def test_watch_ambiguity_resolved_by_display_class(self):
        request = {"locale": "en-US", "parent_kind": "appStoreVersionLocalization", "parent_id": "vl-en",
                   "placement_types": [library.SCREENSHOT], "category": library.MEDIA, "display_class": "WATCH_ULTRA",
                   "files": [("w.png", png_bytes(410, 502))]}
        self.fake.default_spec = "S_410"
        library.sync_groups([request], self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertEqual(self.fake.group("vl-en", "G_WATCH_U"), ["w.png"])
        self.assertEqual(self.fake.group("vl-en", "G_WATCH_10"), [])


class ExperimentGuardTests(unittest.TestCase):
    def test_running_and_in_review_experiments_block(self):
        fake = install(self, FakeConnect())
        self.assertIsNone(library.active_experiment("1", "t"))
        fake.experiments = [{"id": "e1", "attributes": {"name": "Icon test", "state": "APPROVED", "startDate": "2026-01-01T00:00:00Z", "endDate": None}}]
        self.assertEqual(library.active_experiment("1", "t"), "Icon test")
        fake.experiments = [{"id": "e1", "attributes": {"name": "Old", "state": "APPROVED", "startDate": "2026-01-01T00:00:00Z", "endDate": "2026-02-01T00:00:00Z"}}]
        self.assertIsNone(library.active_experiment("1", "t"))
        fake.experiments = [{"id": "e2", "attributes": {"name": "Queued", "state": "WAITING_FOR_REVIEW"}}]
        self.assertEqual(library.active_experiment("1", "t"), "Queued")
