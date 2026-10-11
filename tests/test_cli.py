import csv
import json
import tempfile
import unittest
from pathlib import Path

from asokit import cli
from tests.fakes import FakeCppConnect
from tests.test_cpp import make_doc, page as cpp_page


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


import contextlib
import io
from unittest import mock

from asokit import asc as asc_module
from tests.fakes import FakeConnect, install
from tests.test_creative import png_bytes


class AssetsFixture(unittest.TestCase):
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


class AssetsCommands(AssetsFixture):
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


from asokit import library as library_module


class AssetsSubmitCommand(AssetsFixture):
    """`assets submit`: guards first, wait on every unprocessed asset, skip assets already in review."""

    def seed_image(self, locale, state, spec="S_UNIV"):
        data = (self.out / f"{locale}.png").read_bytes()
        reference, _ = library_module.reference_name(f"{locale}.png", data)
        image_id = f"seed-{locale}"
        self.fake.images[image_id] = {"fileName": f"{locale}.png", "fileSize": len(data), "category": library_module.CREATIVE,
                                      "referenceName": reference, "state": state, "specId": spec}
        return image_id

    def image_posts(self):
        return [e for e in self.fake.writes() if e[:2] == ("POST", "/appAssetLibraryImages")]

    def test_foreign_draft_stops_before_any_upload(self):
        self.fake.submissions["s0"] = {"state": "READY_FOR_REVIEW", "items": [("appStoreVersion", "appStoreVersions", "v1")]}
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("assets", "submit", str(self.out), "--apply")
        self.assertIn("appStoreVersion", str(caught.exception))
        self.assertEqual(self.image_posts(), [])
        self.assertEqual(self.fake.submissions["s0"]["state"], "READY_FOR_REVIEW")

    def test_in_flight_submission_stops_before_any_upload(self):
        self.fake.submissions["s0"] = {"state": "IN_REVIEW", "items": []}
        with self.assertRaises(SystemExit):
            self.run_cli("assets", "submit", str(self.out), "--apply")
        self.assertEqual(self.image_posts(), [])

    def test_waits_on_reused_unprocessed_assets_and_fails_on_bad_state(self):
        seeded = self.seed_image("en-US", "UPLOAD_COMPLETE", spec=None)
        with mock.patch.object(library_module, "wait_processed",
                               return_value={seeded: {"state": "FAILED", "specId": None}}) as waited:
            with self.assertRaises(SystemExit) as caught:
                self.run_cli("assets", "submit", str(self.out), "--locales", "en-US", "--apply")
        self.assertEqual(waited.call_args.args[1], [seeded])
        self.assertIn(seeded, str(caught.exception))
        self.assertEqual(self.fake.submissions, {})

    def test_reused_asset_already_in_review_is_skipped(self):
        self.seed_image("en-US", "IN_REVIEW")
        text = self.run_cli("assets", "submit", str(self.out), "--apply")
        self.assertIn("already IN_REVIEW", text)
        (sub,) = self.fake.submissions.values()
        ids = [rid for _, _, rid in sub["items"]]
        self.assertNotIn("seed-en-US", ids)
        self.assertEqual(len(ids), 1)
        self.assertEqual(sub["state"], "WAITING_FOR_REVIEW")

    def test_nothing_left_to_submit_exits_cleanly(self):
        self.seed_image("en-US", "APPROVED")
        self.seed_image("de-DE", "WAITING_FOR_REVIEW")
        text = self.run_cli("assets", "submit", str(self.out), "--apply")
        self.assertIn("nothing to submit", text)
        self.assertEqual(self.fake.writes(), [])


class AssetsStatusLabels(AssetsFixture):
    def test_status_labels_header_and_search(self):
        self.run_cli("assets", "push", str(self.out), "--target", "default", "--apply")
        # Plain FakeConnect models no custom product pages; status now lists them too.
        with mock.patch.object(cli.cpp_apply, "list_pages", return_value=[]):
            text = self.run_cli("assets", "status")
        self.assertIn("header:", text)
        self.assertIn("search:", text)
        self.assertNotIn("product:", text)


