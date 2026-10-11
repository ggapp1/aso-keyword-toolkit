import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from asokit import creative


def png_bytes(width, height, colour_type=2, bit_depth=8, trns=False):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    body = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, 0))
    if colour_type == 3:
        body += chunk(b"PLTE", b"\x00\x00\x00")
    if trns:
        body += chunk(b"tRNS", b"\x00")
    return b"\x89PNG\r\n\x1a\n" + body + chunk(b"IDAT", b"") + chunk(b"IEND", b"")


class PlanTests(unittest.TestCase):
    def test_ignores_underscore_and_dot_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("en-US.png", "de-DE.png", "_contact.png", ".DS_Store", "notes.txt"):
                (Path(tmp) / name).write_bytes(png_bytes(5244, 2950))
            (Path(tmp) / "_contact").mkdir()
            plan = creative.plan_from_directory(tmp)
            self.assertEqual(sorted(plan), ["de-DE", "en-US"])


class CheckTests(unittest.TestCase):
    def _plan(self, tmp, **kwargs):
        path = Path(tmp) / "en-US.png"
        path.write_bytes(png_bytes(**kwargs))
        return {"en-US": path}

    def test_accepts_universal_rgb(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(creative.check(self._plan(tmp, width=5244, height=2950)), [])

    def test_rejects_wrong_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = creative.check(self._plan(tmp, width=3840, height=1646))
            self.assertTrue(any("3840×1646" in p for p in problems))

    def test_rejects_alpha_grayscale_palette_with_trns_and_16_bit(self):
        cases = [dict(colour_type=6), dict(colour_type=4), dict(colour_type=0),
                 dict(colour_type=3, trns=True), dict(colour_type=2, bit_depth=16)]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                self.assertTrue(creative.check(self._plan(tmp, width=5244, height=2950, **case)))

    def test_accepts_palette_without_trns(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(creative.check(self._plan(tmp, width=5244, height=2950, colour_type=3)), [])

    def test_max_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(creative.check(self._plan(tmp, width=5244, height=2950), max_bytes=10))


class LintTests(unittest.TestCase):
    def test_flags_each_category_in_english(self):
        bad = ["Only $4.99", "50% off today", "Free trial", "Visit moodsync.app", "© MoodSync",
               "The #1 mood app", "Editor's Choice", "Better than Android apps",
               "Diagnose bipolar", "Clinical-grade tracking", "Catch episodes early detection", "Suicide prevention"]
        for text in bad:
            with self.subTest(text=text):
                self.assertTrue(creative.lint(text, "en-US"))

    def test_clean_copy_passes(self):
        for text in ["LOG MOOD SWINGS", "Triggers, symptoms & patterns", "Share a report with your therapist"]:
            with self.subTest(text=text):
                self.assertEqual(creative.lint(text, "en-GB"), [])

    def test_word_boundaries(self):
        self.assertEqual(creative.lint("Offline patterns", "en-US"), [])
        self.assertEqual(creative.lint("Treats yourself kindly", "en-US"), [])

    def test_german_health_claim(self):
        self.assertTrue(creative.lint("Früherkennung von Episoden", "de-DE"))
        self.assertEqual(creative.lint("Muster erkennen", "de-DE"), [])

    def test_linted_languages(self):
        self.assertTrue(creative.linted("pt-BR"))
        self.assertFalse(creative.linted("ja"))


if __name__ == "__main__":
    unittest.main()
