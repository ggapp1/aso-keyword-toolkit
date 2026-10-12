"""Render App Store creatives: the universal file (5244×2950, search results)
and a dedicated product-page header file (3840×1646).

Driven entirely by the app's `assets.json` (see the spec / README): brand
colours, per-locale fonts and type sizes, and variants — each a headline
source plus 1–2 app captures. No app-specific code lives here.

Why two files: Apple shows the universal file whole in search results, but
crops the product-page header hard (iPhone keeps only the centre ~53% width,
iPad the top ~55% height, with system overlays on the top band and corners).
The header file centres the headline in a zone every device shows and keeps
the phones outside the centre band. An optional top-level `"header"` block
configures it; `"enabled": false` renders the universal file only.

The text fitting, wrapping and device frame are lifted from MoodSync's
portrait compositor (`screenshots/store/compose.py`) and parameterised.
"""
import json
import math
import re
from pathlib import Path

from . import creative

CANVAS = (5244, 2950)
ZWSP = "​"
DEFAULT_TYPE = {
    "verb": {"size": 360, "min": 220, "step": 10, "lines": 2, "leading": 1.02},
    "descriptor": {"size": 220, "min": 150, "step": 6, "lines": 2, "leading": 1.12},
    "tight": {"verb": 260, "descriptor": 170},
}
HEADER_CANVAS = (3840, 1646)
HEADER_ZONE = (800, 380, 3040, 1150)        # x0, y0, x1, y1: the headline shows here on every device
HEADER_BAND = (677, 3163)                   # x range devices (and their shadows) stay out of
HEADER_DEVICE_TOP = 200                     # devices start at or below this y; they may bleed off the bottom
HEADER_MIN_DEVICE = 0.4                     # skip devices smaller than this fraction of the canvas height
DEFAULT_HEADER_TYPE = {
    "verb": {"size": 260, "min": 150, "step": 10, "lines": 1, "leading": 1.02},
    "descriptor": {"size": 130, "min": 80, "step": 6, "lines": 1, "leading": 1.12},
    "tight": {"verb": 190, "descriptor": 100},
}


class RenderError(Exception):
    pass


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
    except ImportError as error:
        raise RenderError("asokit assets render needs Pillow: pip install 'aso-keyword-toolkit[render]'") from error
    return Image, ImageDraw, ImageFilter, ImageFont, features


def safe_box(width, height, inset):
    """Intersection of the centred 21:9 (header) and 3:2 (search) crops, inset on every side."""
    w = min(width, height * 3 / 2)
    h = min(height, width * 9 / 21)
    x0, y0 = math.floor((width - w) / 2), math.floor((height - h) / 2)
    # Floor the far edge too: with a floored origin, origin + w never passes the crop's far edge.
    x1, y1 = math.floor(x0 + w), math.floor(y0 + h)
    dx, dy = math.ceil((x1 - x0) * inset), math.ceil((y1 - y0) * inset)
    return x0 + dx, y0 + dy, x1 - dx, y1 - dy


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg["_root"] = Path(path).resolve().parent
    return cfg


