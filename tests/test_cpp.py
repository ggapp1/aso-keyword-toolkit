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


if __name__ == "__main__":
    unittest.main()
