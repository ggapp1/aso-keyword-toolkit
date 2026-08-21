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

    def test_flat_format_still_allows_an_empty_locale_map(self):
        self.assertEqual(products.check({"com.example.pro": {}}), [])


class RequiredProvisioningFields(unittest.TestCase):
    def test_requires_subscription_localizations(self):
        data = declarative()
        del data["groups"][0]["subscriptions"][0]["localizations"]
        self.assertIn(
            "com.example.pro.annual.localizations: at least one locale is "
            "required — App Store Connect rejects a subscription created "
            "without one",
            products.check(data),
        )

    def test_flags_empty_subscription_localizations(self):
        self.assertIn(
            "com.example.pro.annual.localizations: at least one locale is "
            "required — App Store Connect rejects a subscription created "
            "without one",
            products.check(declarative(localizations={})),
        )

    def test_requires_group_localizations(self):
        data = declarative()
        del data["groups"][0]["localizations"]
        self.assertIn(
            "group:Pro.localizations: at least one locale is required — App "
            "Store Connect rejects a subscription group created without one",
            products.check(data),
        )

    def test_requires_price(self):
        data = declarative()
        del data["groups"][0]["subscriptions"][0]["price"]
        self.assertIn(
            "com.example.pro.annual.price: required — App Store Connect "
            "cannot create a subscription without a price",
            products.check(data),
        )

    def test_flags_malformed_availability(self):
        self.assertIn(
            "com.example.pro.annual.availability: expected an object",
            products.check(declarative(availability="worldwide")),
        )
        self.assertIn(
            "com.example.pro.annual.availability.allTerritories: expected "
            "true or false, got 'yes'",
            products.check(declarative(availability={"allTerritories": "yes"})),
        )

    def test_availability_stays_optional(self):
        data = declarative()
        del data["groups"][0]["subscriptions"][0]["availability"]
        self.assertEqual(products.check(data), [])

    def test_sample_file_is_clean_under_the_stricter_rules(self):
        self.assertEqual(products.check(declarative()), [])


EMPTY_INVENTORY = {"subscriptionGroups": [], "inAppPurchases": []}


def provisioned_inventory():
    """Inventory that exactly satisfies `declarative()`."""
    return {
        "subscriptionGroups": [
            {
                "id": "g1",
                "referenceName": "Pro",
                "localizations": {"en-US": {"id": "gl1", "name": "Pro", "customAppName": None}},
                "subscriptions": [
                    {
                        "id": "s1",
                        "productId": "com.example.pro.annual",
                        "state": "READY_TO_SUBMIT",
                        "attributes": {
                            "name": "Pro Annual",
                            "subscriptionPeriod": "ONE_YEAR",
                            "groupLevel": 1,
                            "familySharable": False,
                            "reviewNote": None,
                        },
                        "localizations": {
                            "en-US": {
                                "id": "sl1",
                                "name": "Pro Annual",
                                "description": "All year.",
                            }
                        },
                        "prices": {"USA": "pp1"},
                        "availability": {"allTerritories": True},
                    }
                ],
            }
        ],
        "inAppPurchases": [],
    }


def kinds(actions):
    return [action["kind"] for action in actions]


class PlanFromEmpty(unittest.TestCase):
    def test_creates_group_then_subscription(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        self.assertEqual(kinds(actions)[0], "createGroup")
        self.assertIn("createSubscription", kinds(actions))
        self.assertLess(
            kinds(actions).index("createGroup"),
            kinds(actions).index("createSubscription"),
        )

    def test_creates_localizations_and_price_and_availability(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        self.assertIn("createLocalization", kinds(actions))
        self.assertIn("setPrices", kinds(actions))
        self.assertIn("setAvailability", kinds(actions))

    def test_subscription_carries_creatable_attributes(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        create = next(a for a in actions if a["kind"] == "createSubscription")
        self.assertEqual(create["group"], "Pro")
        self.assertEqual(create["productId"], "com.example.pro.annual")
        self.assertEqual(create["attributes"]["subscriptionPeriod"], "ONE_YEAR")
        self.assertEqual(create["attributes"]["groupLevel"], 1)

    def test_prices_precede_nothing_but_follow_creation(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        self.assertLess(
            kinds(actions).index("createSubscription"),
            kinds(actions).index("setPrices"),
        )


class PlanIdempotence(unittest.TestCase):
    def test_fully_provisioned_inventory_writes_nothing(self):
        actions = products.plan(declarative(), provisioned_inventory())
        self.assertEqual(
            [a for a in actions if a["kind"] not in ("skip", "setPrices")],
            [],
            "a re-run against unchanged state must write nothing structural",
        )

    def test_existing_group_is_not_recreated(self):
        inventory = provisioned_inventory()
        inventory["subscriptionGroups"][0]["subscriptions"] = []
        actions = products.plan(declarative(), inventory)
        self.assertNotIn("createGroup", kinds(actions))
        self.assertIn("createSubscription", kinds(actions))


class PlanDrift(unittest.TestCase):
    def test_mutable_drift_emits_patch(self):
        inventory = provisioned_inventory()
        inventory["subscriptionGroups"][0]["subscriptions"][0]["attributes"]["groupLevel"] = 2
        actions = products.plan(declarative(), inventory)
        patch = next(a for a in actions if a["kind"] == "patchSubscription")
        self.assertEqual(patch["attributes"], {"groupLevel": 1})

    def test_immutable_drift_raises_before_any_write(self):
        inventory = provisioned_inventory()
        subscription = inventory["subscriptionGroups"][0]["subscriptions"][0]
        subscription["attributes"]["subscriptionPeriod"] = "ONE_MONTH"
        with self.assertRaises(products.PlanError) as caught:
            products.plan(declarative(), inventory)
        self.assertIn("subscriptionPeriod", str(caught.exception))

    def test_subscription_in_another_group_raises_before_any_write(self):
        inventory = provisioned_inventory()
        inventory["subscriptionGroups"][0]["referenceName"] = "Legacy"
        with self.assertRaises(products.PlanError) as caught:
            products.plan(declarative(), inventory)
        message = str(caught.exception)
        self.assertIn("com.example.pro.annual", message)
        self.assertIn("Legacy", message)
        self.assertIn("Pro", message)
        self.assertIn("does not move subscriptions between groups", message)

    def test_changed_localization_text_updates_rather_than_creates(self):
        inventory = provisioned_inventory()
        localization = inventory["subscriptionGroups"][0]["subscriptions"][0]["localizations"]
        localization["en-US"]["description"] = "Something else."
        actions = products.plan(declarative(), inventory)
        update = next(a for a in actions if a["kind"] == "updateLocalization")
        self.assertEqual(update["id"], "sl1")
        self.assertEqual(update["fields"]["description"], "All year.")



if __name__ == "__main__":
    unittest.main()
