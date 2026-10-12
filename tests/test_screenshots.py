import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from asokit import asc, screenshots as shots


def png(path, width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IEND", b"")
    Path(path).write_bytes(raw)


class Planner(unittest.TestCase):
    def test_reads_dimensions_and_orders_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "de-DE").mkdir()
            png(Path(tmp) / "de-DE" / "02-b.png", 1290, 2796)
            png(Path(tmp) / "de-DE" / "01-a.png", 1290, 2796)
            plan = shots.plan_from_directory(tmp, "APP_IPHONE_67")
            self.assertEqual([p.name for p in plan["de-DE"]["APP_IPHONE_67"]], ["01-a.png", "02-b.png"])
            self.assertEqual(shots.check(plan), [])

    def test_folders_that_are_not_locale_codes_are_left_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("en-US", "zh-Hans", "no", "ipad-en-US", "_contact"):
                (Path(tmp) / name).mkdir()
                png(Path(tmp) / name / "01.png", 2064 if name.startswith("ipad") else 1290,
                    2752 if name.startswith("ipad") else 2796)
            plan = shots.plan_from_directory(tmp, "APP_IPHONE_67")
            self.assertEqual(sorted(plan), ["en-US", "no", "zh-Hans"])
            self.assertEqual(shots.check(plan), [])
            self.assertEqual(shots.non_locale_folders(tmp), ["_contact", "ipad-en-US"])

    def test_rejects_wrong_size_and_too_many(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fr-FR").mkdir()
            for i in range(11):
                png(Path(tmp) / "fr-FR" / f"{i:02d}.png", 1290, 2796)
            png(Path(tmp) / "fr-FR" / "99.png", 1206, 2622)
            problems = shots.check(shots.plan_from_directory(tmp, "APP_IPHONE_67"))
            self.assertTrue(any("at most 10" in p for p in problems))
            self.assertTrue(any("1206×2622" in p for p in problems))


class FakeScreenshotConnect:
    """Enough of App Store Connect to exercise push_screenshots end to end."""

    def __init__(self):
        self.sets = {"loc-en": {"APP_IPHONE_67": "set-en"}}
        self.shots = {"set-en": ["old-1", "old-2"]}
        self.log = []
        self.uploads = 0

    def call(self, method, path, bearer, body=None):
        self.log.append((method, path))
        if method == "GET" and path.endswith("/appStoreVersions?limit=10"):
            return {"data": [{"id": "v1", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION", "versionString": "2.2.0"}}]}
        if method == "GET" and "appStoreVersionLocalizations?limit=200" in path:
            return {"data": [{"id": "loc-en", "attributes": {"locale": "en-US"}}, {"id": "loc-de", "attributes": {"locale": "de-DE"}}]}
        if method == "GET" and path.endswith("/appScreenshotSets"):
            loc = path.split("/")[2]
            return {"data": [{"id": sid, "attributes": {"screenshotDisplayType": d}} for d, sid in self.sets.get(loc, {}).items()]}
        if method == "GET" and "/appScreenshots?limit=200" in path:
            sid = path.split("/")[2]
            return {"data": [{"id": s, "attributes": {}} for s in self.shots.get(sid, [])]}
        if method == "POST" and path == "/appScreenshotSets":
            loc = body["data"]["relationships"]["appStoreVersionLocalization"]["data"]["id"]
            new = f"set-{loc}"; self.sets.setdefault(loc, {})[body["data"]["attributes"]["screenshotDisplayType"]] = new
            self.shots[new] = []
            return {"data": {"id": new}}
        if method == "DELETE":
            for lst in self.shots.values():
                if path.rsplit("/", 1)[-1] in lst: lst.remove(path.rsplit("/", 1)[-1])
            return {}
        if method == "POST" and path == "/appScreenshots":
            self.uploads += 1
            sid = body["data"]["relationships"]["appScreenshotSet"]["data"]["id"]
            new = f"shot-{self.uploads}"; self.shots[sid].append(new)
            return {"data": {"id": new, "attributes": {"uploadOperations": [
                {"method": "PUT", "url": "https://upload.invalid/x", "offset": 0, "length": body["data"]["attributes"]["fileSize"], "requestHeaders": []}]}}}
        if method == "PATCH":
            return {}
        raise AssertionError(f"unexpected {method} {path}")


class Push(unittest.TestCase):
    def setUp(self):
        self.connect = FakeScreenshotConnect()
        original_call, original_raw = asc.call, asc._raw
        asc.call = self.connect.call
        asc._raw = lambda method, url, headers, data: b""
        self.addCleanup(lambda: setattr(asc, "call", original_call))
        self.addCleanup(lambda: setattr(asc, "_raw", original_raw))

    def test_dry_run_writes_nothing(self):
        plan = {"en-US": {"APP_IPHONE_67": [("a.png", b"x"), ("b.png", b"y")]}}
        actions = asc.push_screenshots("1", plan, "t", apply=False)
        self.assertEqual(actions[0]["delete"], 2)
        self.assertEqual(actions[0]["upload"], 2)
        self.assertFalse(any(m in ("POST", "PATCH", "DELETE") for m, _ in self.connect.log))

    def test_apply_replaces_existing_set_and_creates_missing(self):
        plan = {"en-US": {"APP_IPHONE_67": [("a.png", b"x")]},
                "de-DE": {"APP_IPHONE_67": [("a.png", b"x"), ("b.png", b"y")]}}
        actions = asc.push_screenshots("1", plan, "t", apply=True)
        by = {a["locale"]: a for a in actions}
        self.assertEqual(by["en-US"]["set"], "update")
        self.assertEqual(by["de-DE"]["set"], "create")
        self.assertEqual(len(self.connect.shots["set-en"]), 1)               # old-1/old-2 deleted, one uploaded
        self.assertNotIn("old-1", self.connect.shots["set-en"])
        self.assertEqual(len(self.connect.shots["set-loc-de"]), 2)
        self.assertIn(("PATCH", "/appScreenshotSets/set-en/relationships/appScreenshots"), self.connect.log)


if __name__ == "__main__":
    unittest.main()
