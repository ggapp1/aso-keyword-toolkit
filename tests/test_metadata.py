import unittest

from asokit import metadata


class CharacterLimits(unittest.TestCase):
    def test_flags_over_limit_field(self):
        problems = metadata.check({"en-US": {"name": "x" * 31, "description": "Real copy."}})
        self.assertEqual(len(problems), 1)
        self.assertIn("31 characters, limit is 30", problems[0])

    def test_accepts_exactly_at_limit(self):
        self.assertEqual(
            metadata.check({"en-US": {"name": "x" * 30, "description": "Real copy."}}), []
        )

    def test_flags_unknown_field(self):
        problems = metadata.check({"en-US": {"tagline": "hi"}})
        self.assertIn("unknown field 'tagline'", problems[0])

    def test_flags_non_string_value(self):
        problems = metadata.check({"en-US": {"name": 42}})
        self.assertIn("expected text", problems[0])


class Duplication(unittest.TestCase):
    """The rule that actually costs money: Apple indexes the three fields as one pool."""

    def test_keyword_repeated_from_title_is_flagged(self):
        problems = metadata.check(
            {"en-US": {"name": "Budget Tracker", "keywords": "budget,expenses"}}
        )
        self.assertTrue(any("'budget' already appears" in p for p in problems))

    def test_keyword_repeated_from_subtitle_is_flagged(self):
        problems = metadata.check(
            {"en-US": {"subtitle": "Track spending and savings", "keywords": "spending,receipts"}}
        )
        self.assertTrue(any("'spending' already appears" in p for p in problems))

    def test_word_shared_between_title_and_subtitle_is_flagged(self):
        problems = metadata.check(
            {"en-US": {"name": "Budget Tracker", "subtitle": "The best tracker"}}
        )
        self.assertTrue(any("'tracker' appears in both" in p for p in problems))

    def test_repeated_keyword_within_field_is_flagged(self):
        problems = metadata.check({"en-US": {"keywords": "budget,receipts,budget"}})
        self.assertTrue(any("listed more than once" in p for p in problems))

    def test_distinct_fields_pass(self):
        problems = metadata.check(
            {
                "de-DE": {
                    "name": "Budgeteer: Expense Tracker",
                    "subtitle": "Haushaltsbuch & Finanzen",
                    "keywords": "budgetplaner,ausgaben,sparen,kostenkontrolle",
                    "description": "Behalte deine Ausgaben im Blick.",
                }
            }
        )
        self.assertEqual(problems, [])

    def test_separator_punctuation_does_not_hide_duplicates(self):
        """'Budget: Tracker' must still count 'tracker' as present."""
        problems = metadata.check({"en-US": {"name": "Budget: Tracker", "keywords": "tracker"}})
        self.assertTrue(any("'tracker' already appears" in p for p in problems))


class KeywordFieldFormatting(unittest.TestCase):
    def test_space_after_comma_is_flagged_as_waste(self):
        problems = metadata.check({"en-US": {"keywords": "budget, receipts"}})
        self.assertTrue(any("spaces around commas" in p for p in problems))

    def test_terms_split_on_commas_not_spaces(self):
        self.assertEqual(
            metadata.keyword_terms("expense tracker,budget"), ["expense tracker", "budget"]
        )


class Usage(unittest.TestCase):
    def test_reports_used_and_limit(self):
        usage = metadata.usage({"en-US": {"name": "Budgeteer"}})
        self.assertEqual(usage["en-US"]["name"], (9, 30))




class Stemming(unittest.TestCase):
    """Apple matches on stems, so 'track' in a title already covers 'tracker'."""

    def test_strips_agent_noun_and_plural(self):
        for word, root in (
            ("tracker", "track"),
            ("trackers", "track"),
            ("moods", "mood"),
            ("users", "user"),
        ):
            self.assertEqual(metadata.stem(word, "en-US"), root)

    def test_leaves_short_and_unsuffixed_words_alone(self):
        for word in ("track", "mood", "meds", "bpd", "anxiety", "episode"):
            self.assertEqual(metadata.stem(word, "en-US"), word)

    def test_keyword_sharing_stem_with_title_is_flagged(self):
        problems = metadata.check(
            {"en-US": {"name": "Budget Tracker", "keywords": "track,receipts"}}
        )
        self.assertTrue(any("shares a stem with 'tracker'" in p for p in problems))

    def test_title_and_subtitle_stem_collision_is_flagged(self):
        """The real-world case: title says 'Tracker', subtitle says 'Track'."""
        problems = metadata.check(
            {"en-US": {"name": "Budget Tracker: Ledger", "subtitle": "Track spending daily"}}
        )
        self.assertTrue(any("share a stem" in p for p in problems))

    def test_distinct_words_are_not_falsely_flagged(self):
        problems = metadata.check(
            {
                "en-US": {
                    "name": "Budget Ledger",
                    "subtitle": "Save more",
                    "keywords": "receipts",
                    "description": "Real copy.",
                }
            }
        )
        self.assertEqual(problems, [])

