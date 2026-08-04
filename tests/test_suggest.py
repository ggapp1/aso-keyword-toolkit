import unittest

from asokit import suggest


class Tokenizing(unittest.TestCase):
    def test_splits_on_punctuation_and_lowercases(self):
        self.assertEqual(
            suggest._tokens("Budget Expense Tracker: Budgeteer"),
            ["budget", "expense", "tracker", "budgeteer"],
        )

    def test_keeps_non_latin_scripts(self):
        self.assertEqual(suggest._tokens("家計簿 budget"), ["家計簿", "budget"])

    def test_drops_digits_and_symbols(self):
        self.assertEqual(suggest._tokens("Budget 2.0 & Co"), ["budget", "co"])

    def test_handles_empty_input(self):
        self.assertEqual(suggest._tokens(None), [])


class Filtering(unittest.TestCase):
    def test_removes_stopwords_and_short_words(self):
        self.assertEqual(
            suggest._meaningful(["the", "best", "budget", "to", "ai"]), ["budget"]
        )

    def test_removes_non_english_stopwords(self):
        self.assertEqual(suggest._meaningful(["der", "haushaltsbuch", "und"]), ["haushaltsbuch"])

    def test_builds_adjacent_phrases(self):
        self.assertEqual(
            suggest._phrases(["expense", "tracker", "budget"]),
            ["expense tracker", "tracker budget"],
        )


class FromApp(unittest.TestCase):
    def setUp(self):
        self._lookup = suggest.sources.lookup
        self._search = suggest.sources.search

    def tearDown(self):
        suggest.sources.lookup = self._lookup
        suggest.sources.search = self._search

    def test_raises_when_app_is_not_in_that_store(self):
        suggest.sources.lookup = lambda app_id, country, cache=None: None
        with self.assertRaises(LookupError) as caught:
            suggest.from_app(1, "de")
        self.assertIn("not available in the de store", str(caught.exception))

    def test_derives_seeds_from_repeated_competitor_terms(self):
        suggest.sources.lookup = lambda app_id, country, cache=None: {
            "trackName": "Budget Expense Tracker",
            "primaryGenreName": "Finance",
        }
        competitors = [
            {"trackId": 2, "trackName": "Expense Tracker Daily"},
            {"trackId": 3, "trackName": "Expense Tracker Wallet"},
            {"trackId": 4, "trackName": "Budget Planner"},
        ]
        suggest.sources.search = lambda term, country, cache=None, limit=25: competitors

        seeds, context = suggest.from_app(1, "us")

        self.assertIn("expense tracker", seeds)
        self.assertEqual(context["app"], "Budget Expense Tracker")
        self.assertGreater(context["competitorsRead"], 0)

    def test_excludes_our_own_app_from_competitor_mining(self):
        suggest.sources.lookup = lambda app_id, country, cache=None: {
            "trackName": "Unique Brandname",
            "primaryGenreName": "Finance",
        }
        suggest.sources.search = lambda term, country, cache=None, limit=25: [
            {"trackId": 1, "trackName": "Unique Brandname"}
        ]
        _, context = suggest.from_app(1, "us")
        self.assertEqual(context["competitorsRead"], 0)

    def test_does_not_probe_genre_when_title_yields_probes(self):
        """A category name is not a search term — probing 'Finance' returns banks."""
        suggest.sources.lookup = lambda app_id, country, cache=None: {
            "trackName": "Budget Expense Tracker",
            "primaryGenreName": "Finance",
        }
        probed = []

        def record(term, country, cache=None, limit=25):
            probed.append(term)
            return []

        suggest.sources.search = record
        suggest.from_app(1, "us")
        self.assertNotIn("finance", probed)


if __name__ == "__main__":
    unittest.main()
