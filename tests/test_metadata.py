import unittest

from asokit import metadata


class CharacterLimits(unittest.TestCase):
    def test_flags_over_limit_field(self):
        problems = metadata.check({"en-US": {"name": "x" * 31}})
        self.assertEqual(len(problems), 1)
        self.assertIn("31 characters, limit is 30", problems[0])

    def test_accepts_exactly_at_limit(self):
        self.assertEqual(metadata.check({"en-US": {"name": "x" * 30}}), [])

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
        self.assertEqual(metadata.stem("tracker"), "track")
        self.assertEqual(metadata.stem("trackers"), "track")
        self.assertEqual(metadata.stem("moods"), "mood")
        self.assertEqual(metadata.stem("users"), "user")

    def test_leaves_short_and_unsuffixed_words_alone(self):
        for word in ("track", "mood", "meds", "bpd", "anxiety", "episode"):
            self.assertEqual(metadata.stem(word), word)

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
            {"en-US": {"name": "Budget Ledger", "subtitle": "Save more", "keywords": "receipts"}}
        )
        self.assertEqual(problems, [])

if __name__ == "__main__":
    unittest.main()
