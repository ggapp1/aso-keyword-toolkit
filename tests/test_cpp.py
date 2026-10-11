# tests/test_cpp.py
import json
import tempfile
import unittest
from pathlib import Path

from asokit import cpp, screenshots
from tests.test_creative import png_bytes


def make_doc(tmp, pages, protected=None):
    root = Path(tmp)
    shots_dir = root / "shots" / "en-US"
    shots_dir.mkdir(parents=True)
    for name in ("01-home.png", "02-stats.png", "06-entry.png"):
        (shots_dir / name).write_bytes(png_bytes(1290, 2796) + name.encode())
    for variant in ("bpd", "meds"):
        (root / "assets-out" / variant).mkdir(parents=True)
        for locale in ("en-US", "en-GB"):
            (root / "assets-out" / variant / f"{locale}.png").write_bytes(png_bytes(5244, 2950) + f"{variant}{locale}".encode())
    doc = {"pages": pages}
    if protected is not None:
        doc["protectedKeywords"] = protected
    (root / "cpp.json").write_text(json.dumps(doc))
    return cpp.load(root / "cpp.json")


def page(name="BPD tracker", keywords=("bpd", "borderline"), extra_locales=None, **fields):
    locales = {"en-US": {"promotionalText": "Log mood swings and triggers.", "keywords": list(keywords),
                         "screenshots": [{"dir": "shots/en-US", "order": ["06", "02"], "display": "APP_IPHONE_67"}],
                         "creative": "bpd"}}
    locales.update(extra_locales or {})
    return {"name": name, "template": "appStoreVersion", "deepLink": None, "locales": locales, **fields}


def online(**overrides):
    base = {"pools": {"en-US": {"bpd", "borderline", "medication", "triggers", "cyclothymia"},
                      "en-GB": {"bpd", "borderline", "symptom"}},
            "editable_pools": None, "live_locales": {"en-US", "en-GB"}, "live_pages": set(),
            "live_keywords": {}, "families": {"APP_IPHONE_67"}, "creative_supported": True}
    base.update(overrides)
    return base


class DisplayMapTests(unittest.TestCase):
    def test_inverse_is_one_to_one(self):
        self.assertEqual(len(screenshots.LEGACY_BY_CLASS), len(screenshots.LEGACY_DISPLAY_CLASS))


class ExpandTests(unittest.TestCase):
    def test_same_copies_media_and_promo_but_never_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = make_doc(tmp, [page(extra_locales={"en-GB": {"same": "en-US"}})])
            gb = cpp.expand(doc)[0]["locales"]["en-GB"]
            self.assertEqual(gb["keywords"], [])
            self.assertEqual(gb["creative"], "bpd")
            self.assertEqual(gb["promotionalText"], "Log mood swings and triggers.")

    def test_select_screenshots_by_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = make_doc(tmp, [page()])
            entry = cpp.expand(doc)[0]["locales"]["en-US"]["screenshots"][0]
            self.assertEqual([p.name for p in cpp.select_screenshots(entry, doc["_root"])], ["06-entry.png", "02-stats.png"])


