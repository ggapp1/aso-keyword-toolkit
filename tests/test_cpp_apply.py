# tests/test_cpp_apply.py
import json
import tempfile
import unittest
from pathlib import Path

from asokit import asc, cpp, cpp_apply, library, review
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



class PushTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeCppConnect())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = make_doc(self.tmp.name, [page(extra_locales={"en-GB": {"same": "en-US", "keywords": ["bpd", "borderline"]}})])
        self.lines = []

    def push(self, apply=True, **kwargs):
        return cpp_apply.push("1", self.doc, "t", apply, out=self.lines.append, **kwargs)

    def test_dry_run_new_page_writes_nothing(self):
        result = self.push(apply=False)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["actions"][0]["op"], "create_page")
        self.assertEqual(self.fake.writes(), [])

    def test_apply_creates_hidden_page_with_keywords_and_media(self):
        result = self.push()
        self.assertEqual(result["problems"], [])
        page_id = self.fake.page_named("BPD tracker")
        self.assertFalse(self.fake.pages[page_id]["visible"])
        self.assertEqual(self.fake.pages[page_id]["template"], "v0")
        locs = {l["locale"]: (lid, l) for lid, l in self.fake.cpp_locs.items()}
        self.assertEqual(sorted(locs["en-US"][1]["keywords"]), ["borderline", "bpd"])
        en_us = locs["en-US"][0]
        self.assertEqual(self.fake.group(en_us, "G_IPHONE_L"), ["06-entry.png", "02-stats.png"])
        self.assertEqual(self.fake.group(en_us, "G_HEADER"), ["en-US.png"])
        self.assertEqual(self.fake.group(en_us, "G_SEARCH"), ["en-US.png"])

    def test_second_push_is_a_no_op(self):
        self.push()
        before = len(self.fake.writes())
        result = self.push()
        self.assertEqual([a for a in result["actions"]], [])
        self.assertEqual(len(self.fake.writes()), before)

    def test_live_page_keyword_change_applies_in_place(self):
        self.push()
        page_id = self.fake.page_named("BPD tracker")
        for version in self.fake.cpp_versions.values():
            if version["page"] == page_id:
                version["state"] = "APPROVED"
        for loc in self.fake.cpp_locs.values():
            loc["keywords"] = ["bpd"]
        versions_before = len(self.fake.cpp_versions)
        result = self.push()
        self.assertEqual(len(self.fake.cpp_versions), versions_before)
        self.assertEqual({a["op"] for a in result["actions"]}, {"add_keywords"})
        self.assertTrue(all(a["live"] for a in result["actions"]))
        self.assertTrue(all(sorted(l["keywords"]) == ["borderline", "bpd"] for l in self.fake.cpp_locs.values()))

    def test_live_media_change_creates_version_and_fills_it(self):
        self.push()
        page_id = self.fake.page_named("BPD tracker")
        for version in self.fake.cpp_versions.values():
            version["state"] = "APPROVED"
        self.doc["pages"][0]["locales"]["en-US"]["screenshots"][0]["order"] = ["02", "06"]
        self.doc["pages"][0]["locales"]["en-US"]["promotionalText"] = "Track mood swings and triggers."
        result = self.push()
        ops = [a["op"] for a in result["actions"]]
        # en-GB copies en-US's promo: both edited in place on the live version, then the version is created
        self.assertEqual(ops[:3], ["update_promo", "update_promo", "create_version"])
        versions = [v for v in self.fake.cpp_versions.values() if v["page"] == page_id]
        self.assertEqual(len(versions), 2)
        newest = max(self.fake.cpp_versions, key=lambda vid: int(self.fake.cpp_versions[vid]["version"]))
        new_locs = {l["locale"]: lid for lid, l in self.fake.cpp_locs.items() if l["version"] == newest}
        self.assertEqual(set(new_locs), {"en-US", "en-GB"})
        self.assertEqual(self.fake.group(new_locs["en-US"], "G_IPHONE_L"), ["02-stats.png", "06-entry.png"])

    def test_failed_placement_resyncs_then_converges(self):
        self.push()
        en_us = next(lid for lid, l in self.fake.cpp_locs.items() if l["locale"] == "en-US")
        failed_id = next(pid for pid, p in self.fake.placements.items() if p["parent_id"] == en_us and p["group"] == "G_IPHONE_L")
        self.fake.placements[failed_id]["state"] = "FAILED"
        result = self.push()
        self.assertEqual([a["op"] for a in result["actions"]], ["sync_media"])
        self.assertNotIn(failed_id, self.fake.placements)
        self.assertEqual(self.fake.group(en_us, "G_IPHONE_L"), ["06-entry.png", "02-stats.png"])
        before = len(self.fake.writes())
        self.assertEqual(self.push()["actions"], [])
        self.assertEqual(len(self.fake.writes()), before)

    def test_prepopulated_new_version_is_not_duplicated(self):
        self.fake.prepopulate = True
        self.test_live_media_change_creates_version_and_fills_it()

    def test_validation_problems_stop_before_any_write(self):
        self.doc["pages"][0]["locales"]["en-US"]["keywords"] = ["anxiety"]
        result = self.push()
        self.assertTrue(result["problems"])
        self.assertEqual(self.fake.writes(), [])

    def approve_all(self):
        for version in self.fake.cpp_versions.values():
            version["state"] = "APPROVED"

    def test_processing_failure_on_page_two_blocks_every_surface_write(self):
        self.push()
        self.approve_all()
        self.doc["pages"][0]["locales"]["en-US"]["keywords"] = ["bpd"]          # page 1: a live in-place edit
        meds = page(name="Meds", keywords=())
        meds["locales"]["en-US"]["creative"] = "meds"                            # page 2: new page, new creative
        self.doc["pages"].append(meds)
        self.fake.after_commit = "FAILED"
        start = len(self.fake.writes())
        with self.assertRaises(asc.ASCError):
            self.push()
        surface = [w for w in self.fake.writes()[start:] if not w[1].startswith("/appAssetLibraryImages")]
        self.assertEqual(surface, [])
        self.assertEqual(sorted(self.fake.cpp_locs[l]["keywords"] for l in self.fake.cpp_locs)[0], ["borderline", "bpd"])

    def test_created_page_not_readable_raises_without_a_second_create(self):
        self.fake.hide_created = True
        with self.assertRaises(asc.ASCError):
            self.push()
        creates = [w for w in self.fake.writes() if w[:2] == ("POST", "/appCustomProductPages")]
        self.assertEqual(len(creates), 1)

    def test_created_version_not_editable_raises_without_a_second_create(self):
        self.push()
        self.approve_all()
        self.doc["pages"][0]["locales"]["en-US"]["screenshots"][0]["order"] = ["02", "06"]
        self.fake.new_version_state = "WAITING_FOR_REVIEW"
        with self.assertRaises(asc.ASCError):
            self.push()
        creates = [w for w in self.fake.writes() if w[:2] == ("POST", "/appCustomProductPageVersions")]
        self.assertEqual(len(creates), 1)

    def test_keyword_move_removes_before_adding(self):
        self.doc["pages"] = [page(name="Beta", keywords=()), page(name="Alpha", keywords=("bpd",))]
        self.push()
        self.approve_all()
        self.doc["pages"][0]["locales"]["en-US"]["keywords"] = ["bpd"]
        self.doc["pages"][1]["locales"]["en-US"]["keywords"] = []
        start = len(self.fake.log)
        result = self.push()
        self.assertEqual(result["problems"], [])
        by_page = {self.fake.pages[self.fake.cpp_versions[l["version"]]["page"]]["name"]: l["keywords"] for l in self.fake.cpp_locs.values()}
        self.assertEqual(by_page, {"Alpha": [], "Beta": ["bpd"]})
        tail = [(e[0], e[1]) for e in self.fake.log[start:] if e[1].endswith("/relationships/searchKeywords")]
        self.assertEqual([m for m, _ in tail], ["DELETE", "POST"])

    def test_create_patches_hidden_unless_response_says_hidden(self):
        self.fake.create_visible = None   # attribute missing/unknown in the response
        self.push()
        self.assertEqual(sum(1 for w in self.fake.writes() if w[0] == "PATCH" and w[1].startswith("/appCustomProductPages/")), 1)

    def test_create_skips_patch_when_response_is_hidden(self):
        self.fake.create_visible = False
        self.push()
        self.assertFalse(any(w[0] == "PATCH" and w[1].startswith("/appCustomProductPages/") for w in self.fake.writes()))

    def test_fake_refuses_structural_edits_on_live_versions(self):
        self.push()
        page_id = self.fake.page_named("BPD tracker")
        version_id = next(v for v, row in self.fake.cpp_versions.items() if row["page"] == page_id)
        with self.assertRaises(asc.ASCError):   # an editable version already exists
            asc.call("POST", "/appCustomProductPageVersions", "t", {"data": {"type": "appCustomProductPageVersions",
                     "relationships": {"appCustomProductPage": {"data": {"type": "appCustomProductPages", "id": page_id}}}}})
        self.approve_all()
        with self.assertRaises(asc.ASCError):
            asc.call("POST", "/appCustomProductPageLocalizations", "t", {"data": {"type": "appCustomProductPageLocalizations",
                     "attributes": {"locale": "fr-FR"},
                     "relationships": {"appCustomProductPageVersion": {"data": {"type": "appCustomProductPageVersions", "id": version_id}}}}})
        placement = next(iter(self.fake.placements))
        with self.assertRaises(asc.ASCError):
            asc.call("DELETE", f"/appAssetLibraryPlacements/{placement}", "t")

    def test_pages_scope(self):
        self.doc["pages"].append(page(name="Report", keywords=()))
        self.push(pages=["Report"])
        self.assertEqual([p["name"] for p in self.fake.pages.values()], ["Report"])




class PublishSubmitTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeCppConnect())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = make_doc(self.tmp.name, [page()])
        cpp_apply.push("1", self.doc, "t", True, out=lambda line: None)
        self.page_id = self.fake.page_named("BPD tracker")

    def set_state(self, state):
        for version in self.fake.cpp_versions.values():
            version["state"] = state

    def test_publish_refuses_unapproved(self):
        with self.assertRaises(cpp_apply.PublishError):
            cpp_apply.publish("1", ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertFalse(self.fake.pages[self.page_id]["visible"])

    def test_publish_and_hide(self):
        self.set_state("APPROVED")
        changes = cpp_apply.publish("1", ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertTrue(self.fake.pages[self.page_id]["visible"])
        self.assertEqual(changes[0]["keywords"]["en-US"], ["borderline", "bpd"])
        cpp_apply.publish("1", ["BPD tracker"], "t", apply=True, hide=True, out=lambda line: None)
        self.assertFalse(self.fake.pages[self.page_id]["visible"])

    def test_publish_dry_run_changes_nothing(self):
        self.set_state("APPROVED")
        cpp_apply.publish("1", ["BPD tracker"], "t", apply=False, out=lambda line: None)
        self.assertFalse(self.fake.pages[self.page_id]["visible"])

    def test_submit_adds_only_the_named_page_version(self):
        result = cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
        items = self.fake.submissions[result["submission"]]["items"]
        self.assertEqual([i[0] for i in items], ["appCustomProductPageVersion"])

    def test_submit_refuses_failed_placement(self):
        original = self.fake._surface

        def failing(kind, parent):
            result = original(kind, parent)
            for row in result["data"]:
                row["attributes"]["state"] = "FAILED"
            return result
        self.fake._surface = failing
        with self.assertRaises(review.SubmissionBlocked):
            cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertEqual(self.fake.submissions, {})

    def test_submit_refuses_in_review_page(self):
        self.set_state("IN_REVIEW")
        with self.assertRaises(review.SubmissionBlocked):
            cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)

    def other_doc(self, pages):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return make_doc(tmp.name, pages)

    def test_publish_is_all_or_nothing(self):
        self.set_state("APPROVED")
        self.fake.add_page("Draft page", state="PREPARE_FOR_SUBMISSION", visible=False)
        with self.assertRaises(cpp_apply.PublishError):
            cpp_apply.publish("1", ["BPD tracker", "Draft page"], "t", apply=True, out=lambda line: None)
        self.assertFalse(self.fake.pages[self.page_id]["visible"])

    def test_submit_refuses_declared_locale_missing_from_version(self):
        doc = self.other_doc([page(extra_locales={"en-GB": {"promotionalText": "Hi", "keywords": ["symptom"]}})])
        with self.assertRaisesRegex(review.SubmissionBlocked, "en-GB: declared in the file but missing"):
            cpp_apply.submit("1", doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertEqual(self.fake.submissions, {})

    def test_submit_refuses_declared_family_not_placed(self):
        declared = page()
        declared["locales"]["en-US"]["screenshots"].append(
            {"dir": "shots/en-US", "order": ["06", "02"], "display": "APP_IPAD_PRO_3GEN_129"})
        doc = self.other_doc([declared])
        with self.assertRaisesRegex(review.SubmissionBlocked, "APP_IPAD_PRO_3GEN_129 screenshots but none are placed"):
            cpp_apply.submit("1", doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertEqual(self.fake.submissions, {})

    def test_submit_refuses_declared_creative_without_search_placement(self):
        search = [pid for pid, p in self.fake.placements.items() if p["group"] == "G_SEARCH"]
        self.assertTrue(search)
        for pid in search:
            self.fake.placements.pop(pid)
        with self.assertRaisesRegex(review.SubmissionBlocked, "creative.*search"):
            cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertEqual(self.fake.submissions, {})

    def test_submit_dry_run_happy_path(self):
        result = cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=False, out=lambda line: None)
        self.assertEqual([i[0] for i in result["add"]], ["appCustomProductPageVersion"])
        self.assertFalse(result["submitted"])
        self.assertEqual(self.fake.submissions, {})


if __name__ == "__main__":
    unittest.main()
