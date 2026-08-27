import unittest

from asokit import packing


def candidate(term, opportunity=5, **overrides):
    item = {
        "term": term,
        "opportunity": opportunity,
        "competitionTier": 2,
        "offCategory": False,
        "looksLikeAppName": False,
        "topApps": [],
    }
    item.update(overrides)
    return item


class Tokenizer(unittest.TestCase):
    """Python's \\w excludes nonspacing marks, which shreds several scripts."""

    def test_thai_stays_one_token(self):
        self.assertEqual(packing.words("บันทึกการขับถ่าย"), ["บันทึกการขับถ่าย"])

    def test_devanagari_keeps_matras_attached(self):
        self.assertEqual(packing.words("मल त्याग डायरी"), ["मल", "त्याग", "डायरी"])

    def test_splits_on_punctuation_and_dashes(self):
        self.assertEqual(
            packing.words("Poop Tracker - Balloon, Inc."),
            ["poop", "tracker", "balloon", "inc"],
        )

    def test_digits_survive(self):
        self.assertEqual(packing.words("bristol 7"), ["bristol", "7"])

    def test_normalize_collapses_to_a_comparable_name(self):
        self.assertEqual(packing.normalize("Poop Tracker - Balloon"), "poop tracker balloon")


class Stopwords(unittest.TestCase):
    def test_english_filler_is_dropped(self):
        chosen = packing.packed_words(
            [candidate("with and free budget")], "", "", locale="en-US"
        )
        self.assertEqual(chosen, ["budget"])

    def test_corporate_suffixes_are_dropped_in_every_locale(self):
        chosen = packing.packed_words([candidate("zucker uab gmbh")], "", "", locale="de-DE")
        self.assertEqual(chosen, ["zucker"])

    def test_locale_filler_is_added_to_the_english_set(self):
        chosen = packing.packed_words(
            [candidate("der blutzucker und das tagebuch")], "", "", locale="de-DE"
        )
        self.assertEqual(chosen, ["blutzucker", "tagebuch"])

    def test_short_latin_words_are_dropped(self):
        chosen = packing.packed_words([candidate("ab budget")], "", "", locale="en-US")
        self.assertEqual(chosen, ["budget"])

    def test_cjk_terms_survive_the_minimum_length(self):
        """A blanket minimum guts locales whose terms are legitimately short."""
        chosen = packing.packed_words([candidate("腸活")], "", "", locale="ja")
        self.assertEqual(chosen, ["腸活"])

    def test_digits_survive_the_minimum_length(self):
        chosen = packing.packed_words([candidate("bristol 7")], "", "", locale="en-US")
        self.assertEqual(chosen, ["bristol", "7"])


class BrandFragments(unittest.TestCase):
    """looksLikeAppName filters whole terms; splitting into words leaks the pieces."""

    def test_fragment_of_a_rival_app_name_is_dropped(self):
        candidates = [
            candidate("poop tracker balloon", looksLikeAppName=True),
            candidate("poop tracker"),
            candidate("stool log"),
        ]
        chosen = packing.packed_words(candidates, "", "", locale="en-US")
        self.assertNotIn("balloon", chosen)
        self.assertIn("poop", chosen)
        self.assertIn("tracker", chosen)

    def test_brand_word_from_top_apps_is_dropped(self):
        """A word seen only inside app names never entered a genuine query."""
        candidates = [
            candidate("gut health", topApps=[{"name": "Balloon Gut Coach"}]),
            candidate("stool log"),
        ]
        chosen = packing.packed_words(candidates, "", "", locale="en-US")
        self.assertNotIn("balloon", chosen)
        self.assertIn("gut", chosen)

    def test_brand_word_that_also_arrives_via_genuine_queries_survives(self):
        """The documented limit of the heuristic, and the reason `blocked` exists.

        `balloon gut health` is a real query, so it vouches for the word and no
        rule sharp enough to catch it here would spare `gut` or `health`.
        """
        candidates = [
            candidate("gut health", topApps=[{"name": "Balloon Gut Coach"}]),
            candidate("balloon gut health"),
        ]
        self.assertIn("balloon", packing.packed_words(candidates, "", "", locale="en-US"))
        self.assertNotIn(
            "balloon",
            packing.packed_words(candidates, "", "", blocked={"balloon"}, locale="en-US"),
        )

    def test_a_word_used_in_genuine_queries_is_kept(self):
        candidates = [
            candidate("poop tracker pro", looksLikeAppName=True),
            candidate("poop diary"),
        ]
        self.assertIn("poop", packing.packed_words(candidates, "", "", locale="en-US"))

    def test_long_app_name_does_not_swallow_a_short_generic_term(self):
        """`Poop Tracker Pro` must not disqualify `poop tracker`."""
        names = {"poop tracker pro"}
        self.assertFalse(packing.names_an_app("poop tracker", names))

    def test_multi_word_app_name_inside_a_term_is_recognized(self):
        names = {"poop tracker pro"}
        self.assertTrue(packing.names_an_app("best poop tracker pro app", names))

    def test_single_word_app_name_does_not_disqualify_every_term_using_it(self):
        names = {"balloon"}
        self.assertFalse(packing.names_an_app("balloon gut health", names))