class CheckTests(unittest.TestCase):
    def check(self, tmp, pages, **kwargs):
        protected = kwargs.pop("protected", None)
        return cpp.check(make_doc(tmp, pages, protected), **kwargs)

    def test_valid_page_passes_offline_and_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.check(tmp, [page()])[0], [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.check(tmp, [page()], online=online())[0], [])

    def test_name_and_promo_limits_and_lint(self):
        long_promo = page(name="X" * 31)
        long_promo["locales"]["en-US"]["promotionalText"] = "Free trial! " * 20
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [long_promo])
        text = "\n".join(problems)
        self.assertIn("30", text)
        self.assertIn("170", text)
        self.assertIn("free", text.lower())

    def test_keyword_owned_by_two_pages_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(), page(name="Meds", keywords=("bpd", "medication"))])
        self.assertTrue(any("bpd" in p and "BPD tracker" in p for p in problems))

    def test_live_page_not_in_file_owns_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page()], online=online(live_pages={"Old page"},
                                                                  live_keywords={"Old page": {"en-US": {"borderline"}}}))
        self.assertTrue(any("Old page" in p for p in problems))

    def test_empty_keyword_sets_on_two_pages_are_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=()), page(name="Report", keywords=())])
        self.assertEqual(problems, [])

    def test_protected_keyword_needs_override(self):
        protected = {"*": ["cyclothymia"]}
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=("bpd", "cyclothymia"))], protected=protected)
        self.assertTrue(any("protected" in p for p in problems))
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=("bpd", "cyclothymia"))], protected=protected,
                                     allow_protected=["cyclothymia"])
        self.assertEqual(problems, [])

    def test_keyword_must_be_in_live_pool_matched_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=("BPD", "anxiety"))], online=online())
        self.assertEqual(len(problems), 1)
        self.assertIn("anxiety", problems[0])

    def test_editable_pool_drop_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, warnings = self.check(tmp, [page()], online=online(editable_pools={"en-US": {"bpd"}}))
        self.assertEqual(problems, [])
        self.assertTrue(any("borderline" in w for w in warnings))

    def test_locale_missing_from_live_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page()], online=online(live_locales={"en-GB"}))
        self.assertTrue(any("en-US" in p for p in problems))

    def test_without_template_every_family_needs_screenshots(self):
        bare = page()
        bare.pop("template")
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [bare], online=online(families={"APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"}))
        self.assertTrue(any("APP_IPAD_PRO_3GEN_129" in p for p in problems))

    def test_missing_creative_file(self):
        bad = page()
        bad["locales"]["en-US"]["creative"] = "nope"
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [bad])
        self.assertTrue(any("nope" in p for p in problems))

    def test_deep_link_warns_about_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, warnings = self.check(tmp, [page(deepLink="moodsync://log")])
        self.assertTrue(any("review" in w.lower() for w in warnings))



from asokit.library import reference_name