class SubmissionCompleteness(unittest.TestCase):
    """The failure that only surfaces at submission, long after the push."""

    LOCALIZED = {"name": "X", "subtitle": "Y", "keywords": "a,b"}

    def test_empty_description_is_flagged(self):
        problems = metadata.check({"de-DE": {**self.LOCALIZED, "description": ""}})
        self.assertTrue(any("no description" in p for p in problems))

    def test_absent_description_is_flagged(self):
        problems = metadata.check({"de-DE": dict(self.LOCALIZED)})
        self.assertTrue(any("no description" in p for p in problems))

    def test_whitespace_only_description_is_flagged(self):
        problems = metadata.check({"de-DE": {**self.LOCALIZED, "description": "   \n"}})
        self.assertTrue(any("no description" in p for p in problems))

    def test_message_is_about_submission_not_style(self):
        problems = metadata.check({"de-DE": dict(self.LOCALIZED)})
        message = next(p for p in problems if "no description" in p)
        self.assertIn("blocks submission", message)
        self.assertIn("rather than falling back to your primary locale", message)

    def test_description_present_passes(self):
        problems = metadata.check(
            {"de-DE": {**self.LOCALIZED, "description": "Echte Beschreibung."}}
        )
        self.assertEqual(problems, [])

    def test_locale_touching_no_localized_field_is_not_flagged(self):
        """A URL-only update is not a localization being filled in."""
        problems = metadata.check({"de-DE": {"supportUrl": "https://example.com"}})
        self.assertEqual(problems, [])

    def test_allow_partial_drops_the_rule(self):
        problems = metadata.check({"de-DE": dict(self.LOCALIZED)}, allow_partial=True)
        self.assertEqual(problems, [])

    def test_strict_also_wants_release_notes(self):
        fields = {**self.LOCALIZED, "description": "Echte Beschreibung."}
        self.assertEqual(metadata.check({"de-DE": fields}), [])
        problems = metadata.check({"de-DE": fields}, strict=True)
        self.assertTrue(any("no whatsNew" in p for p in problems))

    def test_strict_satisfied_by_release_notes(self):
        problems = metadata.check(
            {"de-DE": {**self.LOCALIZED, "description": "Text.", "whatsNew": "Fixes."}},
            strict=True,
        )
        self.assertEqual(problems, [])


class LocaleAwareStemming(unittest.TestCase):
    """English suffixes applied to every language invent collisions and miss real ones."""

    def test_german_nouns_survive_the_english_er_rule(self):
        for word in ("zucker", "wasser", "fieber", "kinder", "bilder", "tagebücher"):
            self.assertEqual(metadata.stem(word, "de-DE"), word)

    def test_romance_plurals_use_romance_rules(self):
        # The English `s` rule left `deposiciones` as `deposicione`, which meets
        # nothing. The Spanish `es` rule reaches the actual singular.
        self.assertEqual(metadata.stem("deposiciones", "es-ES"), "deposicion")
        self.assertEqual(metadata.stem("dejeções", "pt-BR"), "dejeção")
        # `heces`/`fezes` are irregular z-to-c plurals, and the four-character
        # remainder guard blocks the `es` rule on words this short anyway. Both
        # fall back to stripping the regular `s`, which reaches no singular —
        # a missed collision, which is the safe direction to fail in.
        self.assertEqual(metadata.stem("heces", "es-ES"), "hece")
        self.assertEqual(metadata.stem("fezes", "pt-BR"), "feze")

    def test_portuguese_ao_plural_meets_its_singular(self):
        self.assertEqual(metadata.stem("dejeções", "pt-BR"), metadata.stem("dejeção", "pt-BR"))

    def test_unknown_locale_falls_back_to_exact_matching(self):
        for word in ("κιλά", "παιδιά", "zucker"):
            self.assertEqual(metadata.stem(word, "el"), word)

    def test_no_locale_does_not_apply_english_rules(self):
        self.assertEqual(metadata.stem("zucker"), "zucker")

    def test_language_subtag_selects_the_rules(self):
        self.assertEqual(metadata.stem("trackers", "en-GB"), "track")
        self.assertEqual(metadata.stem("trackers", "en"), "track")

    def test_no_spurious_collision_in_german_check(self):
        """`Zucker` and `Zuck` are unrelated; the English stemmer merged them."""
        problems = metadata.check(
            {
                "de-DE": {
                    "name": "Zucker Tagebuch",
                    "keywords": "zuck,blutzucker",
                    "description": "Echte Beschreibung.",
                }
            }
        )
        self.assertFalse(any("shares a stem" in p for p in problems))

    def test_english_stem_collision_still_caught(self):
        problems = metadata.check(
            {
                "en-US": {
                    "name": "Budget Tracker",
                    "keywords": "track,receipts",
                    "description": "Real copy.",
                }
            }
        )
        self.assertTrue(any("shares a stem with 'tracker'" in p for p in problems))

    def test_unstemmed_locales_are_reportable(self):
        listed = metadata.unstemmed_locales({"de-DE": {}, "en-US": {}, "el": {}, "ja": {}})
        self.assertEqual(listed, ["de-DE", "el"])


if __name__ == "__main__":
    unittest.main()