class CppCommands(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeCppConnect())
        self.root = Path(tempfile.mkdtemp())
        make_doc(self.root, [cpp_page()])
        (self.root / "asokit.json").write_text(json.dumps({"app": {"appId": 1}}))
        patcher = mock.patch.object(cli, "_bearer", return_value="t")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.main(["--config", str(self.root / "asokit.json"), *argv])
        return buffer.getvalue()

    def test_check_offline(self):
        self.assertIn("ok", self.run_cli("cpp", "check", "--offline").lower())

    def test_push_dry_run_then_apply_then_status_export(self):
        self.assertIn("DRY RUN", self.run_cli("cpp", "push"))
        self.assertEqual(self.fake.writes(), [])
        self.run_cli("cpp", "push", "--apply")
        export = self.root / "ads.csv"
        text = self.run_cli("cpp", "status", "--ads-export", str(export))
        self.assertIn("BPD tracker", text)
        self.assertIn("bpd;borderline", export.read_text())

    def test_submit_and_publish_require_pages(self):
        for command in ("submit", "publish"):
            with self.assertRaises(SystemExit) as caught:
                self.run_cli("cpp", command, "--apply")
            self.assertIn("--pages is required", str(caught.exception))
        self.assertEqual(self.fake.log, [])

    def test_push_apply_ads_export_has_ids_for_pages_created_in_the_run(self):
        export = self.root / "ads.csv"
        self.run_cli("cpp", "push", "--apply", "--ads-export", str(export))
        with open(export, newline="", encoding="utf-8") as handle:
            (row,) = list(csv.DictReader(handle))
        self.assertEqual(row["page_name"], "BPD tracker")
        self.assertTrue(row["page_id"])
        self.assertTrue(row["page_url"])
        self.assertTrue(row["latest_state"])

    def test_submit_malformed_keywords_exits_cleanly_without_requests(self):
        broken = cpp_page()
        broken["locales"]["en-US"]["keywords"] = "bpd, borderline"
        (self.root / "cpp.json").write_text(json.dumps({"pages": [broken]}))
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("cpp", "submit", "--pages", "BPD tracker", "--apply")
        self.assertIn("must be a list of strings", str(caught.exception))
        self.assertEqual(self.fake.log, [])

    def test_assets_status_survives_cpp_listing_failure(self):
        self.fake.fail_on = ("GET", "/apps/1/appCustomProductPages")
        text = self.run_cli("assets", "status")
        self.assertIn("custom product pages: unavailable (injected failure", text)

    def test_assets_push_cpp_target_needs_editable_version(self):
        out = self.root / "assets-out" / "bpd"
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("assets", "push", str(out), "--target", "cpp:BPD tracker")
        self.assertIn("cpp push", str(caught.exception))
        self.run_cli("cpp", "push", "--apply")
        self.run_cli("assets", "push", str(out), "--target", "cpp:BPD tracker", "--locales", "en-US")

    def test_check_malformed_keywords_reports_cleanly(self):
        broken = cpp_page()
        broken["locales"]["en-US"]["keywords"] = "bpd, borderline"
        (self.root / "cpp.json").write_text(json.dumps({"pages": [broken]}))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
            cli.main(["--config", str(self.root / "asokit.json"), "cpp", "check", "--offline"])
        self.assertIn("must be a list of strings", buffer.getvalue())

    def run_cli_aborting(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
            cli.main(["--config", str(self.root / "asokit.json"), *argv])
        return buffer.getvalue()

    def test_rejected_asset_abort_says_change_the_image_not_rerun(self):
        rejected = cli.library.RejectedAsset("asokit:abc: this exact image was rejected by App Review — change it and re-render")
        with mock.patch.object(cli.cpp_apply, "push", side_effect=rejected):
            text = self.run_cli_aborting("cpp", "push", "--apply")
        self.assertIn("change the image", text)
        self.assertNotIn("Re-running is safe", text)
        self.run_cli("cpp", "push", "--apply")
        out = self.root / "assets-out" / "bpd"
        with mock.patch.object(cli.library, "sync_groups", side_effect=rejected):
            text = self.run_cli_aborting("assets", "push", str(out), "--target", "cpp:BPD tracker", "--locales", "en-US", "--apply")
        self.assertIn("change the image", text)
        self.assertNotIn("Re-running is safe", text)

    def test_check_pages_scope_flags_out_of_scope_live_owner(self):
        self.fake.add_page("Alpha", locales={"en-US": {"keywords": ["bpd"]}})
        doc = json.loads((self.root / "cpp.json").read_text())
        doc["pages"].append(cpp_page(name="Alpha", keywords=()))
        (self.root / "cpp.json").write_text(json.dumps(doc))
        self.assertIn("ok", self.run_cli("cpp", "check").lower())
        text = self.run_cli_aborting("cpp", "check", "--pages", "BPD tracker")
        self.assertIn("already belongs to page 'Alpha'", text)

    def test_push_summary_names_pages_whose_routing_changed(self):
        self.run_cli("cpp", "push", "--apply")
        for version in self.fake.cpp_versions.values():
            version["state"] = "APPROVED"
        page_id = self.fake.page_named("BPD tracker")
        self.fake.pages[page_id]["visible"] = True
        doc = json.loads((self.root / "cpp.json").read_text())
        doc["pages"][0]["locales"]["en-US"]["keywords"] = ["bpd"]
        (self.root / "cpp.json").write_text(json.dumps(doc))
        text = self.run_cli_aborting("cpp", "push", "--apply")
        self.assertIn("--allow-live-routing", text)
        text = self.run_cli("cpp", "push", "--apply", "--allow-live-routing")
        self.assertIn("organic routing changed now for: BPD tracker", text)
        self.assertNotIn("stay hidden until", text)

    def test_other_abort_still_says_rerun_is_safe(self):
        with mock.patch.object(cli.cpp_apply, "push", side_effect=cli.asc.ASCError("boom")):
            text = self.run_cli_aborting("cpp", "push", "--apply")
        self.assertIn("Re-running is safe", text)

    def test_assets_status_lists_cpp_pages_without_editable_app_version(self):
        self.run_cli("cpp", "push", "--apply")
        self.fake.versions[:] = [v for v in self.fake.versions if v["id"] == "v0"]
        text = self.run_cli("assets", "status")
        self.assertIn("no editable App Store version", text)
        self.assertIn("custom product page 'BPD tracker'", text)
        self.assertIn("header:", text)


if __name__ == "__main__":
    unittest.main()
