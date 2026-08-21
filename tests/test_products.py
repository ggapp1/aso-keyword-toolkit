import unittest

from asokit import products


def entry(**fields):
    return {"com.example.pro": {"en-US": fields}}


class CharacterLimits(unittest.TestCase):
    def test_flags_name_over_limit(self):
        problems = products.check(entry(name="x" * 31))
        self.assertEqual(len(problems), 1)
        self.assertIn("31 characters, limit is 30", problems[0])

    def test_flags_description_over_limit(self):
        problems = products.check(entry(name="ok", description="x" * 46))
        self.assertTrue(any("46 characters, limit is 45" in p for p in problems))

    def test_accepts_exactly_at_limit(self):
        self.assertEqual(
            products.check(entry(name="x" * 30, description="y" * 45)), []
        )


class Structure(unittest.TestCase):
    def test_flags_unknown_field(self):
        problems = products.check(entry(name="ok", tagline="hi"))
        self.assertTrue(any("unknown field 'tagline'" in p for p in problems))

    def test_flags_non_string_value(self):
        problems = products.check(entry(name=42))
        self.assertTrue(any("expected text" in p for p in problems))

    def test_missing_name_is_flagged(self):
        problems = products.check(entry(description="no name"))
        self.assertTrue(any("'name' is required" in p for p in problems))

    def test_group_allows_custom_app_name_but_not_description(self):
        data = {"group:Pro": {"pt-BR": {"name": "Pro", "customAppName": "App"}}}
        self.assertEqual(products.check(data), [])
        data = {"group:Pro": {"pt-BR": {"name": "Pro", "description": "x"}}}
        problems = products.check(data)
        self.assertTrue(any("unknown field 'description'" in p for p in problems))


class Usage(unittest.TestCase):
    def test_reports_used_and_limit(self):
        report = products.usage(entry(name="Pro Lifetime"))
        self.assertEqual(report["com.example.pro"]["en-US"]["name"], (12, 30))


def declarative(**overrides):
    subscription = {
        "productId": "com.example.pro.annual",
        "name": "Pro Annual",
        "subscriptionPeriod": "ONE_YEAR",
        "groupLevel": 1,
        "familySharable": False,
        "price": {"baseTerritory": "USA", "customerPrice": "24.99"},
        "availability": {"allTerritories": True},
        "localizations": {"en-US": {"name": "Pro Annual", "description": "All year."}},
    }
    subscription.update(overrides)
    return {
        "groups": [
            {
                "referenceName": "Pro",
                "localizations": {"en-US": {"name": "Pro"}},
                "subscriptions": [subscription],
            }
        ]
    }


class DeclarativeFormat(unittest.TestCase):
    def test_detects_declarative_shape(self):
        self.assertTrue(products.is_declarative(declarative()))
        self.assertFalse(products.is_declarative({"com.example.pro": {}}))

    def test_valid_file_has_no_problems(self):
        self.assertEqual(products.check(declarative()), [])

    def test_flags_unknown_period(self):
        problems = products.check(declarative(subscriptionPeriod="FORTNIGHTLY"))
        self.assertTrue(any("subscriptionPeriod" in p for p in problems))

    def test_flags_missing_product_id(self):
        data = declarative()
        del data["groups"][0]["subscriptions"][0]["productId"]
        problems = products.check(data)
        self.assertTrue(any("productId" in p for p in problems))

    def test_flags_non_integer_group_level(self):
        problems = products.check(declarative(groupLevel="1"))
        self.assertTrue(any("groupLevel" in p for p in problems))

    def test_flags_non_decimal_price(self):
        problems = products.check(
            declarative(price={"baseTerritory": "USA", "customerPrice": "free"})
        )
        self.assertTrue(any("customerPrice" in p for p in problems))

    def test_enforces_description_limit_in_declarative_form(self):
        problems = products.check(
            declarative(
                localizations={"en-US": {"name": "Pro", "description": "x" * 46}}
            )
        )
        self.assertTrue(any("46 characters, limit is 45" in p for p in problems))

    def test_flat_format_still_validates(self):
        self.assertEqual(products.check(entry(name="Pro", description="ok")), [])


if __name__ == "__main__":
    unittest.main()
