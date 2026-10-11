import json
import math
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, features
    HAVE_PIL = True
    HAVE_RAQM = features.check("raqm")
except ImportError:
    HAVE_PIL = HAVE_RAQM = False

from asokit import render

BG = (67, 56, 202)


def write_config(root, variants, rtl=None):
    caps = Path(root) / "caps" / "en"
    caps.mkdir(parents=True)
    for name, colour in (("one.png", (255, 0, 0)), ("two.png", (0, 255, 0))):
        Image.new("RGB", (1179, 2556), colour).save(caps / name)
    cfg = {"brand": {"background": "#4338CA", "text": "#FFFFFF", "frame": "#1C1C1E"},
           "type": {"verb": {"size": 300, "min": 120, "step": 10, "lines": 1, "leading": 1.02},
                    "descriptor": {"size": 160, "min": 80, "step": 6, "lines": 2, "leading": 1.12},
                    "tight": {"verb": 150, "descriptor": 90}},
           "rtl": rtl or [], "variants": variants}
    path = Path(root) / "assets.json"
    path.write_text(json.dumps(cfg))
    return render.load_config(path)


def variant(heads, captures=("{ui}/one.png",)):
    return {"captures": list(captures), "capturesRoot": "caps", "ui": "en", "headlines": heads}


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class RenderTests(unittest.TestCase):
    def test_safe_box_sits_inside_both_crops(self):
        x0, y0, x1, y1 = render.safe_box(5244, 2950, 0.03)
        header_top, header_bottom = (2950 - 5244 * 9 / 21) / 2, (2950 + 5244 * 9 / 21) / 2
        search_left, search_right = (5244 - 2950 * 1.5) / 2, (5244 + 2950 * 1.5) / 2
        self.assertTrue(header_top <= y0 and y1 <= header_bottom)
        self.assertTrue(search_left <= x0 and x1 <= search_right)
        # Inset 0: the far edges never round outward; the near edges are the spec's floored origin.
        x0, y0, x1, y1 = render.safe_box(5244, 2950, 0)
        self.assertTrue(math.floor(header_top) <= y0 and y1 <= header_bottom, (y0, y1, header_top, header_bottom))
        self.assertTrue(math.floor(search_left) <= x0 and x1 <= search_right, (x0, x1, search_left, search_right))

    def test_output_size_mode_and_containment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG MOOD SWINGS", "Triggers, symptoms & patterns"]},
                                                  captures=("{ui}/one.png", "{ui}/two.png"))})
            result = render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertEqual(result["failed"], {})
            image = Image.open(Path(tmp) / "out" / "v" / "en-US.png")
            self.assertEqual((image.size, image.mode), ((5244, 2950), "RGB"))
            background = Image.new("RGB", image.size, BG)
            from PIL import ImageChops
            bbox = ImageChops.difference(image, background).getbbox()
            x0, y0, x1, y1 = render.safe_box(5244, 2950, 0.03)
            self.assertTrue(bbox[0] >= x0 and bbox[1] >= y0 and bbox[2] <= x1 and bbox[3] <= y1, (bbox, (x0, y0, x1, y1)))
            self.assertTrue((Path(tmp) / "out" / "_contact" / "v.png").exists())

    def test_default_type_fits_a_realistic_headline(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["SEE THE PATTERNS", "MOOD, SLEEP & MEDS IN ONE PLACE"]},
                                                  captures=("{ui}/one.png", "{ui}/two.png"))})
            del cfg["type"]
            result = render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertEqual(result["failed"], {})
            image = Image.open(Path(tmp) / "out" / "v" / "en-US.png")
            self.assertEqual((image.size, image.mode), ((5244, 2950), "RGB"))
            from PIL import ImageChops
            bbox = ImageChops.difference(image, Image.new("RGB", image.size, BG)).getbbox()
            x0, y0, x1, y1 = render.safe_box(5244, 2950, 0.03)
            self.assertTrue(bbox[0] >= x0 and bbox[1] >= y0 and bbox[2] <= x1 and bbox[3] <= y1, (bbox, (x0, y0, x1, y1)))

    def test_failed_rerender_removes_stale_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "Patterns"]})})
            render.render_variant(cfg, "v", Path(tmp) / "out")
            target = Path(tmp) / "out" / "v" / "en-US.png"
            self.assertTrue(target.exists())
            cfg["variants"]["v"]["headlines"]["en-US"] = ["FREE TRIAL", "Patterns"]
            result = render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertIn("en-US", result["failed"])
            self.assertFalse(target.exists())

    def test_partial_type_override_merges_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "Patterns"]})})
            cfg["type"] = {"verb": {"size": 300}}
            result = render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertEqual(result["failed"], {})
            self.assertEqual(result["report"][0]["verb_px"], 300)

    def test_text_that_overflows_the_safe_box_fails_the_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "AB CD"], "en-GB": ["LOG", "Patterns"]})})
            cfg["type"]["descriptor"] = {"size": 900, "min": 900, "step": 6, "lines": 2, "leading": 1.12}
            cfg["type"]["verb"] = {"size": 300, "min": 300, "step": 10, "lines": 1, "leading": 1.02}
            result = render.render_variant(cfg, "v", Path(tmp) / "out", locales=["en-US"])
            self.assertIn("safe box", result["failed"].get("en-US", ""))
            self.assertFalse((Path(tmp) / "out" / "v" / "en-US.png").exists())

    def test_ltr_devices_trail_on_the_right(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "Patterns"]})})
            render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertGreater(_red_centre_x(Path(tmp) / "out" / "v" / "en-US.png"), 5244 / 2)

    @unittest.skipUnless(HAVE_RAQM, "Pillow without libraqm")
    def test_rtl_mirrors_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"he": ["שלום", "דפוסים"]})}, rtl=["he"])
            render.render_variant(cfg, "v", Path(tmp) / "out", lint=False)
            self.assertLess(_red_centre_x(Path(tmp) / "out" / "v" / "he.png"), 5244 / 2)

    def test_overlong_headline_fails_only_that_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "Patterns"],
                                                   "en-GB": ["X" * 120, "Patterns"]})})
            result = render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertIn("en-GB", result["failed"])
            self.assertTrue((Path(tmp) / "out" / "v" / "en-US.png").exists())
            self.assertFalse((Path(tmp) / "out" / "v" / "en-GB.png").exists())

    def test_lint_blocks_a_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["FREE TRIAL", "Patterns"]})})
            result = render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertIn("en-US", result["failed"])

    def test_three_captures_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "Patterns"]}, captures=("{ui}/one.png",) * 3)})
            with self.assertRaises(render.RenderError):
                render.render_variant(cfg, "v", Path(tmp) / "out")

    def test_unknown_requested_locale_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "Patterns"]})})
            with self.assertRaises(render.RenderError):
                render.render_variant(cfg, "v", Path(tmp) / "out", locales=["de-DE"])


