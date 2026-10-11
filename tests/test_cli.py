import json
import tempfile
import unittest
from pathlib import Path

from asokit import cli


class Args:
    def __init__(self, out=None, all=False):
        self.out = out
        self.all = all


class OutputDirectory(unittest.TestCase):
    CONFIG = {"app": {"outputDir": "aso"}}

    def test_defaults_to_a_per_market_directory_under_the_configured_root(self):
        self.assertEqual(cli.output_dir(self.CONFIG, "de", Args()), Path("aso/de"))

    def test_falls_back_to_aso_when_no_output_dir_is_configured(self):
        self.assertEqual(cli.output_dir({}, "de", Args()), Path("aso/de"))

    def test_out_is_the_directory_itself_for_a_single_market(self):
        self.assertEqual(
            cli.output_dir(self.CONFIG, "de", Args(out="somewhere")), Path("somewhere")
        )

    def test_out_is_the_parent_with_all(self):
        """--out used to be rejected outright, which was a surprise mid-plan."""
        self.assertEqual(
            cli.output_dir(self.CONFIG, "de", Args(out="somewhere", all=True)),
            Path("somewhere/de"),
        )

    def test_each_market_gets_its_own_directory_under_the_parent(self):
        args = Args(out="/tmp/run", all=True)
        dirs = [cli.output_dir(self.CONFIG, market, args) for market in ("de", "fr")]
        self.assertEqual(dirs, [Path("/tmp/run/de"), Path("/tmp/run/fr")])


SCORES = [
    {
        "term": "blutzucker tagebuch",
        "opportunity": 9,
        "competitionTier": 1,
        "offCategory": False,
        "looksLikeAppName": False,
        "topApps": [],
    }
]


class SuggestOutput(unittest.TestCase):
    """The drafted file has to be something `check` passes and `push` can send."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "aso" / "de").mkdir(parents=True)
        (self.root / "aso" / "de" / "scores.json").write_text(json.dumps(SCORES))
        (self.root / "asokit.json").write_text(
            json.dumps(
                {
                    "app": {"appId": 1, "outputDir": str(self.root / "aso")},
                    "markets": {"de": {"seeds": ["blutzucker"]}},
                }
            )
        )
        self.baseline = self.root / "baseline.json"
        self.baseline.write_text(
            json.dumps(
                {
                    "de-DE": {
                        "name": "Zucker",
                        "subtitle": "Im Blick",
                        "keywords": "fodmap",
                        "description": "Echte Beschreibung.",
                    }
                }
            )
        )

    def run_suggest(self, extra):
        parser = cli.build_parser()
        args = parser.parse_args(
            ["--config", str(self.root / "asokit.json"), "metadata", "suggest"] + extra
        )
        out = self.root / "draft.json"
        args.out = str(out)
        args.func(args)
        return json.loads(out.read_text())

    def test_baseline_fields_are_carried_into_the_draft(self):
        drafted = self.run_suggest(
            ["--market", "de", "--baseline", str(self.baseline), "--json"]
        )
        self.assertEqual(drafted["de-DE"]["description"], "Echte Beschreibung.")
        self.assertEqual(drafted["de-DE"]["name"], "Zucker")

    def test_drafted_file_passes_check(self):
        """A keywords-only fragment would trip the submission rule on every locale."""
        from asokit import metadata

        drafted = self.run_suggest(
            ["--market", "de", "--baseline", str(self.baseline), "--json"]
        )
        self.assertEqual(metadata.check(drafted), [])

    def test_keywords_are_replaced_not_appended(self):
        drafted = self.run_suggest(
            ["--market", "de", "--baseline", str(self.baseline), "--json"]
        )
        self.assertIn("blutzucker", drafted["de-DE"]["keywords"])

    def test_incumbent_term_survives_into_the_new_field(self):
        drafted = self.run_suggest(
            ["--market", "de", "--baseline", str(self.baseline), "--json"]
        )
        self.assertIn("fodmap", drafted["de-DE"]["keywords"].split(","))

    def test_without_a_baseline_the_draft_is_keywords_only(self):
        drafted = self.run_suggest(["--market", "de", "--json"])
        self.assertEqual(list(drafted["de-DE"]), ["keywords"])


if __name__ == "__main__":
    unittest.main()


import contextlib
import io
from unittest import mock

from asokit import asc as asc_module
from tests.fakes import FakeConnect, install
from tests.test_creative import png_bytes


class AssetsCommands(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())
        self.root = Path(tempfile.mkdtemp())
        (self.root / "asokit.json").write_text(json.dumps({"app": {"appId": 1}}))
        self.out = self.root / "assets-out" / "default"
        self.out.mkdir(parents=True)
        for locale in ("en-US", "de-DE"):
            (self.out / f"{locale}.png").write_bytes(png_bytes(5244, 2950) + locale.encode())
        patcher = mock.patch.object(cli, "_bearer", return_value="t")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.main(["--config", str(self.root / "asokit.json"), *argv])
        return buffer.getvalue()

    def test_push_default_dry_run(self):
        text = self.run_cli("assets", "push", str(self.out), "--target", "default")
        self.assertIn("DRY RUN", text)
        self.assertEqual(self.fake.writes(), [])

    def test_push_default_apply_places_and_writes_ledger(self):
        self.run_cli("assets", "push", str(self.out), "--target", "default", "--apply")
        self.assertEqual(self.fake.group("vl-en", "G_HEADER"), ["en-US.png"])
        self.assertEqual(self.fake.group("vl-de", "G_SEARCH"), ["de-DE.png"])
        self.assertTrue((self.root / "asokit-ledger.jsonl").exists())

    def test_push_refuses_while_experiment_runs(self):
        self.fake.experiments = [{"id": "e", "attributes": {"name": "Icon test", "state": "IN_REVIEW"}}]
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("assets", "push", str(self.out), "--target", "default", "--apply")
        self.assertIn("Icon test", str(caught.exception))

    def test_push_refuses_version_waiting_for_review(self):
        self.fake.versions[0]["attributes"]["appStoreState"] = "WAITING_FOR_REVIEW"
        with self.assertRaises(SystemExit):
            self.run_cli("assets", "push", str(self.out), "--target", "default", "--apply")

    def test_push_unknown_locale_fails_before_any_write(self):
        (self.out / "fr-FR.png").write_bytes(png_bytes(5244, 2950))
        with self.assertRaises(SystemExit):
            self.run_cli("assets", "push", str(self.out), "--target", "default", "--apply")
        self.assertEqual(self.fake.writes(), [])

    def test_status_catalog_dump(self):
        text = self.run_cli("assets", "status", "--catalog")
        self.assertIn("PRODUCT_PAGE_HEADER_ASSET", text)
