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
           "rtl": rtl or [], "variants": variants, "header": {"enabled": False}}
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
            cfg = write_config(tmp, {"v": variant({"he": ["SHALOM", "Patterns"]})}, rtl=["he"])
            render.render_variant(cfg, "v", Path(tmp) / "out", lint=False)
            self.assertLess(_red_centre_x(Path(tmp) / "out" / "v" / "he.png"), 5244 / 2)

    def test_character_the_font_lacks_fails_only_that_locale(self):
        # Pillow would draw the font's placeholder box and report success.
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(tmp, {"v": variant({"en-US": ["LOG", "Patterns"],
                                                   "he": ["LOG", "דפוסים, Patterns"]})})
            result = render.render_variant(cfg, "v", Path(tmp) / "out", lint=False)
            self.assertIn("no glyph for", result["failed"]["he"])
            self.assertIn("'ד'", result["failed"]["he"])
            self.assertNotIn("','", result["failed"]["he"])
            self.assertTrue((Path(tmp) / "out" / "v" / "en-US.png").exists())
            self.assertFalse((Path(tmp) / "out" / "v" / "he.png").exists())

    def test_spaces_and_zero_width_breaks_are_not_missing_glyphs(self):
        from PIL import ImageFont
        font = ImageFont.load_default(80)
        self.assertEqual(render._missing_glyphs(font, "LOG \u200bMOOD\u00a0NOW"), [])
        self.assertEqual(render._missing_glyphs(font, "LOG ד MOOD ד"), ["ד"])

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


HEADER_ZONE = (940, 380, 2900, 1150)
CENTRE_BAND = (677, 3163)


def _ink_bbox(image, threshold=200):
    """Bounding box of near-white (text) pixels."""
    from PIL import ImageChops
    r, g, b = image.convert("RGB").split()
    return ImageChops.darker(r, ImageChops.darker(g, b)).point(lambda v: 255 if v > threshold else 0).getbbox()


def _darker_than_background_bbox(region):
    """Pixels darker than the brand background in any channel: devices, frames, shadows (text only lightens)."""
    from PIL import ImageChops
    diff = ImageChops.subtract(Image.new("RGB", region.size, BG), region.convert("RGB"))
    r, g, b = diff.split()
    return ImageChops.lighter(r, ImageChops.lighter(g, b)).point(lambda v: 255 if v > 2 else 0).getbbox()


