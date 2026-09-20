"""App Store screenshot plans: a directory of per-locale PNGs → what to upload.

Layout: DIR/<asc-locale>/*.png, sorted by file name = store order. Only PNG
dimensions are checked here (read from the IHDR chunk, no imaging library);
App Store Connect validates everything else at upload time.
"""
import struct
from pathlib import Path

# Pixel sizes App Store Connect accepts per display family (portrait first).
DISPLAY_SIZES = {
    "APP_IPHONE_67": {(1290, 2796), (1320, 2868), (1284, 2778)},
    "APP_IPHONE_65": {(1242, 2688), (1284, 2778)},
    "APP_IPHONE_61": {(1170, 2532), (1179, 2556), (1206, 2622)},
    "APP_IPAD_PRO_3GEN_129": {(2048, 2732), (2064, 2752)},
    "APP_IPAD_PRO_129": {(2048, 2732)},
    "APP_WATCH_SERIES_10": {(416, 496), (410, 502)},
    "APP_WATCH_ULTRA": {(410, 502), (422, 514)},
}
MAX_PER_SET = 10


def png_size(path):
    """(width, height) from the PNG header; ValueError if not a PNG."""
    with open(path, "rb") as handle:
        head = handle.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"{path}: not a PNG")
    return struct.unpack(">II", head[16:24])


def plan_from_directory(directory, display_type):
    """{locale: [Path, ...]} for every locale folder, files in name order."""
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"{directory}: not a directory")
    plan = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".png")
        if files:
            plan[folder.name] = files
    return {locale: {display_type: files} for locale, files in plan.items()}


def check(plan):
    """Problems that would fail at upload: too many shots, wrong pixel size."""
    problems = []
    for locale, families in sorted(plan.items()):
        for display, files in families.items():
            allowed = DISPLAY_SIZES.get(display)
            if allowed is None:
                problems.append(f"{locale}: unknown display type {display}")
                continue
            if len(files) > MAX_PER_SET:
                problems.append(f"{locale} {display}: {len(files)} screenshots, App Store Connect takes at most {MAX_PER_SET}")
            for file in files:
                if isinstance(file, tuple):
                    continue  # (name, bytes) mirrored from a live set — already accepted by Apple
                try:
                    size = png_size(file)
                except (OSError, ValueError) as error:
                    problems.append(str(error)); continue
                if size not in allowed and (size[1], size[0]) not in allowed:
                    problems.append(f"{locale} {display}: {file.name} is {size[0]}×{size[1]}, expected one of {sorted(allowed)}")
    return problems
