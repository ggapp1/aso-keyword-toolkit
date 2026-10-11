"""Render the universal App Store creative (header + search results, 5244×2950).

Driven entirely by the app's `assets.json` (see the spec / README): brand
colours, per-locale fonts and type sizes, and variants — each a headline
source plus 1–2 app captures. No app-specific code lives here.

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
    "verb": {"size": 520, "min": 300, "step": 10, "lines": 1, "leading": 1.02},
    "descriptor": {"size": 250, "min": 170, "step": 6, "lines": 2, "leading": 1.12},
    "tight": {"verb": 340, "descriptor": 190},
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
    x1, y1 = x0 + math.ceil(w), y0 + math.ceil(h)
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
    return _from_file(cfg, heads) if "from" in heads else _inline(cfg, variant)


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

def _device(shot, frame_height, frame_colour, Image, ImageDraw):
    """Flat phone frame around a capture, `frame_height` px tall overall."""
    shot = shot.convert("RGB")
    bezel_ratio, radius_ratio = 30 / 1040, 150 / 1040
    screen_h = frame_height / (1 + 2 * bezel_ratio * shot.width / shot.height)
    scale = screen_h / shot.height
    sw, sh = round(shot.width * scale), round(screen_h)
    bezel, radius = round(sw * bezel_ratio), round(sw * radius_ratio)
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

def _compose(cfg, variant, locale, head, captures):
    Image, ImageDraw, ImageFilter, ImageFont, _ = _pil()
    canvas = tuple(cfg.get("canvas", {}).get(k) or v for k, v in zip(("width", "height"), CANVAS))
    brand = cfg.get("brand", {})
    background = _hex(brand.get("background", "#000000"))
    text_colour = _hex(brand.get("text", "#FFFFFF"))
    frame_colour = _hex(brand.get("frame", "#1C1C1E"))
    types = {**DEFAULT_TYPE, **cfg.get("type", {})}
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
    blur = max(1, round(frame_h * 0.015))
    drop = round(frame_h * 0.012)
    margin = 4 * blur + drop
    column_w = box_w * 0.52
    group_w = sum(f.width for f in frames) - round(frames[0].width * 0.04) * (count - 1)
    if group_w + 2 * margin > column_w:
        raise RenderError(f"{locale}: devices need {group_w + 2 * margin}px, column has {column_w:.0f}px — lower type or use 1 device")
    column_x0 = x1 - column_w if not rtl else x0
    start_x = column_x0 + (column_w - group_w) / 2
    top = y0 + (box_h - frame_h * (1 + offset * (count - 1))) / 2
    shadow = Image.new("RGBA", canvas, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    positions, x = [], start_x
    order = list(range(count)) if not rtl else list(reversed(range(count)))
    for rank, index in enumerate(order):
        frame = frames[index]
        y = top + frame_h * offset * rank
        positions.append((index, round(x), round(y)))
        shadow_draw.rounded_rectangle((round(x) + blur, round(y) + drop, round(x) + frame.width - blur, round(y) + frame.height + drop),
                                      radius=round(frame.width * 0.17), fill=(0, 0, 0, 110))
        x += frame.width - round(frame.width * 0.04)
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    image.paste(shadow, (0, 0), shadow)
    for index, px, py in positions:
        image.paste(frames[index], (px, py), frames[index])

    # Headline: leading side.
    text_w = box_w * 0.44
    verb_font, verb_lines, verb_size = _fit(cfg, draw, locale, head["verb"], text_w, types["verb"], rtl, ImageFont)
    desc_font, desc_lines, desc_size = _fit(cfg, draw, locale, head["descriptor"], text_w, types["descriptor"], rtl, ImageFont)
    verb_lead = round(verb_size * types["verb"]["leading"])
    desc_lead = round(desc_size * types["descriptor"]["leading"])
    gap = round(desc_size * 0.35)
    block_h = verb_lead * len(verb_lines) + gap + desc_lead * len(desc_lines)
    y = y0 + (box_h - block_h) / 2
    kwargs = {"direction": "rtl"} if rtl else {}
    for lines, font, lead in ((verb_lines, verb_font, verb_lead), (desc_lines, desc_font, desc_lead)):
        for line in lines:
            w = _width(draw, line, font, rtl)
            tx = x0 if not rtl else x1 - w
            left, top_offset, _, _ = draw.textbbox((0, 0), line, font=font, **kwargs)
            draw.text((tx - left, y - top_offset), line, font=font, fill=text_colour, **kwargs)
            y += lead
        y += gap
    report = {"locale": locale, "verb_px": verb_size, "verb_lines": len(verb_lines), "descriptor_px": desc_size,
              "descriptor_lines": len(desc_lines), "fallback": head["fallback"],
              "device_width_pct": round(100 * frames[0].width / canvas[0], 1),
              "tight": verb_size < types["tight"]["verb"] or desc_size < types["tight"]["descriptor"]}
    return image, report


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
    root = cfg["_root"] / variant.get("capturesRoot", ".")
    result = {"written": [], "failed": {}, "report": [], "unlinted": []}
    for locale in wanted:
        head = heads[locale]
        if lint:
            if not creative.linted(locale):
                result["unlinted"].append(locale)
                if strict_lint:
                    result["failed"][locale] = "no lint word list for this language (--strict-lint)"
                    continue
            hits = creative.lint(f"{head['verb']} {head['descriptor']}", locale)
            if hits:
                result["failed"][locale] = "; ".join(hits)
                continue
        ui = head.get("ui") or variant.get("ui") or "en"
        try:
            captures = [Image.open(root / c.replace("{ui}", ui)) for c in variant["captures"]]
            image, report = _compose(cfg, variant, locale, head, captures)
        except (RenderError, OSError) as error:
            result["failed"][locale] = str(error)
            continue
        path = out / f"{locale}.png"
        image.save(path, optimize=True)
        result["written"].append(path)
        result["report"].append(report)
    if result["written"]:
        _contact_sheet(result["written"], Path(out_dir) / "_contact" / f"{variant_name}.png", Image)
    return result


def _contact_sheet(paths, target, Image):
    thumb_w, columns = 1050, 4
    thumbs = [Image.open(p).convert("RGB").resize((thumb_w, round(thumb_w * 2950 / 5244))) for p in paths]
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, rows * thumbs[0].height), (255, 255, 255))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % columns) * thumb_w, (index // columns) * thumb.height))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, optimize=True)
