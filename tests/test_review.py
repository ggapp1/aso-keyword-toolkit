# tests/test_review.py
import unittest

from asokit import review
from tests.fakes import FakeConnect, install

CPP_ITEM = ("appCustomProductPageVersion", "appCustomProductPageVersions", "cv1")


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())

    def test_creates_submission_adds_items_and_submits(self):
        result = review.submit("1", [CPP_ITEM], "t", apply=True)
        sub = self.fake.submissions[result["submission"]]
        self.assertEqual(sub["items"], [CPP_ITEM])
        self.assertEqual(sub["state"], "WAITING_FOR_REVIEW")

    def test_dry_run_writes_nothing(self):
        result = review.submit("1", [CPP_ITEM], "t", apply=False)
        self.assertEqual(result["submission"], "(new)")
        self.assertEqual(self.fake.writes(), [])

    def test_in_flight_submission_stops(self):
        self.fake.submissions["s0"] = {"state": "WAITING_FOR_REVIEW", "items": []}
        with self.assertRaises(review.SubmissionBlocked):
            review.submit("1", [CPP_ITEM], "t", apply=True)

    def test_foreign_item_in_draft_stops(self):
        self.fake.submissions["s0"] = {"state": "READY_FOR_REVIEW", "items": [("appStoreVersion", "appStoreVersions", "v1")]}
        with self.assertRaises(review.SubmissionBlocked) as caught:
            review.submit("1", [CPP_ITEM], "t", apply=True)
        self.assertIn("appStoreVersion", str(caught.exception))
        self.assertEqual(self.fake.submissions["s0"]["state"], "READY_FOR_REVIEW")

    def test_clean_draft_is_reused(self):
        self.fake.submissions["s0"] = {"state": "READY_FOR_REVIEW", "items": [CPP_ITEM]}
        other = ("appCustomProductPageVersion", "appCustomProductPageVersions", "cv2")
        result = review.submit("1", [CPP_ITEM, other], "t", apply=True)
        self.assertEqual(result["submission"], "s0")
        self.assertEqual(self.fake.submissions["s0"]["items"], [CPP_ITEM, other])
        self.assertEqual(self.fake.submissions["s0"]["state"], "WAITING_FOR_REVIEW")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())

    def test_no_open_submission_passes(self):
        self.assertIsNone(review.preflight("1", "t", {"appAssetLibraryImage"}))
        self.assertEqual(self.fake.writes(), [])

    def test_in_flight_blocks(self):
        self.fake.submissions["s0"] = {"state": "UNRESOLVED_ISSUES", "items": []}
        with self.assertRaises(review.SubmissionBlocked):
            review.preflight("1", "t", {"appAssetLibraryImage"})

    def test_draft_with_disallowed_relationship_blocks(self):
        self.fake.submissions["s0"] = {"state": "READY_FOR_REVIEW", "items": [CPP_ITEM]}
        with self.assertRaises(review.SubmissionBlocked) as caught:
            review.preflight("1", "t", {"appAssetLibraryImage"})
        self.assertIn("appCustomProductPageVersion", str(caught.exception))

    def test_draft_with_allowed_items_passes(self):
        self.fake.submissions["s0"] = {"state": "READY_FOR_REVIEW", "items": [CPP_ITEM]}
        self.assertEqual(review.preflight("1", "t", {"appCustomProductPageVersion"}), "s0")
        self.assertEqual(self.fake.writes(), [])


if __name__ == "__main__":
    unittest.main()