class Budget(unittest.TestCase):
    def test_output_fits_the_limit(self):
        candidates = [candidate(f"keyword{n} extra{n}", opportunity=50 - n) for n in range(40)]
        field = packing.select_keywords(candidates, "", "", limit=100, locale="en-US")
        self.assertLessEqual(len(field), 100)

    def test_field_is_comma_separated_without_spaces(self):
        field = packing.select_keywords(
            [candidate("budget tracker")], "", "", locale="en-US"
        )
        self.assertEqual(field, "budget,tracker")

    def test_higher_opportunity_wins_the_early_slots(self):
        candidates = [candidate("second", opportunity=1), candidate("first", opportunity=9)]
        self.assertEqual(
            packing.packed_words(candidates, "", "", locale="en-US"), ["first", "second"]
        )

    def test_words_covered_by_name_or_subtitle_are_dropped(self):
        chosen = packing.packed_words(
            [candidate("budget tracker savings")], "Budget Tracker", "", locale="en-US"
        )
        self.assertEqual(chosen, ["savings"])

    def test_stem_coverage_uses_the_locale(self):
        """`Tracker` in the name covers `track` in English."""
        chosen = packing.packed_words(
            [candidate("track savings")], "Budget Tracker", "", locale="en-US"
        )
        self.assertEqual(chosen, ["savings"])

    def test_german_words_are_not_dropped_by_english_morphology(self):
        """The stemmer bug reached here too: `zucker` must not stem to `zuck`."""
        chosen = packing.packed_words(
            [candidate("zucker")], "Zuck Tagebuch", "", locale="de-DE"
        )
        self.assertEqual(chosen, ["zucker"])

    def test_off_category_and_app_name_candidates_are_excluded(self):
        candidates = [
            candidate("moodle", offCategory=True),
            candidate("rival app", looksLikeAppName=True),
            candidate("budget"),
        ]
        self.assertEqual(
            packing.packed_words(candidates, "", "", locale="en-US"), ["budget"]
        )

    def test_a_word_is_never_repeated(self):
        candidates = [candidate("stool tracker"), candidate("poop tracker")]
        chosen = packing.packed_words(candidates, "", "", locale="en-US")
        self.assertEqual(chosen.count("tracker"), 1)

    def test_blocked_words_are_dropped(self):
        chosen = packing.packed_words(
            [candidate("balloon budget")], "", "", blocked={"balloon"}, locale="en-US"
        )
        self.assertEqual(chosen, ["budget"])

    def test_blocked_applies_to_non_latin_scripts_too(self):
        chosen = packing.packed_words(
            [candidate("サントリー 腸活")], "", "", blocked={"サントリー"}, locale="ja"
        )
        self.assertEqual(chosen, ["腸活"])


class IncumbentTerms(unittest.TestCase):
    """Research-only selection silently discarded terms that were already ranking."""

    def test_live_keywords_become_candidates(self):
        incumbents = packing.incumbent_candidates("fodmap,bloating")
        self.assertEqual([item["term"] for item in incumbents], ["fodmap", "bloating"])
        self.assertTrue(all(item["opportunity"] == 0 for item in incumbents))

    def test_incumbents_are_kept_but_fill_the_later_slots(self):
        candidates = [candidate("researched", opportunity=9)]
        candidates += packing.incumbent_candidates("fodmap")
        self.assertEqual(
            packing.packed_words(candidates, "", "", locale="en-US"), ["researched", "fodmap"]
        )

    def test_incumbent_already_covered_by_the_name_is_still_dropped(self):
        candidates = packing.incumbent_candidates("budget")
        self.assertEqual(packing.packed_words(candidates, "Budget", "", locale="en-US"), [])

    def test_blank_keyword_field_yields_nothing(self):
        self.assertEqual(packing.incumbent_candidates(""), [])
        self.assertEqual(packing.incumbent_candidates(None), [])


if __name__ == "__main__":
    unittest.main()
