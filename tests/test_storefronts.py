import unittest

from asokit import storefronts


class Header(unittest.TestCase):
    def test_builds_expected_format(self):
        self.assertEqual(storefronts.header("de"), "143443-4,29")

    def test_country_code_is_case_insensitive(self):
        self.assertEqual(storefronts.header("DE"), storefronts.header("de"))

    def test_unknown_country_raises_with_guidance(self):
        with self.assertRaises(storefronts.UnknownStorefront) as caught:
            storefronts.header("zz")
        self.assertIn("unknown country 'zz'", str(caught.exception))


class Table(unittest.TestCase):
    def test_storefront_ids_are_unique_per_country(self):
        identifiers = [entry[0] for entry in storefronts.STOREFRONTS.values()]
        duplicates = {i for i in identifiers if identifiers.count(i) > 1}
        self.assertEqual(duplicates, set(), f"duplicate storefront ids: {duplicates}")

    def test_every_entry_is_well_formed(self):
        for code, entry in storefronts.STOREFRONTS.items():
            self.assertEqual(len(code), 2, f"{code} is not a two-letter code")
            identifier, label, locale = entry
            self.assertIsInstance(identifier, int)
            self.assertTrue(143_000 < identifier < 144_000, f"{code}: {identifier} out of range")
            self.assertTrue(label and locale)

    def test_known_ids_are_correct(self):
        """Spot-checks verified live against the autocomplete endpoint."""
        for code, expected in (("us", 143441), ("de", 143443), ("jp", 143462), ("br", 143503)):
            self.assertEqual(storefronts.STOREFRONTS[code][0], expected)

    def test_default_locale_available_for_every_storefront(self):
        for code in storefronts.STOREFRONTS:
            self.assertTrue(storefronts.default_locale(code))


if __name__ == "__main__":
    unittest.main()