class HeadlineResolutionTests(unittest.TestCase):
    def _cfg(self, tmp, spec):
        source = {"_notes": "x", "_slots": ["track", "spot"],
                  "en-US": {"h": [["TRACK", "your shifts"], ["SPOT", "patterns"]], "ui": "en", "hero": ["SEE IT", "all in one place"]},
                  "en-GB": {"same": "en-US", "ui": "en"},
                  "de-DE": {"h": [["ERFASSE", "Schwankungen"], ["ERKENNE", "Muster"]], "ui": "de"},
                  "ar-SA": {"h": [["تتبع", "التقلبات"], ["اكتشف", "الأنماط"]], "ui": "en", "rtl": True}}
        (Path(tmp) / "headlines.json").write_text(json.dumps(source, ensure_ascii=False))
        (Path(tmp) / "assets.json").write_text(json.dumps({"variants": {"d": {"captures": ["{ui}/a.png"], "headlines": spec}}}))
        return render.load_config(Path(tmp) / "assets.json")

    def test_slot_by_name_and_index_skip_meta_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            by_name = render.resolve_headlines(self._cfg(tmp, {"from": "headlines.json", "slot": "spot"}), "d")
            self.assertEqual(by_name["de-DE"]["verb"], "ERKENNE")
            self.assertNotIn("_slots", by_name)
            by_index = render.resolve_headlines(self._cfg(tmp, {"from": "headlines.json", "slot": 0}), "d")
            self.assertEqual(by_index["en-GB"]["verb"], "TRACK")
            self.assertTrue(by_index["ar-SA"]["rtl"])
            self.assertEqual(by_index["de-DE"]["ui"], "de")

    def test_mistyped_slot_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._cfg(tmp, {"from": "headlines.json", "slot": "heroo"})
            with self.assertRaisesRegex(render.RenderError, "heroo"):
                render.resolve_headlines(cfg, "d")
            if HAVE_PIL:
                with self.assertRaisesRegex(render.RenderError, "heroo"):
                    render.render_variant(cfg, "d", Path(tmp) / "out")
            cfg = self._cfg(tmp, {"from": "headlines.json", "slot": 7})
            with self.assertRaisesRegex(render.RenderError, "7"):
                render.resolve_headlines(cfg, "d")

    def test_hero_with_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            heads = render.resolve_headlines(self._cfg(tmp, {"from": "headlines.json", "slot": "hero", "fallbackSlot": 0}), "d")
            self.assertEqual((heads["en-US"]["verb"], heads["en-US"]["fallback"]), ("SEE IT", False))
            self.assertEqual((heads["en-GB"]["verb"], heads["en-GB"]["fallback"]), ("SEE IT", False))
            self.assertEqual((heads["de-DE"]["verb"], heads["de-DE"]["fallback"]), ("ERFASSE", True))

    def test_inline_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._cfg(tmp, {"en-US": ["LOG", "swings"], "en-AU": {"same": "en-US"}})
            cfg["variants"]["d"]["ui"] = "en"
            heads = render.resolve_headlines(cfg, "d")
            self.assertEqual(heads["en-AU"]["descriptor"], "swings")
            self.assertEqual(heads["en-AU"]["ui"], "en")


def _red_centre_x(path):
    image = Image.open(path).convert("RGB")
    small = image.resize((image.width // 8, image.height // 8))
    xs = [x * 8 for y in range(small.height) for x in range(small.width) if small.getpixel((x, y)) == (255, 0, 0)]
    return sum(xs) / len(xs)


if __name__ == "__main__":
    unittest.main()
