"""App Store Connect writes, against a stubbed transport.

These exercise the failure the field report in #1 hit: a multi-locale push
where App Store Connect auto-creates the paired appStoreVersionLocalization,
so a planned create collides with a resource that now exists.
"""

import unittest

from asokit import asc


class FakeConnect:
    """A minimal App Store Connect that records every write.

    `auto_pairs` reproduces the real behaviour: creating an appInfoLocalization
    makes App Store Connect create the matching appStoreVersionLocalization as
    a side effect, which is what turned the follow-up create into a 409.
    """

    def __init__(self, info_locales=(), version_locales=(), auto_pairs=False, fail_on=None):
        self.info = {locale: f"i-{locale}" for locale in info_locales}
        self.version = {locale: f"v-{locale}" for locale in version_locales}
        self.auto_pairs = auto_pairs
        self.fail_on = fail_on or set()
        self.writes = []

    def call(self, method, path, bearer, body=None):
        if method == "GET":
            return self._get(path)
        return self._write(method, path, body)

    def _get(self, path):
        if "/appStoreVersions?" in path:
            return {
                "data": [
                    {
                        "id": "ver1",
                        "attributes": {
                            "appStoreState": "PREPARE_FOR_SUBMISSION",
                            "versionString": "1.4",
                        },
                    }
                ]
            }
        if path.endswith("/appInfos"):
            return {
                "data": [{"id": "info1", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION"}}]
            }
        if "/appInfoLocalizations" in path:
            return {"data": [self._row(loc, ident, "info") for loc, ident in self.info.items()]}
        if "/appStoreVersionLocalizations" in path:
            return {
                "data": [self._row(loc, ident, "version") for loc, ident in self.version.items()]
            }
        raise AssertionError(f"unexpected GET {path}")

    def _row(self, locale, ident, kind):
        attributes = {"locale": locale}
        if kind == "info":
            attributes.update(name=f"name-{locale}", subtitle=f"sub-{locale}")
        else:
            attributes.update(
                keywords=f"kw-{locale}", description=f"desc-{locale}", promotionalText=None
            )
        return {"id": ident, "attributes": attributes}

    def _write(self, method, path, body):
        resource = body["data"]["type"]
        locale = body["data"]["attributes"].get("locale")
        if method == "PATCH":
            ident = path.rsplit("/", 1)[-1]
            self.writes.append(("PATCH", resource, ident))
            return {"data": {"id": ident}}

        if locale in self.fail_on:
            raise asc.ASCError(f"App Store Connect returned 500 for POST {path}")
        registry = self.info if resource == "appInfoLocalizations" else self.version
        if locale in registry:
            raise asc.ASCError(
                f"App Store Connect returned 409 for POST /{resource}\n"
                f"  Entity with locale: {locale} already exists. Try updating."
            )
        registry[locale] = f"new-{locale}"
        self.writes.append(("POST", resource, locale))
        if self.auto_pairs and resource == "appInfoLocalizations":
            self.version.setdefault(locale, f"auto-{locale}")
        return {"data": {"id": registry[locale]}}


def install(test, connect):
    original = asc.call
    asc.call = connect.call
    test.addCleanup(lambda: setattr(asc, "call", original))
    return connect


FIELDS = {"name": "N", "subtitle": "S", "keywords": "k1,k2", "description": "D"}


class MultiLocalePush(unittest.TestCase):
    def test_every_locale_lands_in_one_run(self):
        """The reported bug: exactly one new locale landed per invocation."""
        connect = install(self, FakeConnect(auto_pairs=True))
        metadata = {locale: dict(FIELDS) for locale in ("ar-SA", "de-DE", "fr-FR")}

        actions = asc.push("123", metadata, "token", apply=True)

        touched = {action["locale"] for action in actions}
        self.assertEqual(touched, {"ar-SA", "de-DE", "fr-FR"})
        self.assertEqual(len(actions), 6)

    def test_auto_created_pair_is_adopted_not_reported_as_created(self):
        connect = install(self, FakeConnect(auto_pairs=True))

        actions = asc.push("123", {"ar-SA": dict(FIELDS)}, "token", apply=True)

        by_resource = {action["resource"]: action["operation"] for action in actions}
        self.assertEqual(by_resource["appInfoLocalizations"], "created")
        # App Store Connect made this one for us; saying "created" would be a lie.
        self.assertEqual(by_resource["appStoreVersionLocalizations"], "adopted")

    def test_existing_locale_is_patched(self):
        install(self, FakeConnect(info_locales=["de-DE"], version_locales=["de-DE"]))

        actions = asc.push("123", {"de-DE": dict(FIELDS)}, "token", apply=True)

        self.assertEqual([action["operation"] for action in actions], ["updated", "updated"])

    def test_second_run_is_a_clean_no_op_of_patches(self):
        connect = install(self, FakeConnect(auto_pairs=True))
        metadata = {locale: dict(FIELDS) for locale in ("ar-SA", "de-DE")}
        asc.push("123", metadata, "token", apply=True)

        actions = asc.push("123", metadata, "token", apply=True)

        self.assertTrue(all(action["operation"] == "updated" for action in actions))

    def test_dry_run_writes_nothing(self):
        connect = install(self, FakeConnect(auto_pairs=True))

        actions = asc.push("123", {"de-DE": dict(FIELDS)}, "token", apply=False)

        self.assertEqual(connect.writes, [])
        self.assertEqual([action["operation"] for action in actions], ["create", "create"])


class PartialFailureIsReported(unittest.TestCase):
    def test_progress_fires_for_each_completed_write(self):
        connect = install(self, FakeConnect(auto_pairs=True))
        seen = []

        asc.push(
            "123",
            {locale: dict(FIELDS) for locale in ("de-DE", "fr-FR")},
            "token",
            apply=True,
            progress=seen.append,
        )

        self.assertEqual(len(seen), 4)
        self.assertEqual(seen[0]["locale"], "de-DE")

    def test_locales_written_before_an_abort_are_already_reported(self):
        """The abort left the account half-updated and printed nothing."""
        connect = install(self, FakeConnect(auto_pairs=True, fail_on={"fr-FR"}))
        seen = []

        with self.assertRaises(asc.ASCError):
            asc.push(
                "123",
                {locale: dict(FIELDS) for locale in ("de-DE", "fr-FR", "it-IT")},
                "token",
                apply=True,
                progress=seen.append,
            )

        self.assertEqual({action["locale"] for action in seen}, {"de-DE"})


class Pull(unittest.TestCase):
    def test_emits_the_shape_check_and_push_consume(self):
        install(self, FakeConnect(info_locales=["de-DE"], version_locales=["de-DE"]))

        listing = asc.pull("123", "token")

        self.assertEqual(
            listing,
            {
                "de-DE": {
                    "name": "name-de-DE",
                    "subtitle": "sub-de-DE",
                    "keywords": "kw-de-DE",
                    "description": "desc-de-DE",
                }
            },
        )

    def test_merges_both_resources_per_locale(self):
        install(self, FakeConnect(info_locales=["de-DE", "fr-FR"], version_locales=["de-DE"]))

        listing = asc.pull("123", "token")

        self.assertEqual(sorted(listing), ["de-DE", "fr-FR"])
        self.assertIn("keywords", listing["de-DE"])
        self.assertNotIn("keywords", listing["fr-FR"])

    def test_never_set_fields_are_omitted_not_emitted_empty(self):
        install(self, FakeConnect(version_locales=["de-DE"]))

        listing = asc.pull("123", "token")

        self.assertNotIn("promotionalText", listing["de-DE"])

    def test_round_trips_through_push_as_a_no_op(self):
        connect = install(self, FakeConnect(info_locales=["de-DE"], version_locales=["de-DE"]))

        actions = asc.push("123", asc.pull("123", "token"), "token", apply=True)

        self.assertTrue(all(action["operation"] == "updated" for action in actions))


if __name__ == "__main__":
    unittest.main()
