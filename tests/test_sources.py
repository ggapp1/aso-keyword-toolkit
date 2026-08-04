import unittest

from asokit import sources


class HtmlUnescaping(unittest.TestCase):
    """Apple returns HTML-escaped titles; escaped entities must not reach a listing."""

    def test_unescapes_ampersand(self):
        self.assertEqual(sources._clean("Ausgaben &amp; Budget"), "Ausgaben & Budget")

    def test_unescapes_quotes_and_apostrophes(self):
        self.assertEqual(sources._clean("Sbalzi d&#39;umore"), "Sbalzi d'umore")

    def test_leaves_plain_text_untouched(self):
        self.assertEqual(sources._clean("Haushaltsbuch"), "Haushaltsbuch")

    def test_passes_through_non_strings(self):
        self.assertIsNone(sources._clean(None))

    def test_cleans_app_titles_without_dropping_other_fields(self):
        cleaned = sources._clean_app({"trackName": "A &amp; B", "userRatingCount": 5})
        self.assertEqual(cleaned["trackName"], "A & B")
        self.assertEqual(cleaned["userRatingCount"], 5)


if __name__ == "__main__":
    unittest.main()
