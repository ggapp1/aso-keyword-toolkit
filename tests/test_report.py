import unittest

from asokit import report


def row(term, opportunity, **extra):
    base = {"term": term, "looksLikeAppName": False, "offCategory": False, "popularity": 10,
            "competitionTier": 3, "medianTop5Ratings": 1200, "exactTitleMatches": 1,
            "ourRank": None, "opportunity": opportunity}
    return {**base, **extra}


class Digest(unittest.TestCase):
    SCORES = {
        "us": [row("mood tracker", 12), row("daylio", 20, looksLikeAppName=True),
               row("bipolar", 18, ourRank=7), row("weather", 30, offCategory=True)],
        "de": [row("stimmung", 9)],
    }

    def test_markets_in_order_with_targetable_counts(self):
        lines = report.digest(self.SCORES)
        headers = [line for line in lines if line.startswith("###")]
        self.assertEqual(headers, ["### de  (1 targetable of 1)", "### us  (2 targetable of 4)"])

    def test_targets_sorted_by_opportunity_without_app_names_or_off_category(self):
        us = "\n".join(report.digest({"us": self.SCORES["us"]}))
        self.assertLess(us.index("bipolar"), us.index("mood tracker"))
        self.assertNotIn("daylio", us)
        self.assertIn("WE RANK: bipolar (#7)", us)
        self.assertIn("OFF-CATEGORY (ignore): weather", us)

    def test_limit_caps_the_terms_per_market(self):
        lines = report.digest({"us": [row(f"term {i}", i) for i in range(30)]}, limit=5)
        self.assertEqual(len([line for line in lines if line.startswith("  term")]), 5)