def _colour_centre_x(path, colour):
    image = Image.open(path).convert("RGB")
    small = image.resize((image.width // 8, image.height // 8), Image.NEAREST)
    xs = [x * 8 for y in range(small.height) for x in range(small.width) if small.getpixel((x, y)) == colour]
    return sum(xs) / len(xs) if xs else None


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class HeaderRenderTests(unittest.TestCase):
    def render(self, tmp, heads, captures=("{ui}/one.png", "{ui}/two.png"), header=None, rtl=None, **kwargs):
        cfg = write_config(tmp, {"v": variant(heads, captures=captures)}, rtl=rtl)
        cfg["header"] = header if header is not None else {}
        return cfg, render.render_variant(cfg, "v", Path(tmp) / "out", **kwargs)

    def test_header_file_size_mode_text_zone_and_clear_centre_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self.render(tmp, {"en-US": ["LOG MOOD SWINGS", "TRIGGERS, SYMPTOMS & PATTERNS"]})
            self.assertEqual(result["failed"], {})
            path = Path(tmp) / "out" / "v" / "header" / "en-US.png"
            image = Image.open(path)
            self.assertEqual((image.size, image.mode), ((3840, 1646), "RGB"))
            ink = _ink_bbox(image)
            x0, y0, x1, y1 = HEADER_ZONE
            self.assertTrue(ink[0] >= x0 and ink[1] >= y0 and ink[2] <= x1 and ink[3] <= y1, (ink, HEADER_ZONE))
            # Centred horizontally in the zone (within a few px).
            self.assertLess(abs((ink[0] + ink[2]) / 2 - (x0 + x1) / 2), 12, ink)
            band = image.crop((CENTRE_BAND[0], 0, CENTRE_BAND[1], 1646))
            self.assertIsNone(_darker_than_background_bbox(band))
            # Devices: capture[0] (red) on the left, capture[1] (green) on the right, outside the band.
            red, green = _colour_centre_x(path, (255, 0, 0)), _colour_centre_x(path, (0, 255, 0))
            self.assertLess(red, CENTRE_BAND[0])
            self.assertGreater(green, CENTRE_BAND[1])
            self.assertTrue((Path(tmp) / "out" / "_contact" / "v-header.png").exists())
            row = result["report"][0]
            self.assertEqual(row["header"]["devices"], 2)
            self.assertIn("verb_px", row["header"])

    def test_single_capture_is_used_on_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self.render(tmp, {"en-US": ["LOG", "Patterns"]}, captures=("{ui}/one.png",))
            self.assertEqual(result["failed"], {})
            image = Image.open(Path(tmp) / "out" / "v" / "header" / "en-US.png").convert("RGB")
            self.assertEqual(image.getpixel((340, 900)), (255, 0, 0))
            self.assertEqual(image.getpixel((3500, 900)), (255, 0, 0))

    def test_no_room_for_devices_skips_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self.render(tmp, {"en-US": ["LOG", "Patterns"]},
                                    header={"centreBand": [60, 3780]})
            self.assertEqual(result["failed"], {})
            image = Image.open(Path(tmp) / "out" / "v" / "header" / "en-US.png")
            self.assertIsNone(_darker_than_background_bbox(image))
            self.assertEqual(result["report"][0]["header"]["devices"], 0)

    def test_device_below_min_device_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self.render(tmp, {"en-US": ["LOG", "Patterns"]}, header={"minDevice": 0.9})
            self.assertEqual(result["failed"], {})
            self.assertEqual(result["report"][0]["header"]["devices"], 0)
            image = Image.open(Path(tmp) / "out" / "v" / "header" / "en-US.png")
            self.assertIsNone(_darker_than_background_bbox(image))

    def test_default_header_type_fits_realistic_headlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            heads = {"en-US": ["LOG MOOD SWINGS", "TRIGGERS, SYMPTOMS & PATTERNS"],
                     "en-GB": ["SEE THE PATTERNS", "MOOD, SLEEP & MEDS IN ONE PLACE"],
                     "de-DE": ["STIMMUNG ERFASSEN", "SCHLAF, SYMPTOME & MUSTER"]}
            _, result = self.render(tmp, heads)
            self.assertEqual(result["failed"], {})
            self.assertEqual(len(result["header_written"]), 3)

    def test_header_that_cannot_fit_fails_the_locale_and_deletes_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, result = self.render(tmp, {"en-US": ["LOG", "Patterns and triggers"]})
            universal = Path(tmp) / "out" / "v" / "en-US.png"
            header = Path(tmp) / "out" / "v" / "header" / "en-US.png"
            self.assertTrue(universal.exists() and header.exists())
            cfg["header"] = {"type": {"descriptor": {"size": 600, "min": 600}}}
            result = render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertIn("header", result["failed"].get("en-US", ""))
            self.assertFalse(universal.exists())
            self.assertFalse(header.exists())

    def test_universal_failure_also_deletes_a_stale_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, _ = self.render(tmp, {"en-US": ["LOG", "Patterns"]})
            header = Path(tmp) / "out" / "v" / "header" / "en-US.png"
            self.assertTrue(header.exists())
            cfg["variants"]["v"]["headlines"]["en-US"] = ["FREE TRIAL", "Patterns"]
            render.render_variant(cfg, "v", Path(tmp) / "out")
            self.assertFalse(header.exists())

    def test_disabled_header_writes_no_header_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self.render(tmp, {"en-US": ["LOG", "Patterns"]}, header={"enabled": False})
            self.assertEqual(result["failed"], {})
            self.assertTrue((Path(tmp) / "out" / "v" / "en-US.png").exists())
            self.assertFalse((Path(tmp) / "out" / "v" / "header").exists())
            self.assertFalse((Path(tmp) / "out" / "_contact" / "v-header.png").exists())
            self.assertIsNone(result["report"][0]["header"])

    def test_configurable_canvas_and_zone(self):
        with tempfile.TemporaryDirectory() as tmp:
            header = {"canvas": {"width": 1920, "height": 823}, "zone": [400, 190, 1520, 575], "centreBand": [338, 1582],
                      "type": {"verb": {"size": 130, "min": 75}, "descriptor": {"size": 65, "min": 40}}}
            _, result = self.render(tmp, {"en-US": ["LOG", "Patterns"]}, header=header)
            self.assertEqual(result["failed"], {})
            image = Image.open(Path(tmp) / "out" / "v" / "header" / "en-US.png")
            self.assertEqual(image.size, (1920, 823))
            ink = _ink_bbox(image)
            self.assertTrue(ink[0] >= 400 and ink[1] >= 190 and ink[2] <= 1520 and ink[3] <= 575, ink)

    @unittest.skipUnless(HAVE_RAQM, "Pillow without libraqm")
    def test_rtl_header_renders_centred(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self.render(tmp, {"he": ["SHALOM", "Patterns"]}, rtl=["he"], lint=False)
            self.assertEqual(result["failed"], {})
            image = Image.open(Path(tmp) / "out" / "v" / "header" / "he.png")
            self.assertEqual(image.size, (3840, 1646))
            ink = _ink_bbox(image)
            x0, y0, x1, y1 = HEADER_ZONE
            self.assertTrue(ink[0] >= x0 and ink[1] >= y0 and ink[2] <= x1 and ink[3] <= y1, ink)
            band = image.crop((CENTRE_BAND[0], 0, CENTRE_BAND[1], 1646))
            self.assertIsNone(_darker_than_background_bbox(band))


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

    def test_mistyped_named_slot_with_fallback_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._cfg(tmp, {"from": "headlines.json", "slot": "heor", "fallbackSlot": 0})
            with self.assertRaisesRegex(render.RenderError, "heor"):
                render.resolve_headlines(cfg, "d")
            cfg = self._cfg(tmp, {"from": "headlines.json", "slot": "hero", "fallbackSlot": "trak"})
            with self.assertRaisesRegex(render.RenderError, "trak"):
                render.resolve_headlines(cfg, "d")

    def test_named_slot_on_one_entry_only_falls_back_for_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            heads = render.resolve_headlines(self._cfg(tmp, {"from": "headlines.json", "slot": "hero", "fallbackSlot": 0}), "d")
            self.assertFalse(heads["en-US"]["fallback"])
            for locale in ("de-DE", "ar-SA"):
                self.assertTrue(heads[locale]["fallback"], locale)
            self.assertEqual(heads["ar-SA"]["verb"], "تتبع")

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
