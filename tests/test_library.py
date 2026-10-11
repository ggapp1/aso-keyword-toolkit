# tests/test_library.py
import unittest

from asokit import library
from tests.fakes import REFDATA, FakeConnect, install


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


if __name__ == "__main__":
    unittest.main()
