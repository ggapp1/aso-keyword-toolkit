# tests/test_cpp_apply.py
import json
import unittest
from pathlib import Path

from asokit import cpp, cpp_apply, library
from tests.fakes import FakeCppConnect, install
from tests.test_cpp import make_doc, page


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeCppConnect())

    def test_latest_version_ignores_replaced(self):
        page_id, first, _ = self.fake.add_page("BPD tracker", state="REPLACED_WITH_NEW_VERSION")
        second = self.fake._new_version(page_id, "APPROVED")
        self.assertEqual(cpp_apply.latest_version(page_id, "t")["id"], second)

    def test_snapshot_reads_promo_keywords_and_placements(self):
        _, version_id, locs = self.fake.add_page("BPD tracker", locales={"en-US": {"promo": "Hi", "keywords": ["bpd"]}})
        row = cpp_apply.list_pages("1", "t")[0]
        snap = cpp_apply.snapshot_page(row, "t")
        loc = snap["version"]["localizations"]["en-US"]
        self.assertEqual((snap["version"]["id"], snap["version"]["state"]), (version_id, "APPROVED"))
        self.assertEqual((loc["promotionalText"], loc["keywords"]), ("Hi", {"bpd": "bpd"}))
        self.assertEqual(loc["placements"], [])

    def test_online_context(self):
        self.fake.add_page("Old page", locales={"en-US": {"keywords": ["adhd"]}})
        with self._doc() as doc:
            ctx = cpp_apply.online_context("1", doc, "t", library.Catalog.fetch("t"))
        self.assertIn("bpd", ctx["pools"]["en-US"])
        self.assertIn("symptom", ctx["pools"]["en-GB"])
        self.assertEqual(ctx["live_locales"], {"en-US", "en-GB"})
        self.assertEqual(ctx["live_keywords"]["Old page"], {"en-US": {"adhd"}})
        self.assertEqual(ctx["families"], {"APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"})
        self.assertTrue(ctx["creative_supported"])
        self.assertEqual(ctx["live_version_id"], "v0")
        self.assertIsNotNone(ctx["editable_pools"])

    def test_online_context_tolerates_a_malformed_file(self):
        with self._doc() as doc:
            doc["pages"][0]["locales"]["en-US"]["keywords"] = "bpd"
            ctx = cpp_apply.online_context("1", doc, "t", library.Catalog.fetch("t"))
            problems, _ = cpp.check(doc, online=ctx)
        self.assertTrue(any("must be a list of strings" in p for p in problems))

    def _doc(self):
        import contextlib
        import tempfile

        @contextlib.contextmanager
        def manager():
            with tempfile.TemporaryDirectory() as tmp:
                yield make_doc(tmp, [page()])
        return manager()


if __name__ == "__main__":
    unittest.main()
