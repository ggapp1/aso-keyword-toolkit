"""Universal creative files (product page header + search results).

Layout: DIR/<asc-locale>.png — the shape `asokit assets render` writes. Names
starting with `_` or `.` are ignored (render writes contact sheets to
`_contact/`). PNG facts are read from the chunk headers, no imaging library.
"""
import json
import re
import struct
from functools import lru_cache
from importlib import resources
from pathlib import Path

UNIVERSAL = (5244, 2950)
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def plan_from_directory(directory):
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"{directory}: not a directory")
    return {
        path.stem: path
        for path in sorted(root.iterdir())
        if path.is_file() and path.suffix.lower() == ".png" and not path.name.startswith(("_", "."))
    }


def png_info(source):
    data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    if data[:8] != SIGNATURE or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    width, height, bit_depth, colour_type = struct.unpack(">IIBB", data[16:26])
    has_trns, offset = False, 8
    while offset + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        if kind == b"tRNS":
            has_trns = True
        if kind in (b"IDAT", b"IEND"):
            break
        offset += 12 + length
    return {"width": width, "height": height, "bit_depth": bit_depth, "colour_type": colour_type, "has_trns": has_trns}


def check(plan, expected=UNIVERSAL, max_bytes=None):
    """Problems App Store Connect would reject: size, alpha, depth, file size."""
    problems = []
    for locale, path in sorted(plan.items()):
        try:
            info = png_info(path)
        except (OSError, ValueError) as error:
            problems.append(f"{locale}: {Path(path).name}: {error}")
            continue
        if (info["width"], info["height"]) != tuple(expected):
            problems.append(f"{locale}: {Path(path).name} is {info['width']}×{info['height']}, expected {expected[0]}×{expected[1]}")
        if info["bit_depth"] != 8:
            problems.append(f"{locale}: {Path(path).name} is {info['bit_depth']}-bit, expected 8-bit")
        if info["colour_type"] in (0, 4):
            problems.append(f"{locale}: {Path(path).name} is grayscale, expected RGB")
        if info["colour_type"] == 6 or (info["colour_type"] == 3 and info["has_trns"]):
            problems.append(f"{locale}: {Path(path).name} has an alpha channel/transparency — App Store creatives can't")
        if max_bytes and Path(path).stat().st_size > max_bytes:
            problems.append(f"{locale}: {Path(path).name} exceeds {max_bytes} bytes")
    return problems


@lru_cache(maxsize=1)
def _rules():
    text = resources.files("asokit").joinpath("data/creative_lint.json").read_text(encoding="utf-8")
    return json.loads(text)


def _language(locale):
    return locale.split("-")[0].lower()


def linted(locale):
    return _language(locale) in _rules()["words"]


def _phrase_regex(phrase):
    return re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE)


def lint(text, locale):
    """Rejection-rule hits in `text` for `locale`; [] when clean."""
    rules = _rules()
    problems = []
    for category, patterns in rules["patterns"].items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                problems.append(f"{category}: '{text}' matches /{pattern}/")
    for category, phrases in rules["words"].get(_language(locale), {}).items():
        for phrase in phrases:
            if _phrase_regex(phrase).search(text):
                problems.append(f"{category}: '{text}' contains '{phrase}'")
    return problems
