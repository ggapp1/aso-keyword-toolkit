import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from asokit import cli
from tests.fakes import FakeConnect, install
from tests.test_creative import png_bytes


class LibraryEngine(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())
        self.root = Path(tempfile.mkdtemp())
        (self.root / "asokit.json").write_text(json.dumps({"app": {"appId": 1}}))
        self.dir = self.root / "out"
        for locale in ("en-US", "de-DE"):
            (self.dir / locale).mkdir(parents=True)
            for n in (1, 2):
                (self.dir / locale / f"0{n}.png").write_bytes(png_bytes(1290, 2796) + f"{locale}{n}".encode())
        patcher = mock.patch.object(cli, "_bearer", return_value="t")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.main(["--config", str(self.root / "asokit.json"), *argv])
        return buffer.getvalue()

    def test_default_engine_is_sets(self):
        args = cli.build_parser().parse_args(["screenshots", "push", "d"])
        self.assertEqual(args.engine, "sets")
        self.assertEqual(cli.build_parser().parse_args(["screenshots", "status"]).engine, "sets")

    def test_push_places_then_rerun_writes_nothing(self):
        self.run_cli("screenshots", "push", str(self.dir), "--engine", "library", "--apply")
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["01.png", "02.png"])
        self.assertEqual(self.fake.group("vl-de", "G_IPHONE_L"), ["01.png", "02.png"])
        before = len(self.fake.writes())
        self.run_cli("screenshots", "push", str(self.dir), "--engine", "library", "--apply")
        self.assertEqual(len(self.fake.writes()), before)

    def test_status_maps_groups_back_to_legacy_names(self):
        self.run_cli("screenshots", "push", str(self.dir), "--engine", "library", "--apply")
        text = self.run_cli("screenshots", "status", "--engine", "library")
        self.assertIn("en-US", text)
        self.assertIn("APP_IPHONE_67 ×2", text)

    def test_mirror_replaces_asset_ids_without_upload(self):
        ipad = self.root / "ipad" / "en-US"
        ipad.mkdir(parents=True)
        (ipad / "01.png").write_bytes(png_bytes(2064, 2752))
        self.run_cli("screenshots", "push", str(self.root / "ipad"), "--display", "APP_IPAD_PRO_3GEN_129", "--engine", "library", "--apply")
        uploads_before = sum(1 for e in self.fake.log if e[:2] == ("POST", "/appAssetLibraryImages"))
        self.run_cli("screenshots", "push", str(self.dir), "--engine", "library", "--mirror", "APP_IPAD_PRO_3GEN_129",
                     "--mirror-from", "en-US", "--apply")
        self.assertEqual(self.fake.group("vl-de", "G_IPAD_13"), ["01.png"])
        new_uploads = sum(1 for e in self.fake.log if e[:2] == ("POST", "/appAssetLibraryImages")) - uploads_before
        self.assertEqual(new_uploads, 4)   # only the iPhone files; the iPad asset is re-placed, not re-uploaded

    def test_mirror_wins_over_files_of_the_mirrored_display(self):
        src = self.root / "ipad" / "en-US"
        src.mkdir(parents=True)
        (src / "src.png").write_bytes(png_bytes(2064, 2752) + b"source")
        self.run_cli("screenshots", "push", str(self.root / "ipad"), "--display", "APP_IPAD_PRO_3GEN_129", "--engine", "library", "--apply")
        local = self.root / "ipad-de" / "de-DE"
        local.mkdir(parents=True)
        for n in (1, 2):
            (local / f"0{n}.png").write_bytes(png_bytes(2064, 2752) + f"de{n}".encode())
        argv = ("screenshots", "push", str(self.root / "ipad-de"), "--display", "APP_IPAD_PRO_3GEN_129", "--engine", "library",
                "--mirror", "APP_IPAD_PRO_3GEN_129", "--mirror-from", "en-US", "--apply")
        self.run_cli(*argv)
        self.assertEqual(self.fake.group("vl-de", "G_IPAD_13"), ["src.png"])
        before = len(self.fake.writes())
        self.run_cli(*argv)
        self.assertEqual(len(self.fake.writes()), before)
        self.assertEqual(self.fake.group("vl-de", "G_IPAD_13"), ["src.png"])

    def test_status_empty_report_prints_only_the_version_line(self):
        with mock.patch.object(cli, "_library_status", return_value=("2.2.0", {})):
            text = self.run_cli("screenshots", "status", "--engine", "library")
        self.assertEqual(text, "editable version: 2.2.0\n")

    def test_mirror_warns_when_source_has_several_groups_of_the_display_class(self):
        ipad = self.root / "ipad" / "en-US"
        ipad.mkdir(parents=True)
        (ipad / "01.png").write_bytes(png_bytes(2064, 2752))
        self.run_cli("screenshots", "push", str(self.root / "ipad"), "--display", "APP_IPAD_PRO_3GEN_129", "--engine", "library", "--apply")
        self.run_cli("screenshots", "push", str(self.dir), "--engine", "library", "--apply")
        real = cli.library.Catalog.display_class
        both = lambda catalog, group: "IPAD_13_DISPLAY" if group in ("G_IPHONE_L", "G_IPAD_13") else real(catalog, group)
        with mock.patch.object(cli.library.Catalog, "display_class", both):
            text = self.run_cli("screenshots", "push", str(self.dir), "--engine", "library",
                                "--mirror", "APP_IPAD_PRO_3GEN_129", "--mirror-from", "en-US")
        self.assertIn("warning", text)
        self.assertIn("G_IPHONE_L", text)
        self.assertIn("G_IPAD_13", text)


if __name__ == "__main__":
    unittest.main()
