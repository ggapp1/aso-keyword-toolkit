# tests/test_library.py
import unittest

from asokit import library
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
