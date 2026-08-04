import unittest

from asokit import research


def app(name, ratings=0, app_id=1):
    return {"trackName": name, "userRatingCount": ratings, "trackId": app_id}


class CompetitionTier(unittest.TestCase):
    def test_empty_field_is_tier_one(self):
        self.assertEqual(research.competition_tier(0), 1)

    def test_boundaries(self):
        self.assertEqual(research.competition_tier(99), 1)
        self.assertEqual(research.competition_tier(100), 2)
        self.assertEqual(research.competition_tier(999), 2)
        self.assertEqual(research.competition_tier(1_000), 3)
        self.assertEqual(research.competition_tier(10_000), 4)
        self.assertEqual(research.competition_tier(100_000), 5)


class BrandDetection(unittest.TestCase):
    """Autocomplete mixes competitor app names in with real queries."""

    def test_colon_marks_an_app_name(self):
        self.assertTrue(
            research.is_app_name("moneywiz: personal finance", [], 1, set())
        )

    def test_em_dash_marks_an_app_name(self):
        self.assertTrue(research.is_app_name("spendee — budget tracker", [], 1, set()))

    def test_dotted_name_marks_an_app_name(self):
        self.assertTrue(research.is_app_name("money.io", [], 1, set()))

    def test_cjk_interpunct_marks_an_app_name(self):
        """Japanese listings join name and tagline with '・', not ':'."""
        self.assertTrue(
            research.is_app_name("家計簿・節約 マネーフォワード", [], 0, set())
        )

    def test_full_width_colon_marks_an_app_name(self):
        self.assertTrue(research.is_app_name("家計簿：無料", [], 0, set()))

    def test_plain_cjk_keyword_is_not_an_app_name(self):
        self.assertFalse(research.is_app_name("家計簿", [], 0, set()))

    def test_top_result_titled_exactly_the_term_is_a_brand_query(self):
        top = [app("Mint Mobile - Wireless Plan", 4200)]
        self.assertTrue(research.is_app_name("mint mobile", top, 1, set()))

    def test_exact_seed_is_never_a_brand_query(self):
        """An app named 'Budget Tracker' must not disqualify the generic term."""
        top = [app("Budget Tracker", 0)]
        self.assertFalse(
            research.is_app_name("budget tracker", top, 1, {"budget tracker"})
        )

    def test_multiple_apps_competing_means_generic(self):
        top = [app("Expense Tracker Pro", 3)]
        self.assertFalse(research.is_app_name("expense tracker", top, 2, set()))

    def test_unrelated_top_result_is_not_a_brand_query(self):
        top = [app("Monee Ausgaben & Budget", 9717)]
        self.assertFalse(research.is_app_name("haushaltsbuch", top, 0, set()))


class Scoring(unittest.TestCase):
    def setUp(self):
        self._original = research.sources.search
        self.results = [app("Some App", 500, app_id=99)]
        research.sources.search = lambda term, country, cache=None: self.results

    def tearDown(self):
        research.sources.search = self._original

    def test_better_autocomplete_rank_scores_higher(self):
        first = research.score("a", [["seed", 1]], "us")
        third = research.score("b", [["seed", 3]], "us")
        self.assertEqual(first["popularity"], 10)
        self.assertEqual(third["popularity"], 8)

    def test_breadth_bonus_caps_at_three(self):
        many = [[f"seed{i}", 5] for i in range(10)]
        scored = research.score("a", many, "us")
        self.assertEqual(scored["popularity"], 6 + 3)

    def test_term_absent_from_autocomplete_scores_zero_popularity(self):
        self.assertEqual(research.score("a", [], "us")["popularity"], 0)

    def test_finds_our_rank_in_results(self):
        self.results = [app("Other", 10, 1), app("Ours", 5, 42)]
        self.assertEqual(research.score("a", [], "us", app_id=42)["ourRank"], 2)

    def test_our_rank_is_none_when_absent(self):
        self.assertIsNone(research.score("a", [], "us", app_id=12345)["ourRank"])

    def test_lower_competition_raises_opportunity(self):
        self.results = [app("Tiny", 5, 1)]
        easy = research.score("a", [["seed", 1]], "us")
        self.results = [app("Giant", 500_000, 1)]
        hard = research.score("a", [["seed", 1]], "us")
        self.assertGreater(easy["opportunity"], hard["opportunity"])

    def test_counts_exact_title_matches(self):
        self.results = [app("Expense Tracker", 1, 1), app("Best Expense Tracker", 1, 2), app("X", 1, 3)]
        self.assertEqual(research.score("expense tracker", [], "us")["exactTitleMatches"], 2)

    def test_rank_candidates_respects_limit_and_keeps_seeds(self):
        evidence = {
            "alpha": [["alpha", 1]],
            "beta": [["alpha", 2]],
            "gamma": [["alpha", 3]],
            "orphan seed": [],
        }
        chosen = research.rank_candidates(evidence, limit=2, seeds_lower={"orphan seed"})
        self.assertEqual(chosen[:2], ["alpha", "beta"])
        self.assertIn("orphan seed", chosen)
        self.assertNotIn("gamma", chosen)

    def test_rank_candidates_does_not_duplicate_a_seed_already_chosen(self):
        evidence = {"alpha": [["alpha", 1]], "beta": [["alpha", 2]]}
        chosen = research.rank_candidates(evidence, limit=2, seeds_lower={"alpha"})
        self.assertEqual(chosen.count("alpha"), 1)


class Expansion(unittest.TestCase):
    def test_records_every_seed_that_surfaced_a_term(self):
        calls = {"budget": ["budget app", "budget planner"], "expenses": ["budget app"]}
        original = research.sources.autocomplete
        research.sources.autocomplete = lambda term, country, cache=None: calls[term]
        try:
            evidence = research.expand(["budget", "expenses"], "us")
        finally:
            research.sources.autocomplete = original

        self.assertEqual(evidence["budget app"], [["budget", 1], ["expenses", 1]])
        self.assertEqual(evidence["budget planner"], [["budget", 2]])
        self.assertIn("expenses", evidence)  # seeds always present, even if unsuggested


if __name__ == "__main__":
    unittest.main()