def _hex(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- headlines

def _from_file(cfg, spec):
    data = json.loads((cfg["_root"] / spec["from"]).read_text(encoding="utf-8"))
    names = data.get("_slots", [])

    def pick(entry, slot):
        target = data.get(entry["same"], {}) if "same" in entry else {}
        if isinstance(slot, str) and slot not in names:
            line = entry.get(slot) or target.get(slot)
            return list(line) if line else None
        index = names.index(slot) if isinstance(slot, str) else slot
        lines = entry.get("h") or target.get("h") or []
        return list(lines[index]) if index < len(lines) else None

    entries = [entry for locale, entry in data.items() if not locale.startswith("_") and isinstance(entry, dict)]
    for key in ("slot", "fallbackSlot"):
        slot = spec.get(key)
        if isinstance(slot, str) and slot not in names and not any(slot in entry for entry in entries):
            raise RenderError(f"{key} {slot!r} is neither in {spec['from']}'s _slots nor a key on any locale — check the slot name")

    out = {}
    for locale, entry in data.items():
        if locale.startswith("_") or not isinstance(entry, dict):
            continue
        line, fallback = pick(entry, spec["slot"]), False
        if line is None and "fallbackSlot" in spec:
            line, fallback = pick(entry, spec["fallbackSlot"]), True
        if line is None:
            continue
        out[locale] = {"verb": line[0], "descriptor": line[1], "ui": entry.get("ui"),
                       "rtl": bool(entry.get("rtl")), "fallback": fallback}
    return out


def _inline(cfg, variant):
    rtl = set(cfg.get("rtl", []))
    heads = variant["headlines"]
    out = {}
    for locale, value in heads.items():
        source = heads[value["same"]] if isinstance(value, dict) and "same" in value else value
        line = source["h"] if isinstance(source, dict) else source
        ui = ((value.get("ui") if isinstance(value, dict) else None)
              or (source.get("ui") if isinstance(source, dict) else None) or variant.get("ui"))
        out[locale] = {"verb": line[0], "descriptor": line[1], "ui": ui, "rtl": locale in rtl, "fallback": False}
    return out


def resolve_headlines(cfg, variant_name):
    variant = cfg["variants"][variant_name]
    heads = variant["headlines"]
    out = _from_file(cfg, heads) if "from" in heads else _inline(cfg, variant)
    if not out:
        if "from" in heads:
            slots = f"slot {heads.get('slot')!r}"
            if "fallbackSlot" in heads:
                slots += f" (fallbackSlot {heads['fallbackSlot']!r})"
            raise RenderError(f"variant '{variant_name}': {slots} matched no locale in {heads['from']} — check the slot name/index")
        raise RenderError(f"variant '{variant_name}' has no headlines")
    return out


# ---------------------------------------------------------------- text

def _font_spec(cfg, locale):
    fonts = cfg.get("fonts", {})
    return fonts.get(locale) or fonts.get(locale.split("-")[0]) or fonts.get("default")


def _font(cfg, locale, size, ImageFont):
    spec = _font_spec(cfg, locale)
    if not spec:
        # Pillow's built-in font loads with Layout.BASIC, which rejects `direction=`;
        # switch it to RAQM when available so right-to-left text can still be measured.
        font = ImageFont.load_default(size)
        if _pil()[4].check("raqm"):
            font = font.font_variant(layout_engine=ImageFont.Layout.RAQM)
        return font
    font = ImageFont.truetype(spec["path"], size, index=spec.get("index", 0))
    if spec.get("variation"):
        try:
            font.set_variation_by_name(spec["variation"])
        except Exception:
            try:
                font.set_variation_by_axes([700])
            except Exception:
                pass
    return font


def _width(draw, text, font, rtl):
    kwargs = {"direction": "rtl"} if rtl else {}
    left, _, right, _ = draw.textbbox((0, 0), text, font=font, **kwargs)
    return right - left


def _tokenize(text, per_char):
    if per_char:
        return [(ch, "") for ch in text.replace(ZWSP, "") if ch != " "] if " " not in text else \
               [(ch, "") for ch in text.replace(ZWSP, "")]
    units, joiner = [], ""
    for part in re.split(r"( |​)", text):
        if part == " ":
            joiner = " "
        elif part == ZWSP:
            joiner = ""
        elif part:
            units.append((part, joiner))
            joiner = ""
    return units


def _join(units):
    return "".join(joiner + unit for unit, joiner in units).lstrip(" ")


def _wrap(draw, text, font, max_w, rtl, per_char, max_lines):
    """Balanced wrap into ≤ max_lines lines of ≤ max_w; None if impossible."""
    units = _tokenize(text, per_char)
    if not units:
        return [text]
    total = _width(draw, _join(units), font, rtl)
    for k in range(1, max_lines + 1):
        for slack in (1.08, None):
            target = total / k
            lines, current, ok = [], [], True
            for unit in units:
                candidate = current + [unit]
                w = _width(draw, _join(candidate), font, rtl)
                over_target = slack is not None and w > target * slack and len(lines) < k - 1
                if current and (w > max_w or over_target):
                    lines.append(_join(current))
                    current = [unit]
                else:
                    current = candidate
                if _width(draw, _join(current), font, rtl) > max_w:
                    ok = False
                    break
            if current:
                lines.append(_join(current))
            if ok and len(lines) == k and all(_width(draw, line, font, rtl) <= max_w for line in lines) \
                    and not (per_char and k > 1 and any(len(line) < 3 for line in lines)):
                return lines
    return None


def _fit(cfg, draw, locale, text, max_w, spec, rtl, ImageFont):
    per_char = locale in set(cfg.get("noSpaceWrap", ["ja", "zh-Hans", "zh-Hant"]))
    size = spec["size"]
    while size >= spec["min"]:
        font = _font(cfg, locale, size, ImageFont)
        lines = _wrap(draw, text, font, max_w, rtl, per_char, spec["lines"])
        if lines is not None:
            return font, lines, size
        size -= spec["step"]
    raise RenderError(f"'{text}' does not fit in {spec['lines']} line(s) at ≥ {spec['min']}px")


# ---------------------------------------------------------------- devices

def _frame_geometry(shot_w, shot_h, frame_height):
    """(screen w, screen h, bezel, corner radius, scale) of a phone frame `frame_height` px tall overall."""
    bezel_ratio, radius_ratio = 30 / 1040, 150 / 1040
    screen_h = frame_height / (1 + 2 * bezel_ratio * shot_w / shot_h)
    scale = screen_h / shot_h
    sw, sh = round(shot_w * scale), round(screen_h)
    return sw, sh, round(sw * bezel_ratio), round(sw * radius_ratio), scale


def _shadow_metrics(frame_height):
    """(blur, drop, margin): the drop shadow's blur radius, offset, and how far it reaches past the frame."""
    blur = max(1, round(frame_height * 0.015))
    drop = round(frame_height * 0.012)
    return blur, drop, 4 * blur + drop


def _device(shot, frame_height, frame_colour, Image, ImageDraw):
    """Flat phone frame around a capture, `frame_height` px tall overall."""
    shot = shot.convert("RGB")
    sw, sh, bezel, radius, scale = _frame_geometry(shot.width, shot.height, frame_height)
    screen = shot.resize((sw, sh), Image.LANCZOS)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=radius, fill=255)
    fw, fh = sw + 2 * bezel, sh + 2 * bezel
    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((0, 0, fw - 1, fh - 1), radius=radius + bezel, fill=frame_colour + (255,))
    frame.paste(screen, (bezel, bezel), mask)
    island_w, island_h = round(390 * scale), round(112 * scale)
    ix, iy = bezel + (sw - island_w) // 2, bezel + round(24 * scale)
    draw.rounded_rectangle((ix, iy, ix + island_w, iy + island_h), radius=max(1, island_h // 2), fill=(0, 0, 0, 255))
    return frame


# ---------------------------------------------------------------- composition

def _brand(cfg):
    brand = cfg.get("brand", {})
    return (_hex(brand.get("background", "#000000")), _hex(brand.get("text", "#FFFFFF")),
            _hex(brand.get("frame", "#1C1C1E")))


def _types(defaults, overrides):
    return {key: {**defaults[key], **(overrides or {}).get(key, {})} for key in defaults}


def _paste_devices(image, frames, positions, frame_h, Image, ImageDraw, ImageFilter):
    """Drop shadows, then the frames, at `positions` [(frame index, x, y)]."""
    blur, drop, _ = _shadow_metrics(frame_h)
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    for index, x, y in positions:
        frame = frames[index]
        shadow_draw.rounded_rectangle((x + blur, y + drop, x + frame.width - blur, y + frame.height + drop),
                                      radius=round(frame.width * 0.17), fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    image.paste(shadow, (0, 0), shadow)
    for index, x, y in positions:
        image.paste(frames[index], (x, y), frames[index])


def _headline(cfg, draw, locale, head, types, box, text_w, align, where, colour):
    """Fit the verb and descriptor into `text_w`, centre the block vertically in `box`,
    and lay out every line (`align` "leading": flush to the reading-start edge;
    "centre": centred). Each line's ink is checked against `box`, so an oversized
    type override fails this locale instead of drawing outside it."""
    ImageFont = _pil()[3]
    x0, y0, x1, y1 = box
    rtl = head["rtl"]
    verb_font, verb_lines, verb_size = _fit(cfg, draw, locale, head["verb"], text_w, types["verb"], rtl, ImageFont)
    desc_font, desc_lines, desc_size = _fit(cfg, draw, locale, head["descriptor"], text_w, types["descriptor"], rtl, ImageFont)
    verb_lead = round(verb_size * types["verb"]["leading"])
    desc_lead = round(desc_size * types["descriptor"]["leading"])
    gap = round(desc_size * 0.35)
    block_h = verb_lead * len(verb_lines) + gap + desc_lead * len(desc_lines)
    y = y0 + (y1 - y0 - block_h) / 2
    kwargs = {"direction": "rtl"} if rtl else {}
    placed = []
    for lines, font, lead in ((verb_lines, verb_font, verb_lead), (desc_lines, desc_font, desc_lead)):
        for line in lines:
            left, top_offset, right, bottom = draw.textbbox((0, 0), line, font=font, **kwargs)
            w = right - left
            if align == "centre":
                tx = x0 + round((x1 - x0 - w) / 2)
            else:
                tx = x0 if not rtl else x1 - w
            ink = (tx, y, tx + w, y + bottom - top_offset)
            if ink[0] < x0 or ink[1] < y0 or ink[2] > x1 or ink[3] > y1:
                raise RenderError(f"{locale}: headline block ({block_h}px tall) does not fit {where} "
                                  f"({y1 - y0}px) — lower the type size or line count")
            placed.append(((tx - left, y - top_offset), line, font))
            y += lead
        y += gap
    for origin, line, font in placed:
        draw.text(origin, line, font=font, fill=colour, **kwargs)
    return {"verb_px": verb_size, "verb_lines": len(verb_lines), "descriptor_px": desc_size,
            "descriptor_lines": len(desc_lines),
            "tight": verb_size < types["tight"]["verb"] or desc_size < types["tight"]["descriptor"]}


def _compose(cfg, variant, locale, head, captures):
    Image, ImageDraw, ImageFilter, ImageFont, _ = _pil()
    canvas = tuple(cfg.get("canvas", {}).get(k) or v for k, v in zip(("width", "height"), CANVAS))
    background, text_colour, frame_colour = _brand(cfg)
    types = _types(DEFAULT_TYPE, cfg.get("type", {}))
    x0, y0, x1, y1 = safe_box(canvas[0], canvas[1], cfg.get("safeInset", 0.03))
    box_w, box_h = x1 - x0, y1 - y0
    rtl = head["rtl"]

    image = Image.new("RGB", canvas, background)
    draw = ImageDraw.Draw(image)

    # Devices: trailing side. Height budget leaves room for the second device's offset and the shadow.
    count = len(captures)
    offset = 0.06
    frame_h = box_h * 0.86 / (1 + offset * (count - 1))
    frames = [_device(c, frame_h, frame_colour, Image, ImageDraw) for c in captures]
    margin = _shadow_metrics(frame_h)[2]
    column_w = box_w * 0.52
    group_w = sum(f.width for f in frames) - round(frames[0].width * 0.04) * (count - 1)
    if group_w + 2 * margin > column_w:
        raise RenderError(f"{locale}: devices need {group_w + 2 * margin}px, column has {column_w:.0f}px — use 1 device or narrower captures")
    column_x0 = x1 - column_w if not rtl else x0
    start_x = column_x0 + (column_w - group_w) / 2
    top = y0 + (box_h - frame_h * (1 + offset * (count - 1))) / 2
    positions, x = [], start_x
    order = list(range(count)) if not rtl else list(reversed(range(count)))
    for rank, index in enumerate(order):
        positions.append((index, round(x), round(top + frame_h * offset * rank)))
        x += frames[index].width - round(frames[index].width * 0.04)
    _paste_devices(image, frames, positions, frame_h, Image, ImageDraw, ImageFilter)

    # Headline: leading side.
    text = _headline(cfg, draw, locale, head, types, (x0, y0, x1, y1), box_w * 0.44, "leading", "the safe box", text_colour)
    report = {"locale": locale, **{k: text[k] for k in ("verb_px", "verb_lines", "descriptor_px", "descriptor_lines")},
              "fallback": head["fallback"], "device_width_pct": round(100 * frames[0].width / canvas[0], 1),
              "tight": text["tight"]}
    return image, report


def header_settings(cfg):
    """The resolved `"header"` block: None when disabled, else canvas, zone, band, device top and type."""
    block = cfg.get("header") or {}
    if block.get("enabled", True) is False:
        return None
    canvas = tuple(block.get("canvas", {}).get(k) or v for k, v in zip(("width", "height"), HEADER_CANVAS))
    return {"canvas": canvas, "zone": tuple(block.get("zone") or HEADER_ZONE),
            "band": tuple(block.get("centreBand") or HEADER_BAND),
            "device_top": block.get("deviceTop", HEADER_DEVICE_TOP),
            "type": _types(DEFAULT_HEADER_TYPE, block.get("type", {}))}


def _header_device_height(captures, side_w, max_h):
    """Tallest frame (≤ max_h) whose width plus shadow on both sides fits `side_w`; None if none fits."""
    frame_h = max_h
    while frame_h > 0:
        margin = _shadow_metrics(frame_h)[2]
        widths = []
        for shot in captures:
            sw, _, bezel, _, _ = _frame_geometry(shot.width, shot.height, frame_h)
            widths.append(sw + 2 * bezel)
        if max(widths) + 2 * margin <= side_w:
            return frame_h
        frame_h -= max(1, round(frame_h * 0.01))
    return None


def _compose_header(cfg, settings, locale, head, captures):
    """The product-page header file: headline centred in the zone, one phone each side outside the band."""
    Image, ImageDraw, ImageFilter, _, _ = _pil()
    canvas = settings["canvas"]
    zx0, zy0, zx1, zy1 = settings["zone"]
    band_x0, band_x1 = settings["band"]
    background, text_colour, frame_colour = _brand(cfg)
    image = Image.new("RGB", canvas, background)
    draw = ImageDraw.Draw(image)

    # Devices: left side shows capture[0], right side capture[1] (else capture[0]); mirrored for RTL.
    sides = [captures[0], captures[1] if len(captures) > 1 else captures[0]]
    if head["rtl"]:
        sides.reverse()
    side_w = min(band_x0, canvas[0] - band_x1)
    top_limit = settings["device_top"]
    frame_h = _header_device_height(sides, side_w, canvas[1] - top_limit) if side_w > 0 else None
    devices = 0
    if frame_h is not None and frame_h >= canvas[1] * HEADER_MIN_DEVICE:
        frames = [_device(shot, frame_h, frame_colour, Image, ImageDraw) for shot in sides]
        top = max(top_limit, round((zy0 + zy1) / 2 - frame_h / 2))
        positions = [(0, round((band_x0 - frames[0].width) / 2), top),
                     (1, round(band_x1 + (canvas[0] - band_x1 - frames[1].width) / 2), top)]
        margin = _shadow_metrics(frame_h)[2]
        clear = all(x - margin >= 0 and x + frames[i].width + margin <= canvas[0]
                    and (x + frames[i].width + margin <= zx0 or x - margin >= zx1)
                    and (x + frames[i].width + margin <= band_x0 or x - margin >= band_x1)
                    for i, x, _ in positions)
        if clear:
            _paste_devices(image, frames, positions, frame_h, Image, ImageDraw, ImageFilter)
            devices = len(positions)

    text = _headline(cfg, draw, locale, head, settings["type"], (zx0, zy0, zx1, zy1), zx1 - zx0, "centre", "the header zone", text_colour)
    return image, {**text, "devices": devices}


def render_variant(cfg, variant_name, out_dir, locales=None, lint=True, strict_lint=False):
    Image, _, _, _, features = _pil()
    if variant_name not in cfg.get("variants", {}):
        raise RenderError(f"no variant '{variant_name}' in assets.json")
    variant = cfg["variants"][variant_name]
    if not 1 <= len(variant.get("captures", [])) <= 2:
        raise RenderError(f"variant '{variant_name}': use 1 or 2 captures (3+ is illegible at search-row size)")
    heads = resolve_headlines(cfg, variant_name)
    wanted = list(locales) if locales else sorted(heads)
    unknown = [loc for loc in wanted if loc not in heads]
    if unknown:
        raise RenderError(f"variant '{variant_name}' has no headline for: {', '.join(unknown)}")
    if any(heads[loc]["rtl"] for loc in wanted) and not features.check("raqm"):
        raise RenderError("right-to-left locales need Pillow built with libraqm (brew install libraqm; pip install --force-reinstall Pillow)")

    out = Path(out_dir) / variant_name
    out.mkdir(parents=True, exist_ok=True)
    header_dir = out / creative.HEADER_DIR
    header = header_settings(cfg)
    root = cfg["_root"] / variant.get("capturesRoot", ".")
    result = {"written": [], "header_written": [], "failed": {}, "report": [], "unlinted": []}
    for locale in wanted:
        head = heads[locale]
        path = out / f"{locale}.png"
        header_path = header_dir / f"{locale}.png"

        def fail(reason):
            # Never leave a previous render behind: it would be picked up and uploaded as current.
            # The locale fails whole, so its header file goes too.
            result["failed"][locale] = reason
            path.unlink(missing_ok=True)
            header_path.unlink(missing_ok=True)

        if lint:
            if not creative.linted(locale):
                result["unlinted"].append(locale)
                if strict_lint:
                    fail("no lint word list for this language (--strict-lint)")
                    continue
            hits = creative.lint(f"{head['verb']} {head['descriptor']}", locale)
            if hits:
                fail("; ".join(hits))
                continue
        ui = head.get("ui") or variant.get("ui") or "en"
        try:
            captures = [Image.open(root / c.replace("{ui}", ui)) for c in variant["captures"]]
            image, report = _compose(cfg, variant, locale, head, captures)
        except (RenderError, OSError) as error:
            fail(str(error))
            continue
        header_image, report["header"] = None, None
        if header:
            try:
                header_image, report["header"] = _compose_header(cfg, header, locale, head, captures)
            except (RenderError, OSError) as error:
                fail(f"header: {error}")
                continue
        image.save(path, optimize=True)
        result["written"].append(path)
        if header_image is not None:
            header_dir.mkdir(exist_ok=True)
            header_image.save(header_path, optimize=True)
            result["header_written"].append(header_path)
        else:
            # Header output disabled: a header file from an earlier render would still be placed.
            header_path.unlink(missing_ok=True)
        result["report"].append(report)
    if result["written"]:
        _contact_sheet(result["written"], Path(out_dir) / "_contact" / f"{variant_name}.png", Image)
    if result["header_written"]:
        _contact_sheet(result["header_written"], Path(out_dir) / "_contact" / f"{variant_name}-header.png", Image)
    return result


def _contact_sheet(paths, target, Image):
    thumb_w, columns = 1050, 4
    first = Image.open(paths[0])
    thumb_h = round(thumb_w * first.height / first.width)
    thumbs = [Image.open(p).convert("RGB").resize((thumb_w, thumb_h)) for p in paths]
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, rows * thumb_h), (255, 255, 255))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % columns) * thumb_w, (index // columns) * thumb_h))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, optimize=True)