def live_snap(doc, state="APPROVED", keywords=("bpd", "borderline"), promo="Log mood swings and triggers.",
              media=True, deep_link=None, locales=("en-US",)):
    root = doc["_root"]

    def placements(loc):
        if not media:
            return []
        rows = []
        for n, name in enumerate(("06-entry.png", "02-stats.png")):
            data = (root / "shots" / "en-US" / name).read_bytes()
            rows.append({"id": f"p{n}-{loc}", "type": "APP_SCREENSHOT", "group": "G_IPHONE_L", "state": "PARENT_APPROVED",
                         "asset": f"a{n}", "sha": reference_name(name, data)[1]})
        data = (root / "assets-out" / "bpd" / f"{loc}.png").read_bytes() if (root / "assets-out" / "bpd" / f"{loc}.png").exists() else b"x"
        sha = reference_name(f"{loc}.png", data)[1]
        rows += [{"id": f"ph-{loc}", "type": "PRODUCT_PAGE_HEADER_ASSET", "group": "G_HEADER", "state": "PARENT_APPROVED", "asset": "c", "sha": sha},
                 {"id": f"ps-{loc}", "type": "APP_STORE_SEARCH_RESULTS_ASSET", "group": "G_SEARCH", "state": "PARENT_APPROVED", "asset": "c", "sha": sha}]
        return rows

    return {"id": "page1", "name": "BPD tracker", "url": "https://apps.apple.com/x?ppid=1", "visible": True,
            "version": {"id": "ver1", "state": state, "deepLink": deep_link, "localizations": {
                loc: {"id": f"loc-{loc}", "promotionalText": promo, "keywords": {k: k for k in keywords},
                      "placements": placements(loc)} for loc in locales}}}


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = make_doc(self.tmp.name, [page(extra_locales={"en-GB": {"same": "en-US", "keywords": ["bpd", "borderline"]}})])
        self.page = cpp.expand(self.doc)[0]

    def ops(self, actions):
        return [a["op"] for a in actions]

    def test_missing_page_creates_then_previews_editable_work(self):
        actions = cpp.plan(self.page, None, self.doc)
        self.assertEqual(actions[0]["op"], "create_page")
        self.assertTrue(actions[0]["template"])
        self.assertEqual(set(actions[0]["locales"]), {"en-US", "en-GB"})
        self.assertIn("add_keywords", self.ops(actions))
        self.assertIn("sync_media", self.ops(actions))

    def test_live_unchanged_page_plans_nothing(self):
        snap = live_snap(self.doc, locales=("en-US", "en-GB"))
        self.assertEqual(cpp.plan(self.page, snap, self.doc), [])

    def test_live_promo_and_keyword_change_is_in_place(self):
        snap = live_snap(self.doc, keywords=("bpd",), promo="Old text", locales=("en-US", "en-GB"))
        actions = cpp.plan(self.page, snap, self.doc)
        self.assertNotIn("create_version", self.ops(actions))
        self.assertTrue(all(a["live"] for a in actions))
        self.assertEqual(sorted(self.ops(actions)), ["add_keywords", "add_keywords", "update_promo", "update_promo"])

    def test_live_media_change_needs_a_new_version(self):
        snap = live_snap(self.doc, media=False, locales=("en-US", "en-GB"))
        actions = cpp.plan(self.page, snap, self.doc)
        self.assertEqual(self.ops(actions), ["create_version"])

    def test_live_new_locale_needs_a_new_version(self):
        snap = live_snap(self.doc, locales=("en-US",))
        self.assertEqual(self.ops(cpp.plan(self.page, snap, self.doc)), ["create_version"])

    def test_in_review_is_skipped(self):
        snap = live_snap(self.doc, state="IN_REVIEW", locales=("en-US", "en-GB"))
        self.assertEqual(self.ops(cpp.plan(self.page, snap, self.doc)), ["skip"])

    def test_editable_version_full_diff(self):
        snap = live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", keywords=("bpd", "symptom"), media=False, locales=("en-US",))
        actions = cpp.plan(self.page, snap, self.doc)
        ops = self.ops(actions)
        self.assertIn("create_localization", ops)
        self.assertIn("remove_keywords", ops)
        self.assertEqual(ops.count("sync_media"), 2)
        self.assertFalse(any(a["live"] for a in actions))

    def test_locales_scope_never_deletes(self):
        snap = live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", locales=("en-US", "en-GB", "en-AU"))
        actions = cpp.plan(self.page, snap, self.doc, locales=["en-GB"], prune=True)
        self.assertNotIn("delete_localization", self.ops(actions))
        self.assertTrue(all(a.get("locale") in (None, "en-GB") for a in actions))

    def test_prune_deletes_but_never_the_last_localization(self):
        snap = live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", locales=("en-US", "en-GB", "en-AU"))
        actions = cpp.plan(self.page, snap, self.doc, prune=True)
        self.assertEqual([a["locale"] for a in actions if a["op"] == "delete_localization"], ["en-AU"])
        lone = cpp.expand(make_doc(tempfile.mkdtemp(), [page()]))[0]
        lone["locales"] = {}
        actions = cpp.plan(lone, live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", locales=("en-AU",)), self.doc, prune=True)
        self.assertNotIn("delete_localization", self.ops(actions))

    def test_creative_ignored_when_unsupported(self):
        snap = live_snap(self.doc, locales=("en-US", "en-GB"))
        for loc in snap["version"]["localizations"].values():
            loc["placements"] = [p for p in loc["placements"] if p["type"] == "APP_SCREENSHOT"]
        self.assertEqual(cpp.plan(self.page, snap, self.doc, creative_supported=False), [])

    def test_ads_rows(self):
        snap = live_snap(self.doc, locales=("en-US", "en-GB"))
        rows = cpp.ads_rows([self.page], {"BPD tracker": snap})
        self.assertEqual({r["locale"] for r in rows}, {"en-US", "en-GB"})
        self.assertEqual(rows[0]["page_id"], "page1")
        self.assertEqual(rows[0]["keywords"], "bpd;borderline")


if __name__ == "__main__":
    unittest.main()
