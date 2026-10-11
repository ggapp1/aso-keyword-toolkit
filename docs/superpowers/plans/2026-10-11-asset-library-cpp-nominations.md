# Asset Library, Creative Assets, Custom Product Pages and Nominations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add App Asset Library support to `asokit`: render localized universal creatives, upload/place them on the default page and custom product pages, manage CPPs (keywords, media, review, visibility) from `cpp.json`, file featuring nominations from `nominations.json`, and offer a library-based `screenshots push` engine — then wire MoodSync up as the first consumer.

**Architecture:** Pure modules (`creative`, `cpp`, `nominations` planning) validate and plan; network executors (`library`, `cpp_apply`, `review`, `nominations` push) call `asc.call` through the module attribute so the fake-connect tests intercept them. Every write path runs in two phases — prepare (validate, upload/reuse, wait for processing) then apply (placement/CPP writes) — is dry-run unless `--apply`, and appends to a local ledger when applied.

**Tech Stack:** Python ≥ 3.9 stdlib (`urllib`, `json`, `hashlib`, `struct`), `pyjwt` (existing `connect` extra), Pillow ≥ 10.1 (new optional `render` extra), `unittest` run via `python3.13 -m pytest`.

**Spec:** `docs/superpowers/specs/2026-10-11-asset-library-cpp-nominations-design.md` (rev. 2, approved 2026-10-11). Read it before starting any task.

**Repos:**
- `asokit`: `/Users/ggapp/Projects/tools/aso-keyword-toolkit` (Tasks 1–17). Installed in editable mode for `/Users/ggapp/miniconda3/bin/python3.13`; run tests with `python3.13 -m pytest -q` from the repo root (baseline: 195 passed).
- MoodSync: `/Users/ggapp/Projects/mobileapps/moodsync` (Tasks 18–19).
- Commit as the configured user (`ggapp1 <gustavo.germano1@gmail.com>`). **Never add `Co-Authored-By` or any attribution trailer.** Never push.

## Global Constraints

- Core `dependencies = []` stays empty; Pillow only via extra `render = ["Pillow>=10.1"]`.
- All network code calls `asc.call`, `asc.call_all`, `asc._raw` as **module attributes** (`from . import asc` then `asc.call(...)`), never `from .asc import call`.
- Every App Store Connect write is a dry run unless `--apply`. `cpp submit` and `cpp publish` require `--pages`; `nominations push --submit` requires `--name` and `--apply`.
- Never issue `DELETE` on an asset (`/appAssetLibraryImages/...`) or a page (`/appCustomProductPages/...`).
- Placement-editable App Store version states: `PREPARE_FOR_SUBMISSION`, `DEVELOPER_REJECTED`, `REJECTED`, `METADATA_REJECTED`, `INVALID_BINARY` (not `WAITING_FOR_REVIEW`).
- CPP version states: editable `PREPARE_FOR_SUBMISSION`, `REJECTED`, `READY_FOR_REVIEW`; locked `WAITING_FOR_REVIEW`, `IN_REVIEW`; live `ACCEPTED`, `APPROVED`; ignored `REPLACED_WITH_NEW_VERSION`.
- Universal creative: exactly **5244×2950**, PNG, 8-bit RGB (colour type 2), no alpha.
- Upload `referenceName` = `"asokit:" + sha256(bytes)[:16] + ":" + file_name[:40]`.
- Reuse states: `UPLOAD_COMPLETE`, `COMPLETE`, `PREPARE_FOR_SUBMISSION`, `READY_FOR_REVIEW`, `WAITING_FOR_REVIEW`, `IN_REVIEW`, `ACCEPTED`, `APPROVED`. Ignore `AWAITING_UPLOAD`, `FAILED`, `ARCHIVED`. Stop on `REJECTED`.
- Keyword ownership: within a locale a keyword belongs to at most one page (file pages + live pages). Empty keyword sets allowed. Protected keywords need `--allow-protected`.
- `same` in `cpp.json` copies `promotionalText`, `screenshots`, `creative` — never `keywords`.
- New CPPs are created hidden; only `cpp publish` changes `visible`.
- `cpp.json` page `name` ≤ 30 chars; `promotionalText` ≤ 170; ≤ 70 pages (live + new). Nomination `name` ≤ 60, `description` ≤ 1000, `publishStartDate` ≥ today + 14 days unless `--force`.
- Nomination dates sent as `YYYY-MM-DDT00:00:00Z`; app ids sent as strings; `GET /v1/nominations` always carries `filter[state]`.
- `screenshots push`/`status` default engine stays `sets`; `--engine library` is opt-in.
- Rate limit: below 10 % of `user-hour-lim` remaining, sleep 30 s before the next request.
- Render safe box: intersection of the centred 21:9 and 3:2 crops of the canvas, floor origin, then inset 3 % per side; text, devices and shadows stay inside it. Max 2 devices per creative.

## Review Focus

1. **A run aborted mid-upload, then re-run** — the orphaned `AWAITING_UPLOAD` reservation must not be reused and the re-run must not hang; owned by Task 5 (`test_awaiting_upload_is_not_reused`).
2. **`cpp push --locales en-GB` on a page that also has en-US live** — nothing outside the named locale may be deleted or changed; owned by Task 10 (`test_locales_scope_never_deletes`).
3. **An open draft review submission that already holds the app version** — `cpp submit`/`assets submit` must stop, never submit it; owned by Task 8 (`tests/test_review.py::test_foreign_item_in_draft_stops`).
4. **Re-running `cpp push` on an approved page with an unchanged file** — zero writes, no new version; owned by Task 10 (`test_live_unchanged_page_plans_nothing`).
5. **A headline too long for the canvas in one locale** — that locale fails loudly, other locales still render, exit code non-zero; owned by Task 7 (`test_overlong_headline_fails_only_that_locale`).

## File Structure

`asokit` (`/Users/ggapp/Projects/tools/aso-keyword-toolkit`):

| File | Status | Responsibility |
|---|---|---|
| `asokit/asc.py` | modify | `Bearer` (self-refreshing JWT), rate-limit parsing/throttle |
| `asokit/ledger.py` | create | append-only `asokit-ledger.jsonl` |
| `asokit/creative.py` | create | creative dir plan, PNG checks, text lint |
| `asokit/data/creative_lint.json` | create | lint patterns and per-language words |
| `asokit/library.py` | create | `Catalog`, upload/reuse, wait, placements, `replace_group`, `sync_groups`, PPO guard |
| `asokit/review.py` | create | guarded review submissions |
| `asokit/render.py` | create | universal creative renderer |
| `asokit/cpp.py` | create | `cpp.json` load/expand/check (pure), plan, ads rows |
| `asokit/cpp_apply.py` | create | CPP snapshot, online check, push executor, publish, submit |
| `asokit/nominations.py` | create | nominations load/check/plan/push |
| `asokit/screenshots.py` | modify | legacy display → display-class map |
| `asokit/cli.py` | modify | `assets`, `cpp`, `nominations` commands; `screenshots --engine` |
| `pyproject.toml` | modify | `render` extra, package data, version 0.5.0 |
| `README.md` | modify | document new commands |
| `tests/fakes.py` | create | `REFDATA` fixture, `FakeConnect` (library + versions + review + CPP + nominations routes), `install()` |
| `tests/test_asc_transport.py`, `test_ledger.py`, `test_creative.py`, `test_library.py`, `test_review.py`, `test_render.py`, `test_cpp.py`, `test_cpp_apply.py`, `test_nominations.py`, `test_screenshots_library.py` | create | unit tests |
| `tests/test_cli.py` | modify | wiring tests |

MoodSync (`/Users/ggapp/Projects/mobileapps/moodsync`):

| File | Status | Responsibility |
|---|---|---|
| `assets.json` | create | render config (default + 4 variants) |
| `screenshots/store/headlines.json` | modify | add `"hero"` line per locale |
| `cpp.json` | create | 4 pages, en-US/GB/CA/AU |
| `nominations.json` | create | one draft |
| `.gitignore` | modify | `assets-out/` |

---
## Phase A — Asset Library and creatives

### Task 1: Self-refreshing token and rate-limit throttle in `asc.py`

**Files:**
- Modify: `asokit/asc.py` (add after `token()`; modify `_request` and `call`)
- Test: `tests/test_asc_transport.py`

**Interfaces:**
- Produces: `asc.Bearer(mint=None, lifetime=1200)` — `str(bearer)` returns a valid JWT, re-minting when < 180 s remain. `asc.RATE` dict (`limit`, `remaining`), `asc._note_rate(header)`, `asc._throttle()`, constants `RATE_FLOOR = 0.10`, `RATE_PAUSE = 30`.
- Every later network function accepts either a plain string bearer (tests) or an `asc.Bearer`; `_request` already formats with `f"Bearer {bearer}"`, which calls `str()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_asc_transport.py
import unittest
from unittest import mock

from asokit import asc


class BearerTests(unittest.TestCase):
    def test_mints_once_then_reuses_until_near_expiry(self):
        minted = []
        bearer = asc.Bearer(mint=lambda: minted.append(1) or f"jwt{len(minted)}", lifetime=1200)
        with mock.patch("asokit.asc.time.time", return_value=1000):
            self.assertEqual(str(bearer), "jwt1")
            self.assertEqual(str(bearer), "jwt1")
        with mock.patch("asokit.asc.time.time", return_value=1000 + 1200 - 179):
            self.assertEqual(str(bearer), "jwt2")
        self.assertEqual(len(minted), 2)

    def test_formats_into_authorization_header(self):
        bearer = asc.Bearer(mint=lambda: "abc")
        self.assertEqual(f"Bearer {bearer}", "Bearer abc")


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        asc.RATE.clear()
        self.addCleanup(asc.RATE.clear)

    def test_parses_header(self):
        asc._note_rate("user-hour-lim:3500;user-hour-rem:3120;")
        self.assertEqual(asc.RATE, {"limit": 3500, "remaining": 3120})

    def test_ignores_malformed_header(self):
        asc._note_rate("garbage")
        asc._note_rate(None)
        self.assertEqual(asc.RATE, {})

    def test_throttle_sleeps_only_below_floor(self):
        with mock.patch("asokit.asc.time.sleep") as sleep:
            asc._note_rate("user-hour-lim:3500;user-hour-rem:400;")
            asc._throttle()
            sleep.assert_not_called()
            asc._note_rate("user-hour-lim:3500;user-hour-rem:349;")
            asc._throttle()
            sleep.assert_called_once_with(asc.RATE_PAUSE)

    def test_call_throttles_before_each_request(self):
        asc._note_rate("user-hour-lim:100;user-hour-rem:1;")
        with mock.patch("asokit.asc.time.sleep") as sleep, \
             mock.patch("asokit.asc._request", return_value={"data": []}):
            asc.call("GET", "/apps/1", "t")
        sleep.assert_called_once_with(asc.RATE_PAUSE)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.13 -m pytest tests/test_asc_transport.py -q`
Expected: FAIL — `AttributeError: module 'asokit.asc' has no attribute 'Bearer'`

- [ ] **Step 3: Implement**

In `asokit/asc.py`, directly after the `token()` function, add:

```python
class Bearer:
    """A JWT that re-mints itself before it expires.

    Long pushes (39 locales of uploads plus processing waits) outlive the
    20-minute token. Every request formats the bearer with `f"Bearer {b}"`,
    which calls `__str__`, so passing a `Bearer` anywhere a token string is
    accepted keeps the run authenticated without threading re-mint calls
    through every loop. Tests keep passing plain strings.
    """

    REFRESH_MARGIN = 180

    def __init__(self, mint=None, lifetime=20 * 60):
        self._mint = mint or token
        self._lifetime = lifetime
        self._value = None
        self._expires = 0.0

    def __str__(self):
        now = time.time()
        if self._value is None or now >= self._expires - self.REFRESH_MARGIN:
            self._value = self._mint()
            self._expires = now + self._lifetime
        return self._value


# Apple reports the rolling hourly budget on every response:
#   X-Rate-Limit: user-hour-lim:3500;user-hour-rem:3120;
RATE = {}
RATE_FLOOR = 0.10
RATE_PAUSE = 30


def _note_rate(header):
    fields = dict(part.split(":", 1) for part in (header or "").split(";") if ":" in part)
    try:
        limit, remaining = int(fields["user-hour-lim"]), int(fields["user-hour-rem"])
    except (KeyError, ValueError):
        return
    RATE["limit"], RATE["remaining"] = limit, remaining


def _throttle():
    """Pause when the hourly budget is nearly spent, instead of hitting 429s."""
    limit, remaining = RATE.get("limit"), RATE.get("remaining")
    if limit and remaining is not None and remaining < limit * RATE_FLOOR:
        time.sleep(RATE_PAUSE)
```

In `_request`, record the header inside the `with` block:

```python
    with urllib.request.urlopen(request, timeout=30) as response:
        _note_rate(response.headers.get("X-Rate-Limit"))
        raw = response.read().decode()
        return json.loads(raw) if raw else {}
```

In `call`, throttle at the top of each attempt:

```python
    for attempt in range(MAX_ATTEMPTS):
        _throttle()
        try:
            return _request(method, path, bearer, body)
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest -q`
Expected: all pass (195 existing + 6 new).

- [ ] **Step 5: Commit**

```bash
git add asokit/asc.py tests/test_asc_transport.py
git commit -m "feat(asc): self-refreshing Bearer token and rate-limit throttle"
```

---

### Task 2: Ledger

**Files:**
- Create: `asokit/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Produces: `ledger.Ledger(path, enabled=True)` with `.record(command, action, **fields)`, `.entries() -> list[dict]`, `.last(action, **match) -> str | None` (ISO timestamp); `ledger.for_config(config_path, apply) -> Ledger` (file `asokit-ledger.jsonl` next to the config; disabled when `apply` is False); `ledger.NULL` (disabled instance).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ledger.py
import json
import tempfile
import unittest
from pathlib import Path

from asokit import ledger


class LedgerTests(unittest.TestCase):
    def test_records_one_line_per_write_and_drops_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = ledger.Ledger(Path(tmp) / "asokit-ledger.jsonl")
            book.record("cpp push", "add_keywords", page_name="BPD", locale="en-US", keywords_added=["bpd"], asset_sha=None)
            book.record("cpp publish", "publish", page_id="p1")
            lines = (Path(tmp) / "asokit-ledger.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            self.assertEqual(first["action"], "add_keywords")
            self.assertNotIn("asset_sha", first)
            self.assertIn("ts", first)

    def test_disabled_ledger_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "asokit.json"
            config.write_text("{}")
            book = ledger.for_config(config, apply=False)
            book.record("cpp push", "create_page", page_name="X")
            self.assertFalse((Path(tmp) / "asokit-ledger.jsonl").exists())
            ledger.NULL.record("x", "y")

    def test_last_returns_latest_matching_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = ledger.Ledger(Path(tmp) / "l.jsonl")
            book.record("cpp publish", "publish", page_id="p1")
            book.record("cpp publish", "publish", page_id="p2")
            self.assertIsNotNone(book.last("publish", page_id="p1"))
            self.assertIsNone(book.last("submit", page_id="p1"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_ledger.py -q`
Expected: FAIL — `ImportError: cannot import name 'ledger'`

- [ ] **Step 3: Implement**

```python
# asokit/ledger.py
"""Append-only record of every App Store Connect write asokit applied.

One JSON object per line in `asokit-ledger.jsonl`, next to `asokit.json`.
Commit it with the app: it is how you line up App Analytics (per custom
product page, per creative) with the date a change actually went live.
Dry runs never write to it.
"""
import json
import time
from pathlib import Path

DEFAULT_NAME = "asokit-ledger.jsonl"


class Ledger:
    def __init__(self, path, enabled=True):
        self.path = Path(path) if path else None
        self.enabled = bool(enabled and self.path is not None)

    def record(self, command, action, **fields):
        if not self.enabled:
            return
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "command": command, "action": action}
        entry.update({key: value for key, value in fields.items() if value is not None})
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def entries(self):
        if not self.path or not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def last(self, action, **match):
        hits = [e for e in self.entries() if e.get("action") == action and all(e.get(k) == v for k, v in match.items())]
        return hits[-1]["ts"] if hits else None


def for_config(config_path, apply):
    return Ledger(Path(config_path).resolve().parent / DEFAULT_NAME, enabled=apply)


NULL = Ledger(None, enabled=False)
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest tests/test_ledger.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add asokit/ledger.py tests/test_ledger.py
git commit -m "feat: append-only ledger of applied App Store Connect writes"
```

---

### Task 3: Creative plan, PNG checks and lint

**Files:**
- Create: `asokit/creative.py`, `asokit/data/creative_lint.json`
- Modify: `pyproject.toml` (package data + `render` extra)
- Test: `tests/test_creative.py`

**Interfaces:**
- Produces: `creative.UNIVERSAL = (5244, 2950)`; `creative.plan_from_directory(directory) -> dict[str, Path]` (stem = locale); `creative.png_info(path_or_bytes) -> dict(width, height, bit_depth, colour_type, has_trns)`; `creative.check(plan, expected=UNIVERSAL, max_bytes=None) -> list[str]`; `creative.lint(text, locale) -> list[str]`; `creative.linted(locale) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_creative.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_creative.py -q`
Expected: FAIL — cannot import `creative`.

- [ ] **Step 3: Create the lint data**

```json
// asokit/data/creative_lint.json  (write WITHOUT this comment line — JSON has no comments)
{
  "_notes": "App Store creative and promo-text rejection rules. 'patterns' are regexes applied to every locale; 'words' are whole-word, case-insensitive phrases per language (locale prefix). Extend a language when the app ships UI in it.",
  "patterns": {
    "pricing": ["[$€£¥₹]", "R\\$", "\\d+\\s*%", "%\\s*off"],
    "links": ["https?://", "www\\.", "\\b[\\w-]+\\.(com|app|io|net|org)\\b"],
    "marks": ["©", "®", "™"],
    "rank": ["#\\s*1\\b"],
    "platforms": ["\\bandroid\\b", "\\bgoogle play\\b", "\\bgalaxy\\b", "\\bwear os\\b", "\\bfitbit\\b", "\\bsamsung\\b"]
  },
  "words": {
    "en": {
      "pricing": ["free", "trial", "sale", "discount"],
      "rank": ["no. 1", "number one", "best", "top-rated", "award", "award-winning", "editor's choice", "app of the day", "apple design award"],
      "health": ["diagnose", "diagnosis", "treat", "treatment", "cure", "prevent", "prevention", "predict", "detect", "early detection", "clinical-grade", "clinical grade", "clinically proven", "fda", "medical device", "doctor approved", "doctor recommended", "psychiatrist approved", "psychiatrist recommended", "therapist approved", "therapist recommended"],
      "distress": ["suicide", "self-harm", "self harm", "overdose", "crisis"]
    },
    "de": {
      "pricing": ["kostenlos", "gratis", "testversion", "angebot", "rabatt"],
      "rank": ["nr. 1", "nummer 1", "beste", "bester", "bestes", "testsieger", "auszeichnung", "preisgekrönt"],
      "health": ["diagnose", "diagnostizieren", "behandeln", "behandlung", "heilen", "heilung", "vorbeugen", "verhindern", "vorhersagen", "früherkennung", "klinisch geprüft", "klinisch getestet", "medizinprodukt", "von ärzten empfohlen"],
      "distress": ["suizid", "selbstmord", "selbstverletzung", "überdosis", "krise"]
    },
    "fr": {
      "pricing": ["gratuit", "gratuite", "essai", "promo", "réduction", "soldes"],
      "rank": ["n°1", "n° 1", "numéro 1", "meilleur", "meilleure", "récompensé", "récompensée"],
      "health": ["diagnostic", "diagnostiquer", "traiter", "traitement", "guérir", "guérison", "prévenir", "prédire", "détection précoce", "cliniquement prouvé", "dispositif médical", "recommandé par les médecins"],
      "distress": ["suicide", "automutilation", "surdose", "crise"]
    },
    "es": {
      "pricing": ["gratis", "gratuito", "gratuita", "prueba", "oferta", "descuento"],
      "rank": ["n.º 1", "nº 1", "número 1", "mejor", "premiado", "premiada"],
      "health": ["diagnóstico", "diagnosticar", "tratar", "tratamiento", "curar", "prevenir", "predecir", "detección temprana", "clínicamente probado", "dispositivo médico", "recomendado por médicos"],
      "distress": ["suicidio", "autolesión", "sobredosis", "crisis"]
    },
    "pt": {
      "pricing": ["grátis", "gratuito", "gratuita", "oferta", "desconto"],
      "rank": ["nº 1", "número 1", "melhor", "premiado", "premiada"],
      "health": ["diagnóstico", "diagnosticar", "tratar", "tratamento", "curar", "cura", "prevenir", "prever", "detecção precoce", "clinicamente comprovado", "dispositivo médico", "recomendado por médicos"],
      "distress": ["suicídio", "automutilação", "overdose", "crise"]
    },
    "it": {
      "pricing": ["gratis", "gratuito", "gratuita", "prova", "offerta", "sconto"],
      "rank": ["n. 1", "numero 1", "migliore", "premiato", "premiata"],
      "health": ["diagnosi", "diagnosticare", "trattare", "trattamento", "curare", "prevenire", "prevedere", "diagnosi precoce", "clinicamente provato", "dispositivo medico", "raccomandato dai medici"],
      "distress": ["suicidio", "autolesionismo", "overdose", "crisi"]
    }
  }
}
```

- [ ] **Step 4: Implement `creative.py`**

```python
# asokit/creative.py
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
```

Note: `"Offline"` must not trip `"off"` — there is no bare `"off"` word; `%\s*off` is a pattern. `"Treats"` must not trip `"treat"` — the word boundary `(?!\w)` handles it.

- [ ] **Step 5: Package data and extra in `pyproject.toml`**

Replace the `[project.optional-dependencies]` block and add package data:

```toml
[project.optional-dependencies]
# Only needed for App Store Connect sync. Research needs nothing.
connect = ["pyjwt>=2.0", "cryptography>=3.4"]
# Only needed for `asokit assets render`.
render = ["Pillow>=10.1"]

[tool.setuptools.package-data]
asokit = ["data/*.json"]
```

If `pyproject.toml` already has a `[tool.setuptools]` packages section, keep it and add the `package-data` table after it. Re-install editable so the data file resolves: `python3.13 -m pip install -e . -q`.

- [ ] **Step 6: Run tests**

Run: `python3.13 -m pytest tests/test_creative.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add asokit/creative.py asokit/data/creative_lint.json pyproject.toml tests/test_creative.py
git commit -m "feat: creative directory plan, PNG checks and App Store rejection lint"
```

---
### Task 4: Test fakes and the reference-data `Catalog`

**Files:**
- Create: `tests/fakes.py`, `asokit/library.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Produces (`tests/fakes.py`): `REFDATA` (dict shaped like `GET /v1/appAssetLibraryRefData`), `FakeConnect` (in-memory App Store Connect; this task covers ref data, library, images, placements, ordering, versions, experiments, review submissions — Task 11 adds CPP routes, Task 16 adds nominations), `install(testcase, fake)` (patches `asc.call`, `asc._raw`, `time.sleep`).
- Produces (`asokit/library.py`): `Catalog(attributes)`, `Catalog.fetch(bearer, features=None)`, methods `features()`, `supports(feature, placement_type)`, `groups_for_spec(feature, placement_type, spec_id) -> list[str]`, `groups_for_display_class(feature, placement_type, display_class) -> list[str]`, `specs_matching(placement_type, width, height) -> list[dict]`, `spec(spec_id)`, `max_count(feature, placement_type, group) -> int | None`, `accepts(placement_type) -> set[str]`, `display_class(group) -> str | None`, `summary() -> list[str]`. Constants `HEADER = "PRODUCT_PAGE_HEADER_ASSET"`, `SEARCH = "APP_STORE_SEARCH_RESULTS_ASSET"`, `SCREENSHOT = "APP_SCREENSHOT"`, `CREATIVE = "CREATIVE_ASSETS"`, `MEDIA = "APP_SCREENSHOTS_AND_PREVIEWS"`.

Ref-data attribute names (verified from Apple's schema): `features[].featureId`, `features[].placementPolicies[].placementType`, `…groupLimits[].groupIds`, `…groupLimits[].maxCount`; `placementProfileGroups[].placementProfileGroupId`, `.displayClassId`, `.platform`; `placementTypes[].placementTypeId`, `.acceptsAssetCategories`, `.specMappings[].placementGroupId`, `.specMappings[].specs`; `imageSpecs[].specId`, `.dimensions.{minWidth,maxWidth,minHeight,maxHeight}`, `.compatiblePlacementTypes`, `.maxFileSize`, `.universalAsset`, `.alphaAllowed`, `.shortName`.

- [ ] **Step 1: Write `tests/fakes.py`**

```python
# tests/fakes.py
"""In-memory App Store Connect for library / CPP / review / nomination tests."""
import json
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

from asokit import asc


def _spec(spec_id, w, h, types, universal=False):
    return {"specId": spec_id, "shortName": spec_id, "aspectRatio": "",
            "dimensions": {"minWidth": w, "maxWidth": w, "minHeight": h, "maxHeight": h},
            "compatiblePlacementTypes": types, "alphaAllowed": False, "fileExtensions": [".png"],
            "mimeTypes": ["image/png"], "maxFileSize": 524288000, "universalAsset": universal}


def _policies():
    return [
        {"placementType": "APP_SCREENSHOT", "groupLimits": [{"groupIds": ["G_IPHONE_L", "G_IPAD_13", "G_WATCH_U", "G_WATCH_10"], "maxCount": 10}]},
        {"placementType": "PRODUCT_PAGE_HEADER_ASSET", "groupLimits": [{"groupIds": ["G_HEADER"], "maxCount": 1}]},
        {"placementType": "APP_STORE_SEARCH_RESULTS_ASSET", "groupLimits": [{"groupIds": ["G_SEARCH"], "maxCount": 1}]},
    ]


REFDATA = {"data": [{"type": "appAssetLibraryRefData", "id": "ref", "attributes": {
    "features": [
        {"featureId": "APP_STORE_VERSIONS", "placementPolicies": _policies()},
        {"featureId": "CUSTOM_PRODUCT_PAGES", "placementPolicies": _policies()},
    ],
    "placementProfileGroups": [
        {"placementProfileGroupId": "G_IPHONE_L", "displayClassId": "IPHONE_DYNAMIC_ISLAND_LARGE_DISPLAY", "platform": "IOS"},
        {"placementProfileGroupId": "G_IPAD_13", "displayClassId": "IPAD_13_DISPLAY", "platform": "IOS"},
        {"placementProfileGroupId": "G_WATCH_U", "displayClassId": "WATCH_ULTRA", "platform": "WATCH_OS"},
        {"placementProfileGroupId": "G_WATCH_10", "displayClassId": "WATCH_SERIES_10", "platform": "WATCH_OS"},
        {"placementProfileGroupId": "G_HEADER", "displayClassId": "DEFAULT", "platform": "IOS"},
        {"placementProfileGroupId": "G_SEARCH", "displayClassId": "DEFAULT", "platform": "IOS"},
    ],
    "placementTypes": [
        {"placementTypeId": "APP_SCREENSHOT", "acceptsAssetCategories": ["APP_SCREENSHOTS_AND_PREVIEWS"], "specMappings": [
            {"placementGroupId": "G_IPHONE_L", "specs": ["S_1290"]},
            {"placementGroupId": "G_IPAD_13", "specs": ["S_2064"]},
            {"placementGroupId": "G_WATCH_U", "specs": ["S_410"]},
            {"placementGroupId": "G_WATCH_10", "specs": ["S_410"]}]},
        {"placementTypeId": "PRODUCT_PAGE_HEADER_ASSET", "acceptsAssetCategories": ["CREATIVE_ASSETS"], "specMappings": [
            {"placementGroupId": "G_HEADER", "specs": ["S_UNIV", "S_HEADER"]}]},
        {"placementTypeId": "APP_STORE_SEARCH_RESULTS_ASSET", "acceptsAssetCategories": ["CREATIVE_ASSETS"], "specMappings": [
            {"placementGroupId": "G_SEARCH", "specs": ["S_UNIV"]}]},
    ],
    "imageSpecs": [
        _spec("S_1290", 1290, 2796, ["APP_SCREENSHOT", "IMESSAGE_APP_SCREENSHOT"]),
        _spec("S_2064", 2064, 2752, ["APP_SCREENSHOT"]),
        _spec("S_410", 410, 502, ["APP_SCREENSHOT"]),
        _spec("S_UNIV", 5244, 2950, ["PRODUCT_PAGE_HEADER_ASSET", "APP_STORE_SEARCH_RESULTS_ASSET"], universal=True),
        _spec("S_HEADER", 3840, 1646, ["PRODUCT_PAGE_HEADER_ASSET"]),
    ],
    "videoSpecs": [], "displayClasses": [],
}}]}

PARENT_COLLECTIONS = {
    "appStoreVersionLocalizations": "appStoreVersionLocalization",
    "appCustomProductPageLocalizations": "appCustomProductPageLocalization",
}


class FakeConnect:
    def __init__(self):
        self.log = []
        self.seq = 0
        self.images = {}          # id -> attrs
        self.placements = {}      # id -> {parent_kind, parent_id, type, group, image, pos}
        self.spec_by_file = {}    # fileName -> specId override; otherwise matched by dimensions
        self.default_spec = "S_UNIV"  # used when no bytes were uploaded
        self.after_commit = "PREPARE_FOR_SUBMISSION"
        self.versions = [{"id": "v1", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION", "versionString": "2.3.0"}}]
        self.version_locs = {"v1": {"en-US": "vl-en", "de-DE": "vl-de"}}
        self.experiments = []
        self.submissions = {}     # id -> {"state": str, "items": [(rel, type, id)]}
        self.fail_on = None       # (method, path prefix)
        self.uploaded = {}        # upload URL -> bytes received

    # ---- plumbing -------------------------------------------------------
    def next_id(self, prefix):
        self.seq += 1
        return f"{prefix}{self.seq}"

    def raw(self, method, url, headers, data):
        self.log.append((method, url))
        self.uploaded[url] = self.uploaded.get(url, b"") + (data or b"")
        return b""

    def call(self, method, path, bearer, body=None):
        self.log.append((method, path) if body is None else (method, path, json.dumps(body, sort_keys=True)))
        if self.fail_on and method == self.fail_on[0] and path.startswith(self.fail_on[1]):
            raise asc.ASCError(f"injected failure for {method} {path}")
        url = urlparse(path)
        parts = [p for p in url.path.split("/") if p]
        if parts and parts[0] == "v1":
            parts = parts[1:]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        result = self.route(method, parts, query, body)
        if result is None:
            raise AssertionError(f"unexpected {method} {path}")
        return result

    def writes(self):
        return [entry for entry in self.log if entry[0] in ("POST", "PATCH", "DELETE")]

    # ---- routes -----------------------------------------------------------
    def route(self, method, parts, query, body):
        if method == "GET" and parts == ["appAssetLibraryRefData"]:
            return json.loads(json.dumps(REFDATA))
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "assetLibrary":
            return {"data": {"type": "appAssetLibraries", "id": "lib1"}}
        if method == "GET" and parts[:1] == ["appAssetLibraries"] and parts[2:] == ["images"]:
            return {"data": self._list_images(query), "links": {}}
        if method == "POST" and parts == ["appAssetLibraryImages"]:
            return self._reserve(body)
        if method == "PATCH" and parts[:1] == ["appAssetLibraryImages"]:
            return self._commit(parts[1], body)
        if method == "GET" and parts[:1] == ["appAssetLibraryImages"] and len(parts) == 2:
            return {"data": self._image_row(parts[1])}
        if method == "POST" and parts == ["appAssetLibraryPlacements"]:
            return self._place(body)
        if method == "DELETE" and parts[:1] == ["appAssetLibraryPlacements"]:
            self.placements.pop(parts[1])
            return {}
        if method == "GET" and len(parts) == 3 and parts[0] in PARENT_COLLECTIONS and parts[2] == "placements":
            return self._surface(PARENT_COLLECTIONS[parts[0]], parts[1])
        if method == "POST" and parts == ["appAssetLibraryPlacementOrderingRequests"]:
            for position, item in enumerate(body["data"]["relationships"]["orderedPlacements"]["data"]):
                self.placements[item["id"]]["pos"] = position
            return {"data": {"type": "appAssetLibraryPlacementOrderingRequests", "id": self.next_id("ord")}}
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "appStoreVersions":
            return {"data": self.versions}
        if method == "GET" and len(parts) == 3 and parts[0] == "appStoreVersions" and parts[2] == "appStoreVersionLocalizations":
            return {"data": [{"id": lid, "attributes": {"locale": loc}} for loc, lid in self.version_locs.get(parts[1], {}).items()]}
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "appStoreVersionExperimentsV2":
            return {"data": self.experiments}
        return self.route_review(method, parts, query, body)

    def route_review(self, method, parts, query, body):
        if method == "GET" and parts == ["reviewSubmissions"]:
            wanted = set(query.get("filter[state]", "").split(","))
            return {"data": [{"id": sid, "type": "reviewSubmissions", "attributes": {"state": s["state"]}}
                             for sid, s in self.submissions.items() if s["state"] in wanted]}
        if method == "POST" and parts == ["reviewSubmissions"]:
            sid = self.next_id("sub")
            self.submissions[sid] = {"state": "READY_FOR_REVIEW", "items": []}
            return {"data": {"id": sid, "type": "reviewSubmissions"}}
        if method == "POST" and parts == ["reviewSubmissionItems"]:
            rels = body["data"]["relationships"]
            sid = rels.pop("reviewSubmission")["data"]["id"]
            (rel, value), = rels.items()
            self.submissions[sid]["items"].append((rel, value["data"]["type"], value["data"]["id"]))
            return {"data": {"id": self.next_id("item")}}
        if method == "GET" and len(parts) == 3 and parts[0] == "reviewSubmissions" and parts[2] == "items":
            return {"data": [{"id": f"i{n}", "type": "reviewSubmissionItems",
                              "relationships": {rel: {"data": {"type": rtype, "id": rid}}}}
                             for n, (rel, rtype, rid) in enumerate(self.submissions[parts[1]]["items"])]}
        if method == "PATCH" and parts[:1] == ["reviewSubmissions"]:
            if body["data"]["attributes"].get("submitted"):
                self.submissions[parts[1]]["state"] = "WAITING_FOR_REVIEW"
            return {"data": {"id": parts[1]}}
        return None

    # ---- library internals -----------------------------------------------
    def _image_row(self, image_id):
        return {"id": image_id, "type": "appAssetLibraryImages", "attributes": dict(self.images[image_id])}

    def _list_images(self, query):
        rows = []
        for image_id, attrs in self.images.items():
            if "filter[referenceName]" in query and attrs.get("referenceName") != unquote(query["filter[referenceName]"]):
                continue
            if "filter[category]" in query and attrs.get("category") != query["filter[category]"]:
                continue
            if "filter[id]" in query and image_id not in query["filter[id]"].split(","):
                continue
            rows.append(self._image_row(image_id))
        return rows

    def _reserve(self, body):
        attrs = body["data"]["attributes"]
        assert body["data"]["relationships"]["assetLibrary"]["data"] == {"type": "appAssetLibraries", "id": "lib1"}
        image_id = self.next_id("img")
        self.images[image_id] = {"fileName": attrs["fileName"], "fileSize": attrs["fileSize"], "category": attrs["category"],
                                 "referenceName": attrs.get("referenceName"), "state": "AWAITING_UPLOAD", "specId": None}
        return {"data": {"id": image_id, "type": "appAssetLibraryImages", "attributes": dict(self.images[image_id], uploadOperations=[
            {"method": "PUT", "url": f"https://upload.invalid/{image_id}", "offset": 0, "length": attrs["fileSize"], "requestHeaders": [
                {"name": "Content-Type", "value": "image/png"}]}])}}

    def _commit(self, image_id, body):
        assert body["data"]["attributes"] == {"uploaded": True}
        image = self.images[image_id]
        image["state"] = self.after_commit
        image["specId"] = self.spec_by_file.get(image["fileName"]) or self._spec_for(self.uploaded.get(f"https://upload.invalid/{image_id}"))
        return {"data": self._image_row(image_id)}

    def _spec_for(self, data):
        """Match uploaded bytes to a spec by exact dimensions, like Apple does."""
        if data:
            from asokit.creative import png_info
            info = png_info(data)
            for spec in REFDATA["data"][0]["attributes"]["imageSpecs"]:
                d = spec["dimensions"]
                if (d["minWidth"], d["minHeight"]) == (info["width"], info["height"]):
                    return spec["specId"]
        return self.default_spec

    def _place(self, body):
        data = body["data"]
        rels = dict(data["relationships"])
        image = rels.pop("image")["data"]["id"]
        (parent_kind, parent), = rels.items()
        assert image in self.images, f"placing unknown image {image}"
        pid = self.next_id("pl")
        siblings = [p for p in self.placements.values() if p["parent_id"] == parent["data"]["id"] and p["group"] == data["attributes"]["placementGroup"]]
        self.placements[pid] = {"parent_kind": parent_kind, "parent_id": parent["data"]["id"], "type": data["attributes"]["placementType"],
                                "group": data["attributes"]["placementGroup"], "image": image, "pos": len(siblings)}
        return {"data": {"id": pid, "type": "appAssetLibraryPlacements", "attributes": {"state": "PARENT_PREPARE_FOR_SUBMISSION"}}}

    def _surface(self, parent_kind, parent_id):
        rows = sorted((p for p in self.placements.values() if p["parent_id"] == parent_id), key=lambda p: (p["group"], p["pos"]))
        ids = {id(p): pid for pid, p in self.placements.items()}
        data = [{"id": ids[id(p)], "type": "appAssetLibraryPlacements",
                 "attributes": {"placementType": p["type"], "placementGroup": p["group"], "state": "PARENT_PREPARE_FOR_SUBMISSION"},
                 "relationships": {"image": {"data": {"type": "appAssetLibraryImages", "id": p["image"]}}}} for p in rows]
        included = [self._image_row(i) for i in {p["image"] for p in rows}]
        return {"data": data, "included": included, "links": {}}

    # ---- helpers for tests -------------------------------------------------
    def group(self, parent_id, group):
        rows = sorted((p for p in self.placements.values() if p["parent_id"] == parent_id and p["group"] == group), key=lambda p: p["pos"])
        return [self.images[p["image"]]["fileName"] for p in rows]


def install(testcase, fake):
    patches = [mock.patch.object(asc, "call", fake.call), mock.patch.object(asc, "_raw", fake.raw),
               mock.patch("time.sleep", lambda seconds: None)]
    for patch in patches:
        patch.start()
        testcase.addCleanup(patch.stop)
    return fake
```

- [ ] **Step 2: Write the failing Catalog tests**

```python
# tests/test_library.py
import unittest

from asokit import library
from tests.fakes import REFDATA, FakeConnect, install


def catalog():
    return library.Catalog(REFDATA["data"][0]["attributes"])


class CatalogTests(unittest.TestCase):
    def test_fetch_reads_the_single_ref_datum(self):
        install(self, FakeConnect())
        cat = library.Catalog.fetch("t")
        self.assertEqual(cat.features(), {"APP_STORE_VERSIONS", "CUSTOM_PRODUCT_PAGES"})

    def test_groups_for_spec_respects_policy(self):
        cat = catalog()
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.HEADER, "S_UNIV"), ["G_HEADER"])
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.SEARCH, "S_UNIV"), ["G_SEARCH"])
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.SEARCH, "S_HEADER"), [])
        self.assertEqual(cat.groups_for_spec("APP_STORE_VERSIONS", library.SCREENSHOT, "S_410"), ["G_WATCH_U", "G_WATCH_10"])

    def test_unsupported_feature_or_type(self):
        cat = catalog()
        self.assertFalse(cat.supports("IN_APP_EVENTS", library.HEADER))
        self.assertEqual(cat.groups_for_spec("IN_APP_EVENTS", library.HEADER, "S_UNIV"), [])

    def test_specs_matching_by_dimensions(self):
        cat = catalog()
        self.assertEqual([s["specId"] for s in cat.specs_matching(library.HEADER, 5244, 2950)], ["S_UNIV"])
        self.assertEqual(cat.specs_matching(library.SEARCH, 3840, 1646), [])

    def test_limits_categories_and_display_class(self):
        cat = catalog()
        self.assertEqual(cat.max_count("APP_STORE_VERSIONS", library.SCREENSHOT, "G_IPHONE_L"), 10)
        self.assertEqual(cat.max_count("APP_STORE_VERSIONS", library.HEADER, "G_HEADER"), 1)
        self.assertIsNone(cat.max_count("APP_STORE_VERSIONS", library.HEADER, "G_NOPE"))
        self.assertEqual(cat.accepts(library.HEADER), {"CREATIVE_ASSETS"})
        self.assertEqual(cat.display_class("G_WATCH_U"), "WATCH_ULTRA")
        self.assertEqual(cat.groups_for_display_class("APP_STORE_VERSIONS", library.SCREENSHOT, "WATCH_ULTRA"), ["G_WATCH_U"])

    def test_summary_mentions_every_policy(self):
        text = "\n".join(catalog().summary())
        self.assertIn("CUSTOM_PRODUCT_PAGES", text)
        self.assertIn("G_SEARCH", text)
        self.assertIn("5244×2950", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify failure**

Run: `python3.13 -m pytest tests/test_library.py -q`
Expected: FAIL — cannot import `library`.

- [ ] **Step 4: Implement the catalog**

```python
# asokit/library.py
"""App Store Connect App Asset Library.

Upload an image once into the app's library, then *place* it on surfaces: an
App Store version localization or a custom product page localization. Apple
publishes which sizes go where as runtime reference data — read it, never
hard-code placement groups or spec ids (new devices appear there first).

The set-based screenshot API in `asc.py` is deprecated by Apple; this module
is its replacement.
"""
import hashlib
import time
from pathlib import Path
from urllib.parse import quote

from . import asc

SCREENSHOT = "APP_SCREENSHOT"
HEADER = "PRODUCT_PAGE_HEADER_ASSET"
SEARCH = "APP_STORE_SEARCH_RESULTS_ASSET"
CREATIVE = "CREATIVE_ASSETS"
MEDIA = "APP_SCREENSHOTS_AND_PREVIEWS"


class Catalog:
    """Parsed `appAssetLibraryRefData` (one resource, six parallel arrays)."""

    def __init__(self, attributes):
        self.raw = attributes
        self._features = {f["featureId"]: f for f in attributes.get("features", [])}
        self._groups = {g["placementProfileGroupId"]: g for g in attributes.get("placementProfileGroups", [])}
        self._types = {t["placementTypeId"]: t for t in attributes.get("placementTypes", [])}
        self._images = {s["specId"]: s for s in attributes.get("imageSpecs", [])}

    @classmethod
    def fetch(cls, bearer, features=None):
        path = "/appAssetLibraryRefData"
        if features:
            path += "?filter[features]=" + ",".join(features)
        data = asc.call("GET", path, bearer)["data"]
        item = data[0] if isinstance(data, list) else data
        return cls(item["attributes"])

    def features(self):
        return set(self._features)

    def _policy(self, feature, placement_type):
        for policy in self._features.get(feature, {}).get("placementPolicies", []):
            if policy.get("placementType") == placement_type:
                return policy
        return None

    def supports(self, feature, placement_type):
        return self._policy(feature, placement_type) is not None

    def _allowed_groups(self, policy):
        return {g for limit in policy.get("groupLimits", []) for g in limit.get("groupIds", [])}

    def groups_for_spec(self, feature, placement_type, spec_id):
        policy = self._policy(feature, placement_type)
        if policy is None:
            return []
        allowed = self._allowed_groups(policy)
        groups = []
        for mapping in self._types.get(placement_type, {}).get("specMappings", []):
            group = mapping.get("placementGroupId")
            if spec_id in mapping.get("specs", []) and (not allowed or group in allowed) and group not in groups:
                groups.append(group)
        return groups

    def groups_for_display_class(self, feature, placement_type, display_class):
        policy = self._policy(feature, placement_type)
        if policy is None:
            return []
        allowed = self._allowed_groups(policy)
        groups = []
        for mapping in self._types.get(placement_type, {}).get("specMappings", []):
            group = mapping.get("placementGroupId")
            if self.display_class(group) == display_class and (not allowed or group in allowed) and group not in groups:
                groups.append(group)
        return groups

    def specs_matching(self, placement_type, width, height):
        matches = []
        for spec in self._images.values():
            d = spec.get("dimensions", {})
            if (placement_type in spec.get("compatiblePlacementTypes", [])
                    and d.get("minWidth", 0) <= width <= d.get("maxWidth", 0)
                    and d.get("minHeight", 0) <= height <= d.get("maxHeight", 0)):
                matches.append(spec)
        return matches

    def spec(self, spec_id):
        return self._images.get(spec_id)

    def max_count(self, feature, placement_type, group):
        policy = self._policy(feature, placement_type)
        for limit in (policy or {}).get("groupLimits", []):
            if group in limit.get("groupIds", []):
                return limit.get("maxCount")
        return None

    def accepts(self, placement_type):
        return set(self._types.get(placement_type, {}).get("acceptsAssetCategories", []))

    def display_class(self, group):
        return self._groups.get(group, {}).get("displayClassId")

    def summary(self):
        """Human-readable dump for the live read-only check (Phase A step 1)."""
        lines = []
        for feature, body in sorted(self._features.items()):
            lines.append(feature)
            for policy in body.get("placementPolicies", []):
                ptype = policy.get("placementType")
                for limit in policy.get("groupLimits", []):
                    for group in limit.get("groupIds", []):
                        specs = []
                        for mapping in self._types.get(ptype, {}).get("specMappings", []):
                            if mapping.get("placementGroupId") == group:
                                for spec_id in mapping.get("specs", []):
                                    d = (self._images.get(spec_id) or {}).get("dimensions", {})
                                    specs.append(f"{spec_id} {d.get('minWidth')}×{d.get('minHeight')}")
                        lines.append(f"  {ptype:<32} {group:<40} max {limit.get('maxCount')}  "
                                     f"[{self.display_class(group)}]  {', '.join(specs) or '-'}")
        return lines
```

(`hashlib`, `time`, `Path`, `quote` are used by Tasks 5–6; keep the imports.)

- [ ] **Step 5: Run tests**

Run: `python3.13 -m pytest tests/test_library.py -q`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add asokit/library.py tests/fakes.py tests/test_library.py
git commit -m "feat(library): reference-data catalog and in-memory App Store Connect fake"
```

---

### Task 5: Upload, reuse and batch processing wait

**Files:**
- Modify: `asokit/library.py`
- Test: `tests/test_library.py` (append)

**Interfaces:**
- Consumes: `asc.call`, `asc.call_all`, `asc._raw`; `FakeConnect`/`install` from Task 4.
- Produces:
  - `library.REUSABLE`, `library.PROCESSED` (frozensets), `library.RejectedAsset(asc.ASCError)`.
  - `library.reference_name(file_name, data) -> (reference, sha16)`.
  - `library.library_id(app_id, bearer) -> str`.
  - `library.find_reusable(library_id, reference, category, bearer) -> dict | None` (an image row).
  - `library.upload_image(library_id, file_name, data, category, reference, bearer) -> str`.
  - `library.wait_processed(library_id, ids, bearer, timeout_s=900) -> dict[id, {"state","specId","stateDetails"}]`.
  - `library.Uploader(library_id, bearer, apply)` with `.ensure(file_name, data, category) -> dict` returning `{"asset": id_or_"new:<sha>", "sha": sha16, "status": "reused"|"uploaded"|"would-upload", "specId": str|None, "width": int, "height": int, "name": file_name}`, and `.new_ids` (list of ids uploaded this run).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_library.py`)

```python
from tests.test_creative import png_bytes


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())

    def test_upload_reserves_puts_and_commits(self):
        data = png_bytes(5244, 2950)
        ref, sha = library.reference_name("en-US.png", data)
        self.assertTrue(ref.startswith(f"asokit:{sha}:"))
        image_id = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        self.assertEqual(self.fake.images[image_id]["state"], "PREPARE_FOR_SUBMISSION")
        self.assertIn(("PUT", f"https://upload.invalid/{image_id}"), self.fake.log)

    def test_reuse_states(self):
        data = png_bytes(5244, 2950)
        ref, _ = library.reference_name("en-US.png", data)
        image_id = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        for state, expected in [("APPROVED", image_id), ("UPLOAD_COMPLETE", image_id), ("FAILED", None), ("ARCHIVED", None)]:
            with self.subTest(state=state):
                self.fake.images[image_id]["state"] = state
                found = library.find_reusable("lib1", ref, library.CREATIVE, "t")
                self.assertEqual(found and found["id"], expected)

    def test_awaiting_upload_is_not_reused(self):
        data = png_bytes(5244, 2950)
        ref, _ = library.reference_name("en-US.png", data)
        orphan = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        self.fake.images[orphan]["state"] = "AWAITING_UPLOAD"
        uploader = library.Uploader("lib1", "t", apply=True)
        result = uploader.ensure("en-US.png", data, library.CREATIVE)
        self.assertEqual(result["status"], "uploaded")
        self.assertNotEqual(result["asset"], orphan)
        states = library.wait_processed("lib1", uploader.new_ids, "t", timeout_s=5)
        self.assertEqual(states[result["asset"]]["state"], "PREPARE_FOR_SUBMISSION")

    def test_rejected_match_stops(self):
        data = png_bytes(5244, 2950)
        ref, _ = library.reference_name("en-US.png", data)
        image_id = library.upload_image("lib1", "en-US.png", data, library.CREATIVE, ref, "t")
        self.fake.images[image_id]["state"] = "REJECTED"
        with self.assertRaises(library.RejectedAsset):
            library.Uploader("lib1", "t", apply=True).ensure("en-US.png", data, library.CREATIVE)

    def test_in_run_cache_uploads_identical_bytes_once(self):
        data = png_bytes(5244, 2950)
        uploader = library.Uploader("lib1", "t", apply=True)
        first = uploader.ensure("en-US.png", data, library.CREATIVE)
        second = uploader.ensure("en-US.png", data, library.CREATIVE)
        self.assertEqual(first["asset"], second["asset"])
        self.assertEqual(sum(1 for e in self.fake.log if e[:2] == ("POST", "/appAssetLibraryImages")), 1)

    def test_dry_run_never_writes(self):
        uploader = library.Uploader("lib1", "t", apply=False)
        result = uploader.ensure("en-US.png", png_bytes(5244, 2950), library.CREATIVE)
        self.assertEqual(result["status"], "would-upload")
        self.assertTrue(result["asset"].startswith("new:"))
        self.assertEqual(self.fake.writes(), [])

    def test_wait_reports_failed_without_hanging(self):
        self.fake.after_commit = "FAILED"
        uploader = library.Uploader("lib1", "t", apply=True)
        result = uploader.ensure("en-US.png", png_bytes(5244, 2950), library.CREATIVE)
        states = library.wait_processed("lib1", uploader.new_ids, "t", timeout_s=5)
        self.assertEqual(states[result["asset"]]["state"], "FAILED")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_library.py -q -k Upload`
Expected: FAIL — `AttributeError: module 'asokit.library' has no attribute 'reference_name'`.

- [ ] **Step 3: Implement** (append to `asokit/library.py`)

```python
REUSABLE = frozenset({"UPLOAD_COMPLETE", "COMPLETE", "PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW",
                      "WAITING_FOR_REVIEW", "IN_REVIEW", "ACCEPTED", "APPROVED"})
PROCESSED = REUSABLE - {"UPLOAD_COMPLETE"}
TERMINAL_BAD = frozenset({"FAILED", "REJECTED", "ARCHIVED"})


class RejectedAsset(asc.ASCError):
    pass


def reference_name(file_name, data):
    sha = hashlib.sha256(data).hexdigest()[:16]
    return f"asokit:{sha}:{Path(file_name).name[:40]}", sha


def sha_of(reference):
    """The content hash inside an asokit referenceName, else None."""
    if reference and reference.startswith("asokit:"):
        return reference.split(":")[1]
    return None


def library_id(app_id, bearer):
    return asc.call("GET", f"/apps/{app_id}/assetLibrary", bearer)["data"]["id"]


def find_reusable(library, reference, category, bearer):
    rows = asc.call_all(
        "GET",
        f"/appAssetLibraries/{library}/images?filter[referenceName]={quote(reference, safe='')}"
        f"&filter[category]={category}&limit=200",
        bearer,
    )
    usable = [row for row in rows if row["attributes"].get("state") in REUSABLE]
    if usable:
        return usable[0]
    if any(row["attributes"].get("state") == "REJECTED" for row in rows):
        raise RejectedAsset(f"{reference}: this exact image was rejected by App Review — change it and re-render")
    return None


def upload_image(library, file_name, data, category, reference, bearer):
    reserved = asc.call("POST", "/appAssetLibraryImages", bearer, {"data": {
        "type": "appAssetLibraryImages",
        "attributes": {"fileName": Path(file_name).name, "fileSize": len(data), "category": category, "referenceName": reference},
        "relationships": {"assetLibrary": {"data": {"type": "appAssetLibraries", "id": library}}},
    }})["data"]
    for op in reserved["attributes"]["uploadOperations"]:
        chunk = data[op["offset"]: op["offset"] + op["length"]]
        asc._raw(op["method"], op["url"], {h["name"]: h["value"] for h in op.get("requestHeaders", [])}, chunk)
    asc.call("PATCH", f"/appAssetLibraryImages/{reserved['id']}", bearer, {"data": {
        "type": "appAssetLibraryImages", "id": reserved["id"], "attributes": {"uploaded": True},
    }})
    return reserved["id"]


def wait_processed(library, ids, bearer, timeout_s=900):
    """Batch-poll until every id is processed or terminally bad; backoff 5 → 30 s."""
    states, pending = {}, set(ids)
    delay, deadline = 5, time.time() + timeout_s
    while pending:
        ordered = sorted(pending)
        for start in range(0, len(ordered), 50):
            chunk = ",".join(ordered[start:start + 50])
            for row in asc.call_all("GET", f"/appAssetLibraries/{library}/images?filter[id]={chunk}&limit=200", bearer):
                attrs = row["attributes"]
                states[row["id"]] = {"state": attrs.get("state"), "specId": attrs.get("specId"), "stateDetails": attrs.get("stateDetails")}
        pending = {i for i in pending if states.get(i, {}).get("state") not in PROCESSED | TERMINAL_BAD}
        if not pending or time.time() >= deadline:
            break
        time.sleep(delay)
        delay = min(delay * 2, 30)
    return states


class Uploader:
    """Upload-or-reuse, with an in-run cache keyed by (sha, category)."""

    def __init__(self, library, bearer, apply):
        self.library, self.bearer, self.apply = library, bearer, apply
        self.cache = {}
        self.new_ids = []

    def ensure(self, file_name, data, category):
        from .creative import png_info
        reference, sha = reference_name(file_name, data)
        info = png_info(data)
        base = {"sha": sha, "name": Path(file_name).name, "width": info["width"], "height": info["height"]}
        key = (sha, category)
        if key in self.cache:
            return dict(self.cache[key], **{k: base[k] for k in ("name",)})
        row = find_reusable(self.library, reference, category, self.bearer)
        if row:
            result = dict(base, asset=row["id"], status="reused", specId=row["attributes"].get("specId"))
        elif not self.apply:
            result = dict(base, asset=f"new:{sha}", status="would-upload", specId=None)
        else:
            asset = upload_image(self.library, file_name, data, category, reference, self.bearer)
            self.new_ids.append(asset)
            result = dict(base, asset=asset, status="uploaded", specId=None)
        self.cache[key] = result
        return result
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest tests/test_library.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add asokit/library.py tests/test_library.py
git commit -m "feat(library): upload with safe reuse, in-run cache and batch processing wait"
```

---

### Task 6: Placements, `replace_group`, `sync_groups` and the PPO guard

**Files:**
- Modify: `asokit/library.py`
- Test: `tests/test_library.py` (append)

**Interfaces:**
- Consumes: Task 4–5 functions.
- Produces:
  - `library.PARENTS = {"appStoreVersionLocalization": "appStoreVersionLocalizations", "appCustomProductPageLocalization": "appCustomProductPageLocalizations"}`.
  - `library.VERSION_PLACEABLE` (frozenset of App Store version states).
  - `library.PartialPlacement(asc.ASCError)`.
  - `library.surface_placements(parent_kind, parent_id, bearer) -> list[{"id","type","group","state","asset","sha"}]`.
  - `library.place(asset_id, placement_type, group, parent_kind, parent_id, bearer) -> str`, `library.unplace(placement_id, bearer)`, `library.order(group, placement_ids, parent_kind, parent_id, bearer)`.
  - `library.replace_group(desired, placement_type, group, parent_kind, parent_id, max_count, bearer, apply, current) -> dict` where `desired = [{"asset": id, "sha": sha16}]`, `current` = that group's rows from `surface_placements`; result `{"type","group","parent_id","mode": "unchanged"|"reorder"|"place-first"|"unplace-first","place": int,"unplace": int}`.
  - `library.sync_groups(requests, catalog, feature, library_id, bearer, apply, ledger=None, command="", progress=None) -> list[dict]` — see docstring for the request shape.
  - `library.active_experiment(app_id, bearer) -> str | None`.

- [ ] **Step 1: Write the failing tests** (append)

```python
class ReplaceGroupTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())
        self.fake.default_spec = "S_1290"
        self.uploader = library.Uploader("lib1", "t", apply=True)

    def asset(self, name):
        return self.uploader.ensure(name, png_bytes(1290, 2796) + name.encode(), library.MEDIA)

    def current(self):
        return [p for p in library.surface_placements("appStoreVersionLocalization", "vl-en", "t") if p["group"] == "G_IPHONE_L"]

    def replace(self, names, max_count=10):
        desired = [{"asset": a["asset"], "sha": a["sha"]} for a in (self.asset(n) for n in names)]
        return library.replace_group(desired, library.SCREENSHOT, "G_IPHONE_L", "appStoreVersionLocalization", "vl-en",
                                     max_count, "t", apply=True, current=self.current())

    def test_first_fill_then_unchanged_is_zero_writes(self):
        self.replace(["a.png", "b.png"])
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["a.png", "b.png"])
        before = len(self.fake.writes())
        result = self.replace(["a.png", "b.png"])
        self.assertEqual(result["mode"], "unchanged")
        self.assertEqual(len(self.fake.writes()), before)

    def test_reorder_only_issues_one_ordering_request(self):
        self.replace(["a.png", "b.png"])
        before = len(self.fake.writes())
        result = self.replace(["b.png", "a.png"])
        self.assertEqual(result["mode"], "reorder")
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["b.png", "a.png"])
        self.assertEqual(len(self.fake.writes()), before + 1)

    def test_place_first_under_capacity_keeps_shared_assets(self):
        self.replace(["a.png", "b.png"])
        c, a = self.asset("c.png"), self.asset("a.png")
        start = len(self.fake.log)
        result = library.replace_group([{"asset": c["asset"], "sha": c["sha"]}, {"asset": a["asset"], "sha": a["sha"]}],
                                       library.SCREENSHOT, "G_IPHONE_L", "appStoreVersionLocalization", "vl-en",
                                       10, "t", apply=True, current=self.current())
        self.assertEqual(result["mode"], "place-first")
        self.assertEqual((result["place"], result["unplace"]), (1, 1))
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["c.png", "a.png"])
        tail = [entry[:2] for entry in self.fake.log[start:]]
        first_place = tail.index(("POST", "/appAssetLibraryPlacements"))
        first_delete = next(i for i, entry in enumerate(tail) if entry[0] == "DELETE")
        self.assertLess(first_place, first_delete)

    def test_unplace_first_at_capacity(self):
        self.replace(["a.png"], max_count=1)
        result = self.replace(["b.png"], max_count=1)
        self.assertEqual(result["mode"], "unplace-first")
        self.assertEqual(self.fake.group("vl-en", "G_IPHONE_L"), ["b.png"])

    def test_abort_between_unplace_and_place_reports_gap(self):
        self.replace(["a.png"], max_count=1)
        b = self.asset("b.png")
        self.fake.fail_on = ("POST", "/appAssetLibraryPlacements")
        with self.assertRaises(library.PartialPlacement) as caught:
            library.replace_group([{"asset": b["asset"], "sha": b["sha"]}], library.SCREENSHOT, "G_IPHONE_L",
                                  "appStoreVersionLocalization", "vl-en", 1, "t", apply=True, current=self.current())
        self.assertIn("0 of 1", str(caught.exception))

    def test_never_deletes_assets(self):
        self.replace(["a.png", "b.png"])
        self.replace(["c.png"])
        self.assertFalse(any(e[0] == "DELETE" and "/appAssetLibraryImages" in e[1] for e in self.fake.log))


class SyncGroupsTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())
        self.catalog = library.Catalog.fetch("t")

    def creative_request(self, locale, parent):
        return {"locale": locale, "parent_kind": "appStoreVersionLocalization", "parent_id": parent,
                "placement_types": [library.HEADER, library.SEARCH], "category": library.CREATIVE,
                "files": [(f"{locale}.png", png_bytes(5244, 2950) + locale.encode())]}

    def test_creative_lands_in_header_and_search(self):
        actions = library.sync_groups([self.creative_request("en-US", "vl-en"), self.creative_request("de-DE", "vl-de")],
                                      self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertEqual(self.fake.group("vl-en", "G_HEADER"), ["en-US.png"])
        self.assertEqual(self.fake.group("vl-en", "G_SEARCH"), ["en-US.png"])
        self.assertEqual(self.fake.group("vl-de", "G_HEADER"), ["de-DE.png"])
        self.assertEqual({a["group"] for a in actions}, {"G_HEADER", "G_SEARCH"})

    def test_uploads_all_before_any_placement(self):
        library.sync_groups([self.creative_request("en-US", "vl-en"), self.creative_request("de-DE", "vl-de")],
                            self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        kinds = [e[1] for e in self.fake.log if e[0] == "POST"]
        last_upload = max(i for i, k in enumerate(kinds) if k == "/appAssetLibraryImages")
        first_place = min(i for i, k in enumerate(kinds) if k == "/appAssetLibraryPlacements")
        self.assertLess(last_upload, first_place)

    def test_processing_failure_places_nothing(self):
        self.fake.after_commit = "FAILED"
        with self.assertRaises(asc.ASCError):
            library.sync_groups([self.creative_request("en-US", "vl-en")], self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertFalse(any(e[:2] == ("POST", "/appAssetLibraryPlacements") for e in self.fake.log))

    def test_spec_mismatch_is_reported(self):
        self.fake.spec_by_file = {"en-US.png": "S_HEADER"}   # Apple matched the file to the header-only spec
        with self.assertRaises(asc.ASCError) as caught:
            library.sync_groups([self.creative_request("en-US", "vl-en")], self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertIn("S_HEADER", str(caught.exception))

    def test_dry_run_plans_new_parent_without_reads(self):
        request = dict(self.creative_request("en-US", None))
        actions = library.sync_groups([request], self.catalog, "CUSTOM_PRODUCT_PAGES", "lib1", "t", apply=False)
        self.assertEqual(len(actions), 2)
        self.assertEqual(self.fake.writes(), [])

    def test_watch_ambiguity_resolved_by_display_class(self):
        request = {"locale": "en-US", "parent_kind": "appStoreVersionLocalization", "parent_id": "vl-en",
                   "placement_types": [library.SCREENSHOT], "category": library.MEDIA, "display_class": "WATCH_ULTRA",
                   "files": [("w.png", png_bytes(410, 502))]}
        self.fake.default_spec = "S_410"
        library.sync_groups([request], self.catalog, "APP_STORE_VERSIONS", "lib1", "t", apply=True)
        self.assertEqual(self.fake.group("vl-en", "G_WATCH_U"), ["w.png"])
        self.assertEqual(self.fake.group("vl-en", "G_WATCH_10"), [])


class ExperimentGuardTests(unittest.TestCase):
    def test_running_and_in_review_experiments_block(self):
        fake = install(self, FakeConnect())
        self.assertIsNone(library.active_experiment("1", "t"))
        fake.experiments = [{"id": "e1", "attributes": {"name": "Icon test", "state": "APPROVED", "startDate": "2026-01-01T00:00:00Z", "endDate": None}}]
        self.assertEqual(library.active_experiment("1", "t"), "Icon test")
        fake.experiments = [{"id": "e1", "attributes": {"name": "Old", "state": "APPROVED", "startDate": "2026-01-01T00:00:00Z", "endDate": "2026-02-01T00:00:00Z"}}]
        self.assertIsNone(library.active_experiment("1", "t"))
        fake.experiments = [{"id": "e2", "attributes": {"name": "Queued", "state": "WAITING_FOR_REVIEW"}}]
        self.assertEqual(library.active_experiment("1", "t"), "Queued")
```

Add `from asokit import asc` to the imports at the top of `tests/test_library.py`.

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_library.py -q`
Expected: FAIL — missing `replace_group`, `surface_placements`, etc.

- [ ] **Step 3: Implement** (append to `asokit/library.py`)

```python
PARENTS = {
    "appStoreVersionLocalization": "appStoreVersionLocalizations",
    "appCustomProductPageLocalization": "appCustomProductPageLocalizations",
}
VERSION_PLACEABLE = frozenset({"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY"})


class PartialPlacement(asc.ASCError):
    pass


def surface_placements(parent_kind, parent_id, bearer):
    """Every placement on one localization, with each placement's asset hash."""
    url = f"/{PARENTS[parent_kind]}/{parent_id}/placements?include=image&sort=placementGroupPosition&limit=200"
    rows, images = [], {}
    while url:
        page = asc.call("GET", url, bearer)
        rows.extend(page.get("data", []))
        for item in page.get("included", []) or []:
            if item.get("type") == "appAssetLibraryImages":
                images[item["id"]] = item.get("attributes") or {}
        url = (page.get("links") or {}).get("next")
    placements = []
    for row in rows:
        attrs = row.get("attributes") or {}
        image = (((row.get("relationships") or {}).get("image") or {}).get("data") or {}).get("id")
        placements.append({"id": row["id"], "type": attrs.get("placementType"), "group": attrs.get("placementGroup"),
                           "state": attrs.get("state"), "asset": image,
                           "sha": sha_of((images.get(image) or {}).get("referenceName"))})
    return placements


def place(asset_id, placement_type, group, parent_kind, parent_id, bearer):
    return asc.call("POST", "/appAssetLibraryPlacements", bearer, {"data": {
        "type": "appAssetLibraryPlacements",
        "attributes": {"placementType": placement_type, "placementGroup": group},
        "relationships": {
            "image": {"data": {"type": "appAssetLibraryImages", "id": asset_id}},
            parent_kind: {"data": {"type": PARENTS[parent_kind], "id": parent_id}},
        },
    }})["data"]["id"]


def unplace(placement_id, bearer):
    asc.call("DELETE", f"/appAssetLibraryPlacements/{placement_id}", bearer)


def order(group, placement_ids, parent_kind, parent_id, bearer):
    asc.call("POST", "/appAssetLibraryPlacementOrderingRequests", bearer, {"data": {
        "type": "appAssetLibraryPlacementOrderingRequests",
        "attributes": {"placementGroup": group},
        "relationships": {
            "orderedPlacements": {"data": [{"type": "appAssetLibraryPlacements", "id": pid} for pid in placement_ids]},
            parent_kind: {"data": {"type": PARENTS[parent_kind], "id": parent_id}},
        },
    }})


def _key(row):
    return row.get("sha") or row.get("asset")


def replace_group(desired, placement_type, group, parent_kind, parent_id, max_count, bearer, apply, current):
    """Make one placement group hold exactly `desired`, in order, with minimal writes.

    Placements that already show a desired asset are kept. Missing ones are
    placed BEFORE extras are removed whenever the group's limit allows, so an
    abort never leaves the surface emptier than it started; at the limit the
    extras go first and an abort reports the gap.
    """
    pool = list(current)
    final = []
    for want in desired:
        match = next((row for row in pool if _key(row) == _key(want)), None)
        if match:
            pool.remove(match)
        final.append([match["id"] if match else None, want])
    extras = pool
    missing = [slot for slot in final if slot[0] is None]
    action = {"type": placement_type, "group": group, "parent_id": parent_id, "place": len(missing), "unplace": len(extras)}
    if not missing and not extras:
        action["mode"] = "unchanged" if [s[0] for s in final] == [row["id"] for row in current] else "reorder"
    else:
        place_first = max_count is None or len(current) + len(missing) <= max_count
        action["mode"] = "place-first" if place_first else "unplace-first"
    if not apply or action["mode"] == "unchanged":
        return action

    placed = 0
    try:
        if action["mode"] == "unplace-first":
            for row in extras:
                unplace(row["id"], bearer)
        for slot in missing:
            slot[0] = place(slot[1]["asset"], placement_type, group, parent_kind, parent_id, bearer)
            placed += 1
        if action["mode"] == "place-first":
            for row in extras:
                unplace(row["id"], bearer)
    except asc.ASCError as error:
        raise PartialPlacement(
            f"{parent_id} {group}: {placed} of {len(missing)} new placements made before the failure — "
            f"the group may be incomplete; re-run to converge.\n{error}"
        ) from error
    ids = [slot[0] for slot in final]
    if len(ids) > 1:
        order(group, ids, parent_kind, parent_id, bearer)
        actual = [row["id"] for row in surface_placements(parent_kind, parent_id, bearer) if row["group"] == group]
        if actual != ids:
            raise asc.ASCError(f"{parent_id} {group}: order did not stick (got {actual}, wanted {ids})")
    return action


def sync_groups(requests, catalog, feature, library, bearer, apply, ledger=None, command="", progress=None):
    """Upload/reuse every file, wait once, then replace each request's groups.

    A request is a dict:
      locale, parent_kind, parent_id (None for a surface that doesn't exist yet — dry run only),
      placement_types: [type, ...]  (one asset sequence is placed under each type),
      category: CREATIVE or MEDIA,
      files: [(file_name, bytes), ...]  OR  assets: [{"asset", "sha", "specId"}] (re-place existing assets),
      display_class: optional tie-breaker when a spec maps to several groups (e.g. Watch 410×502),
      groups: optional explicit group list (mirroring copies the source group).
    Phase 1 (no surface writes): uploads + one processing wait + spec checks.
    Phase 2: replace_group per (request, type, group).
    """
    uploader = Uploader(library, bearer, apply)
    for request in requests:
        if "assets" not in request:
            request["assets"] = [uploader.ensure(name, data, request["category"]) for name, data in request["files"]]
    if apply and uploader.new_ids:
        states = wait_processed(library, uploader.new_ids, bearer)
        bad = {i: s for i, s in states.items() if s.get("state") not in PROCESSED}
        if bad:
            details = ", ".join(f"{i}: {s.get('state')} {s.get('stateDetails') or ''}".strip() for i, s in bad.items())
            raise asc.ASCError(f"Apple did not accept {len(bad)} upload(s) — nothing placed. {details}")
        for request in requests:
            for asset in request["assets"]:
                if asset["asset"] in states:
                    asset["specId"] = states[asset["asset"]]["specId"]

    plans = []
    for request in requests:
        for ptype in request["placement_types"]:
            if not catalog.supports(feature, ptype):
                plans.append((request, ptype, None))
                continue
            groups = request.get("groups") or _resolve_groups(catalog, feature, ptype, request)
            for group in groups:
                plans.append((request, ptype, group))

    actions, surfaces = [], {}
    for request, ptype, group in plans:
        if group is None:
            actions.append({"locale": request["locale"], "type": ptype, "group": None, "mode": "unsupported",
                            "parent_id": request["parent_id"], "place": 0, "unplace": 0})
            continue
        parent = request["parent_id"]
        if parent not in surfaces:
            surfaces[parent] = surface_placements(request["parent_kind"], parent, bearer) if parent else []
        current = [row for row in surfaces[parent] if row["type"] == ptype and row["group"] == group]
        desired = [{"asset": a["asset"], "sha": a["sha"]} for a in request["assets"]]
        action = replace_group(desired, ptype, group, request["parent_kind"], parent,
                               catalog.max_count(feature, ptype, group), bearer, apply and parent is not None, current)
        action["locale"] = request["locale"]
        actions.append(action)
        if apply and ledger and action["mode"] != "unchanged":
            ledger.record(command, "place", locale=request["locale"], surface=request["parent_kind"], parent_id=parent,
                          placement_type=ptype, group=group, asset_sha=[a["sha"] for a in request["assets"]], mode=action["mode"])
        if progress:
            progress(action)
    return actions


def _resolve_groups(catalog, feature, ptype, request):
    """Groups every asset of the request can go to; screenshots need exactly one."""
    per_asset = []
    for asset in request["assets"]:
        if asset.get("specId"):
            groups = catalog.groups_for_spec(feature, ptype, asset["specId"])
            if not groups:
                raise asc.ASCError(f"{request['locale']}: {asset['name']} matched spec {asset['specId']}, "
                                   f"which has no {ptype} group under {feature}")
        else:   # dry run, or reused row without a spec: infer from dimensions
            groups = []
            for spec in catalog.specs_matching(ptype, asset["width"], asset["height"]):
                groups += [g for g in catalog.groups_for_spec(feature, ptype, spec["specId"]) if g not in groups]
            if not groups:
                raise asc.ASCError(f"{request['locale']}: {asset['name']} is {asset['width']}×{asset['height']}; "
                                   f"no {ptype} spec under {feature} accepts that size")
        per_asset.append(groups)
    common = [g for g in per_asset[0] if all(g in groups for groups in per_asset[1:])] if per_asset else []
    if request.get("display_class"):
        common = [g for g in common if catalog.display_class(g) == request["display_class"]] or common
    if ptype == SCREENSHOT and len(common) != 1:
        raise asc.ASCError(f"{request['locale']}: screenshots map to {len(common)} groups {common}; pass a display class")
    return common


EXPERIMENT_REVIEW = frozenset({"READY_FOR_REVIEW", "WAITING_FOR_REVIEW", "IN_REVIEW"})
EXPERIMENT_LIVE = frozenset({"ACCEPTED", "APPROVED"})


def active_experiment(app_id, bearer):
    """Name of a product page optimization test that is in review or running, else None.

    Field reports say a running test blocks placements on the default page.
    Apple has no RUNNING state: running = approved/accepted, started, not ended.
    """
    states = ",".join(sorted(EXPERIMENT_REVIEW | EXPERIMENT_LIVE))
    rows = asc.call_all("GET", f"/apps/{app_id}/appStoreVersionExperimentsV2?filter[state]={states}&limit=200", bearer)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for row in rows:
        attrs = row.get("attributes") or {}
        state = attrs.get("state")
        if state in EXPERIMENT_REVIEW:
            return attrs.get("name") or row["id"]
        if state in EXPERIMENT_LIVE and (attrs.get("startDate") or "") <= now and not attrs.get("endDate"):
            return attrs.get("name") or row["id"]
    return None
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add asokit/library.py tests/test_library.py
git commit -m "feat(library): minimal-write group replacement, two-phase sync and PPO guard"
```

---
### Task 7: Universal creative renderer

**Files:**
- Create: `asokit/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `creative.lint`, `creative.linted` (Task 3).
- Produces:
  - `render.RenderError(Exception)`.
  - `render.safe_box(width, height, inset) -> (x0, y0, x1, y1)`.
  - `render.load_config(path) -> dict` (adds `"_root"`: the config's directory as `Path`).
  - `render.resolve_headlines(cfg, variant_name) -> dict[locale, {"verb","descriptor","ui","rtl","fallback"}]`.
  - `render.render_variant(cfg, variant_name, out_dir, locales=None, lint=True, strict_lint=False) -> {"written": [Path], "failed": {locale: reason}, "report": [dict], "unlinted": [locale]}`.

Geometry (spec): canvas 5244×2950; 21:9 header crop = 5244×2247.43 centred; 3:2 search crop = 4425×2950 centred; safe box = intersection, floored origin, then inset 3 % per side. Headline column ~44 % of the safe box on the leading side (left LTR, right RTL); 1–2 devices on the trailing side; everything (text, frames, shadows) inside the inset box.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_render.py
import json
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_render.py -q`
Expected: FAIL — cannot import `render`.

- [ ] **Step 3: Implement**

```python
# asokit/render.py
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
        return ImageFont.load_default(size)
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
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest tests/test_render.py -q`
Expected: all pass (RTL test skipped only if libraqm is missing; this machine has it).

If `test_output_size_mode_and_containment` fails because the text bounding box exceeds the safe box at the bottom, the descriptor leading pushed the block past the box: reduce the fixture's descriptor `size` rather than changing geometry — the geometry is the spec.

- [ ] **Step 5: Commit**

```bash
git add asokit/render.py tests/test_render.py
git commit -m "feat(render): config-driven universal creative renderer with safe-box layout"
```

---
### Task 8: Guarded review submissions and the `assets` commands

**Files:**
- Create: `asokit/review.py`
- Modify: `asokit/cli.py` (imports, new `cmd_assets_*` functions, parser block, module docstring)
- Test: `tests/test_review.py`, `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `library.*` (Tasks 4–6), `creative.*` (Task 3), `render.*` (Task 7), `ledger.for_config` (Task 2), `asc.Bearer` (Task 1), `asc.editable_version`, `asc._localizations` (existing).
- Produces:
  - `review.SubmissionBlocked(asc.ASCError)`.
  - `review.submit(app_id, items, bearer, apply, ledger=None, command="") -> dict` where `items = [(relationship, resource_type, id), ...]`, e.g. `("appCustomProductPageVersion", "appCustomProductPageVersions", "cv1")`; result `{"submission": id or "(new)", "add": [items], "existing": [items], "submitted": bool}`.
  - CLI: `asokit assets render|status|push|submit` (this task supports `--target default` only; Task 14 adds `--target cpp:<name>`).
  - `cli._bearer()` — returns `asc.Bearer()`; tests patch it.
  - `cli._config_path(args)` — `Path(args.config)`.

- [ ] **Step 1: Write the failing review tests**

```python
# tests/test_review.py
import unittest

from asokit import review
from tests.fakes import FakeConnect, install

CPP_ITEM = ("appCustomProductPageVersion", "appCustomProductPageVersions", "cv1")


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeConnect())

    def test_creates_submission_adds_items_and_submits(self):
        result = review.submit("1", [CPP_ITEM], "t", apply=True)
        sub = self.fake.submissions[result["submission"]]
        self.assertEqual(sub["items"], [CPP_ITEM])
        self.assertEqual(sub["state"], "WAITING_FOR_REVIEW")

    def test_dry_run_writes_nothing(self):
        result = review.submit("1", [CPP_ITEM], "t", apply=False)
        self.assertEqual(result["submission"], "(new)")
        self.assertEqual(self.fake.writes(), [])

    def test_in_flight_submission_stops(self):
        self.fake.submissions["s0"] = {"state": "WAITING_FOR_REVIEW", "items": []}
        with self.assertRaises(review.SubmissionBlocked):
            review.submit("1", [CPP_ITEM], "t", apply=True)

    def test_foreign_item_in_draft_stops(self):
        self.fake.submissions["s0"] = {"state": "READY_FOR_REVIEW", "items": [("appStoreVersion", "appStoreVersions", "v1")]}
        with self.assertRaises(review.SubmissionBlocked) as caught:
            review.submit("1", [CPP_ITEM], "t", apply=True)
        self.assertIn("appStoreVersion", str(caught.exception))
        self.assertEqual(self.fake.submissions["s0"]["state"], "READY_FOR_REVIEW")

    def test_clean_draft_is_reused(self):
        self.fake.submissions["s0"] = {"state": "READY_FOR_REVIEW", "items": [CPP_ITEM]}
        other = ("appCustomProductPageVersion", "appCustomProductPageVersions", "cv2")
        result = review.submit("1", [CPP_ITEM, other], "t", apply=True)
        self.assertEqual(result["submission"], "s0")
        self.assertEqual(self.fake.submissions["s0"]["items"], [CPP_ITEM, other])
        self.assertEqual(self.fake.submissions["s0"]["state"], "WAITING_FOR_REVIEW")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_review.py -q`
Expected: FAIL — cannot import `review`.

- [ ] **Step 3: Implement `review.py`**

```python
# asokit/review.py
"""Review submissions that can only ever contain what asokit put in them.

An app has one open review submission per platform. If the user already has a
draft holding the app version, adding a custom product page to it and
submitting would ship the version too — so a draft is reused only when every
item in it is one asokit is submitting now; otherwise we stop.
"""
from . import asc

OPEN = ("READY_FOR_REVIEW", "WAITING_FOR_REVIEW", "IN_REVIEW", "UNRESOLVED_ISSUES")
IN_FLIGHT = frozenset({"WAITING_FOR_REVIEW", "IN_REVIEW", "UNRESOLVED_ISSUES"})
ITEM_RELATIONSHIPS = ("appStoreVersion", "appCustomProductPageVersion", "appAssetLibraryImage", "appAssetLibraryVideo",
                      "appEvent", "appStoreVersionExperiment", "appStoreVersionExperimentV2", "inAppPurchaseVersion",
                      "subscriptionVersion", "subscriptionGroupVersion", "backgroundAssetVersion")


class SubmissionBlocked(asc.ASCError):
    pass


def _items(submission_id, bearer):
    include = ",".join(ITEM_RELATIONSHIPS)
    rows = asc.call_all("GET", f"/reviewSubmissions/{submission_id}/items?include={include}&limit=200", bearer)
    found = []
    for row in rows:
        key = ("unknown", "unknown", row["id"])
        for name in ITEM_RELATIONSHIPS:
            data = ((row.get("relationships") or {}).get(name) or {}).get("data")
            if data:
                key = (name, data["type"], data["id"])
                break
        found.append(key)
    return found


def submit(app_id, items, bearer, apply, ledger=None, command=""):
    planned = list(dict.fromkeys(tuple(i) for i in items))
    if not planned:
        raise SubmissionBlocked("nothing to submit")
    states = ",".join(OPEN)
    open_rows = asc.call_all("GET", f"/reviewSubmissions?filter[app]={app_id}&filter[platform]=IOS&filter[state]={states}&limit=200", bearer)
    flying = [r for r in open_rows if (r.get("attributes") or {}).get("state") in IN_FLIGHT]
    if flying:
        raise SubmissionBlocked(f"a review submission is in flight ({flying[0]['id']}, {flying[0]['attributes']['state']}) — "
                                "wait for it to finish, then re-run")
    drafts = [r for r in open_rows if (r.get("attributes") or {}).get("state") == "READY_FOR_REVIEW"]
    submission, existing = None, []
    if drafts:
        submission = drafts[0]["id"]
        existing = _items(submission, bearer)
        foreign = [i for i in existing if i not in planned]
        if foreign:
            listed = ", ".join(f"{rel} {rid}" for rel, _, rid in foreign)
            raise SubmissionBlocked(f"draft submission {submission} already holds other items ({listed}). "
                                    "Submit or clear it in App Store Connect first — asokit will not submit them for you.")
    add = [i for i in planned if i not in existing]
    result = {"submission": submission or "(new)", "add": add, "existing": existing, "submitted": False}
    if not apply:
        return result
    if submission is None:
        submission = asc.call("POST", "/reviewSubmissions", bearer, {"data": {
            "type": "reviewSubmissions", "attributes": {"platform": "IOS"},
            "relationships": {"app": {"data": {"type": "apps", "id": str(app_id)}}},
        }})["data"]["id"]
        result["submission"] = submission
    for relationship, resource_type, resource_id in add:
        asc.call("POST", "/reviewSubmissionItems", bearer, {"data": {
            "type": "reviewSubmissionItems",
            "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission}},
                relationship: {"data": {"type": resource_type, "id": resource_id}},
            },
        }})
    final = _items(submission, bearer)
    if sorted(final) != sorted(planned):
        raise SubmissionBlocked(f"submission {submission} holds {final}, expected {planned} — NOT submitted")
    asc.call("PATCH", f"/reviewSubmissions/{submission}", bearer, {"data": {
        "type": "reviewSubmissions", "id": submission, "attributes": {"submitted": True},
    }})
    result["submitted"] = True
    if ledger:
        ledger.record(command, "submit", submission_id=submission, items=[f"{rel}:{rid}" for rel, _, rid in planned])
    return result
```

- [ ] **Step 4: Run review tests**

Run: `python3.13 -m pytest tests/test_review.py -q`
Expected: 5 passed.

- [ ] **Step 5: Write the failing CLI tests** (append to `tests/test_cli.py`)

```python
import contextlib
import io
from unittest import mock

from asokit import asc as asc_module
from tests.fakes import FakeConnect, install
from tests.test_creative import png_bytes


class AssetsCommands(unittest.TestCase):
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
```

- [ ] **Step 6: Run to verify failure**

Run: `python3.13 -m pytest tests/test_cli.py -q -k Assets`
Expected: FAIL — `AttributeError: module 'asokit.cli' has no attribute '_bearer'`.

- [ ] **Step 7: Implement the CLI**

In `asokit/cli.py`:

1. Extend the module docstring with:

```
  asokit assets render [--variant V]   render header/search creatives from assets.json
  asokit assets status [--catalog]     library, asset states, placements
  asokit assets push DIR --target default [--apply]   place creatives
  asokit assets submit DIR [--apply]   standalone review of creatives
```

2. Extend the `from . import (...)` block with `creative`, `ledger as ledger_module`, `library`, `review`. Do **not** import `render` at module level (it is optional); import it inside `cmd_assets_render`.

3. Add these helpers and commands above `build_parser()`:

```python
def _bearer():
    return asc.Bearer()


def _config_path(args):
    return Path(args.config)


def _require_app_id(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")
    return config, app_id


def _locales_filter(plan, locales):
    if not locales:
        return plan
    wanted = set(locales.split(","))
    return {k: v for k, v in plan.items() if k in wanted}


def _print_actions(actions):
    for a in actions:
        print(f"  {a.get('locale', ''):<8} {a['type']:<32} {str(a.get('group')):<28} {a['mode']:<14} "
              f"+{a.get('place', 0)} -{a.get('unplace', 0)}", flush=True)


def cmd_assets_render(args):
    from . import render
    cfg_path = Path(args.assets) if args.assets else _config_path(args).resolve().parent / "assets.json"
    try:
        cfg = render.load_config(cfg_path)
        variants = args.variant or sorted(cfg.get("variants", {}))
        failed_any = False
        out_dir = Path(args.out) if args.out else cfg["_root"] / "assets-out"
        for name in variants:
            result = render.render_variant(cfg, name, out_dir, locales=args.locales.split(",") if args.locales else None,
                                           lint=not args.no_lint, strict_lint=args.strict_lint)
            print(f"{name}: {len(result['written'])} written → {out_dir / name}")
            for row in result["report"]:
                flags = [f for f, on in (("TIGHT", row["tight"]), ("fallback-headline", row["fallback"])) if on]
                if flags:
                    print(f"  {row['locale']:<8} verb {row['verb_px']}px×{row['verb_lines']}  desc {row['descriptor_px']}px×"
                          f"{row['descriptor_lines']}  device {row['device_width_pct']}%  {' '.join(flags)}")
            for locale, reason in sorted(result["failed"].items()):
                print(f"  FAILED {locale}: {reason}")
                failed_any = True
            if result["unlinted"]:
                print(f"  unlinted (needs native review): {', '.join(result['unlinted'])}")
    except render.RenderError as error:
        sys.exit(str(error))
    if failed_any:
        sys.exit(1)


def cmd_assets_status(args):
    _, app_id = _require_app_id(args)
    bearer = _bearer()
    catalog = library.Catalog.fetch(bearer)
    if args.catalog:
        print("\n".join(catalog.summary()))
        return
    lib = library.library_id(app_id, bearer)
    images = asc.call_all("GET", f"/appAssetLibraries/{lib}/images?limit=200", bearer)
    counts = {}
    for row in images:
        key = (row["attributes"].get("category"), row["attributes"].get("state"))
        counts[key] = counts.get(key, 0) + 1
    print(f"asset library {lib}: {len(images)} images")
    for (category, state), n in sorted(counts.items()):
        print(f"  {category:<30} {state:<24} {n}")
    version = asc.editable_version(app_id, bearer)
    if not version:
        print("no editable App Store version")
        return
    print(f"editable version {version['attributes']['versionString']} ({version['attributes']['appStoreState']}):")
    for locale, loc_id in sorted(asc._localizations(version["id"], bearer).items()):
        rows = [p for p in library.surface_placements("appStoreVersionLocalization", loc_id, bearer)
                if p["type"] in (library.HEADER, library.SEARCH)]
        line = ", ".join(f"{p['type'].split('_')[0].lower()}:{p['state']}" for p in rows) or "(no header/search assets)"
        print(f"  {locale:<8} {line}")


def _default_target(app_id, bearer):
    version = asc.editable_version(app_id, bearer)
    if not version or version["attributes"]["appStoreState"] not in library.VERSION_PLACEABLE:
        sys.exit("no App Store version in Prepare for Submission — create the next version in App Store Connect first; "
                 "default-page creatives ride with it")
    running = library.active_experiment(app_id, bearer)
    if running:
        sys.exit(f"product page optimization test '{running}' is in review or running — placements on the default page "
                 "are blocked while it runs; stop it or wait")
    return "appStoreVersionLocalization", asc._localizations(version["id"], bearer), "APP_STORE_VERSIONS"


def _creative_plan(args):
    plan = _locales_filter(creative.plan_from_directory(args.directory), args.locales)
    problems = creative.check(plan)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    if not plan:
        sys.exit(f"no <locale>.png files in {args.directory}")
    return plan


def _resolve_target(args, app_id, bearer):
    if args.target == "default":
        return _default_target(app_id, bearer)
    sys.exit(f"unknown target '{args.target}' — use 'default' or 'cpp:<page name>'")


def cmd_assets_push(args):
    _, app_id = _require_app_id(args)
    plan = _creative_plan(args)
    bearer = _bearer()
    parent_kind, parents, feature = _resolve_target(args, app_id, bearer)
    missing = sorted(set(plan) - set(parents))
    if missing:
        sys.exit(f"no localization on the target for: {', '.join(missing)} — nothing sent")
    catalog = library.Catalog.fetch(bearer)
    lib = library.library_id(app_id, bearer)
    requests = [{"locale": locale, "parent_kind": parent_kind, "parent_id": parents[locale],
                 "placement_types": [library.HEADER, library.SEARCH], "category": library.CREATIVE,
                 "files": [(path.name, path.read_bytes())]} for locale, path in sorted(plan.items())]
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        actions = library.sync_groups(requests, catalog, feature, lib, bearer, args.apply, ledger=book,
                                      command="assets push", progress=lambda a: _print_actions([a]))
    except asc.ASCError as error:
        print(f"\naborted — {error}\nRe-running is safe: uploads are reused and unchanged groups are skipped.", flush=True)
        sys.exit(1)
    unsupported = [a for a in actions if a["mode"] == "unsupported"]
    if unsupported:
        print(f"note: {len(unsupported)} placement(s) skipped — the catalog has no such type under {feature}")
    print("\napplied — verify in App Store Connect." if args.apply else "\nDRY RUN — nothing written. Re-run with --apply to push.")


def cmd_assets_submit(args):
    _, app_id = _require_app_id(args)
    plan = _creative_plan(args)
    bearer = _bearer()
    lib = library.library_id(app_id, bearer)
    uploader = library.Uploader(lib, bearer, args.apply)
    assets = {locale: uploader.ensure(path.name, path.read_bytes(), library.CREATIVE) for locale, path in sorted(plan.items())}
    if args.apply and uploader.new_ids:
        states = library.wait_processed(lib, uploader.new_ids, bearer)
        bad = [i for i, s in states.items() if s.get("state") not in library.PROCESSED]
        if bad:
            sys.exit(f"Apple did not accept {len(bad)} upload(s): {', '.join(bad)} — nothing submitted")
    items = [("appAssetLibraryImage", "appAssetLibraryImages", a["asset"]) for a in assets.values()]
    for locale, a in assets.items():
        print(f"  {locale:<8} {a['name']:<24} {a['status']}")
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        result = review.submit(app_id, items, bearer, args.apply, ledger=book, command="assets submit")
    except review.SubmissionBlocked as error:
        sys.exit(str(error))
    print(f"submission {result['submission']}: +{len(result['add'])} item(s)")
    print("submitted for review." if result["submitted"] else "\nDRY RUN — nothing written. Re-run with --apply to submit.")
```

4. In `build_parser()`, before `return parser`, add:

```python
    assets_command = subcommands.add_parser("assets", help="App Store creatives: header and search results assets")
    assets_sub = assets_command.add_subparsers(dest="assets_command", required=True)
    assets_render = assets_sub.add_parser("render", help="render creatives from assets.json (needs the 'render' extra)")
    assets_render.add_argument("--assets", help="path to assets.json (default: next to the config)")
    assets_render.add_argument("--variant", action="append", help="variant to render (repeatable; default: all)")
    assets_render.add_argument("--locales", help="comma-separated subset")
    assets_render.add_argument("--out", help="output directory (default: assets-out next to assets.json)")
    assets_render.add_argument("--no-lint", action="store_true", help="skip the App Store rejection lint")
    assets_render.add_argument("--strict-lint", action="store_true", help="fail locales whose language has no lint list")
    assets_render.set_defaults(func=cmd_assets_render)
    assets_status = assets_sub.add_parser("status", help="library, asset states and header/search placements")
    assets_status.add_argument("--app-id")
    assets_status.add_argument("--catalog", action="store_true", help="dump Apple's placement/spec catalog instead")
    assets_status.set_defaults(func=cmd_assets_status)
    assets_push = assets_sub.add_parser("push", help="place DIR/<locale>.png as header + search asset (dry run unless --apply)")
    assets_push.add_argument("directory")
    assets_push.add_argument("--target", required=True, help="'default' or 'cpp:<page name>'")
    assets_push.add_argument("--locales")
    assets_push.add_argument("--app-id")
    assets_push.add_argument("--apply", action="store_true")
    assets_push.set_defaults(func=cmd_assets_push)
    assets_submit = assets_sub.add_parser("submit", help="send DIR/<locale>.png to App Review on their own, placing nothing")
    assets_submit.add_argument("directory")
    assets_submit.add_argument("--locales")
    assets_submit.add_argument("--app-id")
    assets_submit.add_argument("--apply", action="store_true")
    assets_submit.set_defaults(func=cmd_assets_submit)
```

- [ ] **Step 8: Run tests**

Run: `python3.13 -m pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add asokit/review.py asokit/cli.py tests/test_review.py tests/test_cli.py
git commit -m "feat: guarded review submissions and assets render/status/push/submit commands"
```

---

## Phase B — Custom product pages

### Task 9: `cpp.json` load, expand and validate (pure)

**Files:**
- Create: `asokit/cpp.py`
- Modify: `asokit/screenshots.py` (add the legacy display-class map)
- Test: `tests/test_cpp.py`

**Interfaces:**
- Consumes: `creative.check`, `creative.lint` (Task 3); `screenshots.check` (existing); `library.reference_name` (Task 5, pure).
- Produces:
  - `screenshots.LEGACY_DISPLAY_CLASS` (dict legacy display type → `AppAssetLibraryDisplayClass`), `screenshots.LEGACY_BY_CLASS` (inverse; must be one-to-one).
  - `cpp.CppError(ValueError)`; constants `MAX_PAGES = 70`, `NAME_MAX = 30`, `PROMO_MAX = 170`, `EDITABLE`, `LOCKED`, `LIVE`.
  - `cpp.load(path) -> dict` (adds `"_root"`).
  - `cpp.expand(doc) -> list[page]`, page = `{"name", "deepLink", "template", "locales": {locale: {"promotionalText", "keywords": [str], "screenshots": [{"dir","order","display"}], "creative": str|None}}}`.
  - `cpp.norm(keyword) -> str`.
  - `cpp.select_screenshots(entry, root) -> list[Path]`.
  - `cpp.creative_path(doc, creative_root, variant, locale) -> Path`.
  - `cpp.check(doc, creative_root="assets-out", allow_protected=(), lint=True, online=None) -> (problems: list[str], warnings: list[str])`. `online` is the dict built by `cpp_apply.online_context` (Task 11) with keys `pools` ({locale: set(norm)}), `editable_pools` ({locale: set} or None), `live_locales` (set), `live_pages` (set of names), `live_keywords` ({name: {locale: set(norm)}}), `families` (set of legacy display names), `creative_supported` (bool).

- [ ] **Step 1: Add the display-class map to `screenshots.py`** (after `DISPLAY_SIZES`)

```python
# Legacy screenshot display types → Asset Library display classes. The only
# static table in the library path: placement groups themselves are read from
# Apple's catalog at run time.
LEGACY_DISPLAY_CLASS = {
    "APP_IPHONE_67": "IPHONE_DYNAMIC_ISLAND_LARGE_DISPLAY",
    "APP_IPHONE_61": "IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY",
    "APP_IPHONE_65": "IPHONE_FACE_ID_LARGE_DISPLAY",
    "APP_IPAD_PRO_3GEN_129": "IPAD_13_DISPLAY",
    "APP_IPAD_PRO_129": "IPAD_129_DISPLAY",
    "APP_WATCH_ULTRA": "WATCH_ULTRA",
    "APP_WATCH_SERIES_10": "WATCH_SERIES_10",
}
LEGACY_BY_CLASS = {value: key for key, value in LEGACY_DISPLAY_CLASS.items()}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_cpp.py
import json
import tempfile
import unittest
from pathlib import Path

from asokit import cpp, screenshots
from tests.test_creative import png_bytes


def make_doc(tmp, pages, protected=None):
    root = Path(tmp)
    shots_dir = root / "shots" / "en-US"
    shots_dir.mkdir(parents=True)
    for name in ("01-home.png", "02-stats.png", "06-entry.png"):
        (shots_dir / name).write_bytes(png_bytes(1290, 2796) + name.encode())
    for variant in ("bpd", "meds"):
        (root / "assets-out" / variant).mkdir(parents=True)
        for locale in ("en-US", "en-GB"):
            (root / "assets-out" / variant / f"{locale}.png").write_bytes(png_bytes(5244, 2950) + f"{variant}{locale}".encode())
    doc = {"pages": pages}
    if protected is not None:
        doc["protectedKeywords"] = protected
    (root / "cpp.json").write_text(json.dumps(doc))
    return cpp.load(root / "cpp.json")


def page(name="BPD tracker", keywords=("bpd", "borderline"), extra_locales=None, **fields):
    locales = {"en-US": {"promotionalText": "Log mood swings and triggers.", "keywords": list(keywords),
                         "screenshots": [{"dir": "shots/en-US", "order": ["06", "02"], "display": "APP_IPHONE_67"}],
                         "creative": "bpd"}}
    locales.update(extra_locales or {})
    return {"name": name, "template": "appStoreVersion", "deepLink": None, "locales": locales, **fields}


def online(**overrides):
    base = {"pools": {"en-US": {"bpd", "borderline", "medication", "triggers", "cyclothymia"},
                      "en-GB": {"bpd", "borderline", "symptom"}},
            "editable_pools": None, "live_locales": {"en-US", "en-GB"}, "live_pages": set(),
            "live_keywords": {}, "families": {"APP_IPHONE_67"}, "creative_supported": True}
    base.update(overrides)
    return base


class DisplayMapTests(unittest.TestCase):
    def test_inverse_is_one_to_one(self):
        self.assertEqual(len(screenshots.LEGACY_BY_CLASS), len(screenshots.LEGACY_DISPLAY_CLASS))


class ExpandTests(unittest.TestCase):
    def test_same_copies_media_and_promo_but_never_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = make_doc(tmp, [page(extra_locales={"en-GB": {"same": "en-US"}})])
            gb = cpp.expand(doc)[0]["locales"]["en-GB"]
            self.assertEqual(gb["keywords"], [])
            self.assertEqual(gb["creative"], "bpd")
            self.assertEqual(gb["promotionalText"], "Log mood swings and triggers.")

    def test_select_screenshots_by_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = make_doc(tmp, [page()])
            entry = cpp.expand(doc)[0]["locales"]["en-US"]["screenshots"][0]
            self.assertEqual([p.name for p in cpp.select_screenshots(entry, doc["_root"])], ["06-entry.png", "02-stats.png"])


class CheckTests(unittest.TestCase):
    def check(self, tmp, pages, **kwargs):
        protected = kwargs.pop("protected", None)
        return cpp.check(make_doc(tmp, pages, protected), **kwargs)

    def test_valid_page_passes_offline_and_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.check(tmp, [page()])[0], [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.check(tmp, [page()], online=online())[0], [])

    def test_name_and_promo_limits_and_lint(self):
        long_promo = page(name="X" * 31)
        long_promo["locales"]["en-US"]["promotionalText"] = "Free trial! " * 20
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [long_promo])
        text = "\n".join(problems)
        self.assertIn("30", text)
        self.assertIn("170", text)
        self.assertIn("free", text.lower())

    def test_keyword_owned_by_two_pages_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(), page(name="Meds", keywords=("bpd", "medication"))])
        self.assertTrue(any("bpd" in p and "BPD tracker" in p for p in problems))

    def test_live_page_not_in_file_owns_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page()], online=online(live_pages={"Old page"},
                                                                  live_keywords={"Old page": {"en-US": {"borderline"}}}))
        self.assertTrue(any("Old page" in p for p in problems))

    def test_empty_keyword_sets_on_two_pages_are_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=()), page(name="Report", keywords=())])
        self.assertEqual(problems, [])

    def test_protected_keyword_needs_override(self):
        protected = {"*": ["cyclothymia"]}
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=("bpd", "cyclothymia"))], protected=protected)
        self.assertTrue(any("protected" in p for p in problems))
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=("bpd", "cyclothymia"))], protected=protected,
                                     allow_protected=["cyclothymia"])
        self.assertEqual(problems, [])

    def test_keyword_must_be_in_live_pool_matched_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page(keywords=("BPD", "anxiety"))], online=online())
        self.assertEqual(len(problems), 1)
        self.assertIn("anxiety", problems[0])

    def test_editable_pool_drop_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, warnings = self.check(tmp, [page()], online=online(editable_pools={"en-US": {"bpd"}}))
        self.assertEqual(problems, [])
        self.assertTrue(any("borderline" in w for w in warnings))

    def test_locale_missing_from_live_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [page()], online=online(live_locales={"en-GB"}))
        self.assertTrue(any("en-US" in p for p in problems))

    def test_without_template_every_family_needs_screenshots(self):
        bare = page()
        bare.pop("template")
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [bare], online=online(families={"APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"}))
        self.assertTrue(any("APP_IPAD_PRO_3GEN_129" in p for p in problems))

    def test_missing_creative_file(self):
        bad = page()
        bad["locales"]["en-US"]["creative"] = "nope"
        with tempfile.TemporaryDirectory() as tmp:
            problems, _ = self.check(tmp, [bad])
        self.assertTrue(any("nope" in p for p in problems))

    def test_deep_link_warns_about_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, warnings = self.check(tmp, [page(deepLink="moodsync://log")])
        self.assertTrue(any("review" in w.lower() for w in warnings))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify failure**

Run: `python3.13 -m pytest tests/test_cpp.py -q`
Expected: FAIL — cannot import `cpp`.

- [ ] **Step 4: Implement**

```python
# asokit/cpp.py
"""Custom product pages as code: load, expand, validate and plan `cpp.json`.

Pure — no network. `cpp_apply.py` snapshots live state and executes the plans
built here. Format (see the spec for the full schema):

  {"protectedKeywords": {"*": [...], "en-US": [...]},
   "pages": [{"name": "...", "template": "appStoreVersion", "deepLink": null,
              "locales": {"en-US": {"promotionalText": "...", "keywords": [...],
                                    "screenshots": [{"dir", "order", "display"}],
                                    "creative": "<variant>"},
                          "en-GB": {"same": "en-US", "keywords": [...]}}}]}
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from . import creative
from . import screenshots as shots
from .library import HEADER, SEARCH, SCREENSHOT, reference_name

MAX_PAGES = 70
NAME_MAX = 30
PROMO_MAX = 170
EDITABLE = frozenset({"PREPARE_FOR_SUBMISSION", "REJECTED", "READY_FOR_REVIEW"})
LOCKED = frozenset({"WAITING_FOR_REVIEW", "IN_REVIEW"})
LIVE = frozenset({"ACCEPTED", "APPROVED"})
COPIED = ("promotionalText", "screenshots", "creative")
LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$")


class CppError(ValueError):
    pass


def load(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc["_root"] = Path(path).resolve().parent
    return doc


def norm(keyword):
    return " ".join(keyword.split()).casefold()


def expand(doc):
    pages = []
    for raw_page in doc.get("pages", []):
        raw = raw_page.get("locales", {})
        locales = {}
        for locale, entry in raw.items():
            if "same" in entry:
                target = raw.get(entry["same"])
                if target is None or "same" in target:
                    raise CppError(f"{raw_page.get('name')}: {locale} 'same' must name a locale with its own entry")
                resolved = {key: target.get(key) for key in COPIED}
                resolved.update({key: value for key, value in entry.items() if key in COPIED})
            else:
                resolved = {key: entry.get(key) for key in COPIED}
            resolved["keywords"] = [k.strip() for k in entry.get("keywords", []) if k.strip()]
            resolved["screenshots"] = resolved.get("screenshots") or []
            locales[locale] = resolved
        pages.append({"name": raw_page.get("name", ""), "deepLink": raw_page.get("deepLink"),
                      "template": raw_page.get("template"), "locales": locales})
    return pages


def select_screenshots(entry, root):
    directory = Path(root) / entry["dir"]
    if not directory.is_dir():
        raise CppError(f"screenshot dir {entry['dir']} does not exist")
    files = sorted(p for p in directory.iterdir() if p.suffix.lower() == ".png" and not p.name.startswith(("_", ".")))
    if not entry.get("order"):
        return files
    chosen = []
    for prefix in entry["order"]:
        hits = [p for p in files if p.name.startswith(prefix)]
        if len(hits) != 1:
            raise CppError(f"{entry['dir']}: order prefix '{prefix}' matches {len(hits)} files, expected 1")
        chosen.append(hits[0])
    return chosen


def creative_path(doc, creative_root, variant, locale):
    return Path(doc["_root"]) / creative_root / variant / f"{locale}.png"


def _protected(doc, locale):
    table = doc.get("protectedKeywords", {})
    return {norm(k) for k in table.get("*", []) + table.get(locale, [])}


def check(doc, creative_root="assets-out", allow_protected=(), lint=True, online=None):
    problems, warnings = [], []
    try:
        pages = expand(doc)
    except CppError as error:
        return [str(error)], []
    names = [p["name"] for p in pages]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"page name '{name}' appears more than once")
    allow = {norm(k) for k in allow_protected}
    owner = {}
    if online:
        for live_name, by_locale in online["live_keywords"].items():
            if live_name in names:
                continue
            for locale, keywords in by_locale.items():
                for keyword in keywords:
                    owner[(locale, keyword)] = live_name

    for page in pages:
        name = page["name"]
        if not name or len(name) > NAME_MAX:
            problems.append(f"page name '{name}' must be 1–{NAME_MAX} characters")
        if page["deepLink"]:
            if not urlparse(page["deepLink"]).scheme:
                problems.append(f"{name}: deepLink '{page['deepLink']}' has no scheme")
            else:
                warnings.append(f"{name}: deep-link changes require App Review before they work")
        declared_families = set()
        for locale, entry in sorted(page["locales"].items()):
            where = f"{name} {locale}"
            if not LOCALE_RE.match(locale):
                problems.append(f"{where}: '{locale}' is not an App Store Connect locale code")
            promo = entry.get("promotionalText") or ""
            if len(promo) > PROMO_MAX:
                problems.append(f"{where}: promotionalText is {len(promo)} characters, limit {PROMO_MAX}")
            if lint and promo:
                problems += [f"{where}: {hit}" for hit in creative.lint(promo, locale)]
            for shot in entry["screenshots"]:
                declared_families.add(shot.get("display"))
                try:
                    files = select_screenshots(shot, doc["_root"])
                except CppError as error:
                    problems.append(f"{where}: {error}")
                    continue
                problems += [f"{name}: {p}" for p in shots.check({locale: {shot["display"]: files}})]
            if entry.get("creative"):
                path = creative_path(doc, creative_root, entry["creative"], locale)
                if not path.exists():
                    problems.append(f"{where}: creative {path} not found (run `asokit assets render --variant {entry['creative']}`)")
                else:
                    problems += [f"{name}: {p}" for p in creative.check({locale: path})]
            seen = set()
            for keyword in (norm(k) for k in entry["keywords"]):
                if keyword in seen:
                    problems.append(f"{where}: keyword '{keyword}' listed twice")
                seen.add(keyword)
                if keyword in _protected(doc, locale) and keyword not in allow:
                    problems.append(f"{where}: '{keyword}' is protected (it carries the default page) — "
                                    f"pass --allow-protected {keyword} to assign it anyway")
                other = owner.get((locale, keyword))
                if other and other != name:
                    problems.append(f"{where}: keyword '{keyword}' already belongs to page '{other}' in {locale}")
                owner[(locale, keyword)] = name
                if online:
                    pool = online["pools"].get(locale)
                    if pool is not None and keyword not in pool:
                        problems.append(f"{where}: '{keyword}' is not in the {locale} keyword field of the live version "
                                        f"(available: {', '.join(sorted(pool))})")
                    editable = online.get("editable_pools")
                    if editable is not None and locale in editable and keyword not in editable[locale]:
                        warnings.append(f"{where}: '{keyword}' is missing from the next version's keyword field — "
                                        "routing stops when that version ships")
            if online and locale not in online["live_locales"]:
                problems.append(f"{where}: the live version has no {locale} localization")
        if online and page["template"] != "appStoreVersion":
            missing = sorted(online["families"] - declared_families)
            if missing:
                problems.append(f"{name}: no template, so every device family needs screenshots — missing {', '.join(missing)}")
        if online and not online["creative_supported"] and any(e.get("creative") for e in page["locales"].values()):
            warnings.append(f"{name}: Apple's catalog has no header/search placements for custom product pages — creatives skipped")
    total = len(set(names) | set(online["live_pages"])) if online else len(set(names))
    if total > MAX_PAGES:
        problems.append(f"{total} custom product pages (live + file) — App Store Connect allows {MAX_PAGES}")
    return problems, warnings
```

- [ ] **Step 5: Run tests**

Run: `python3.13 -m pytest tests/test_cpp.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add asokit/cpp.py asokit/screenshots.py tests/test_cpp.py
git commit -m "feat(cpp): load, expand and validate cpp.json with keyword ownership and protection"
```

---

### Task 10: CPP plan (pure)

**Files:**
- Modify: `asokit/cpp.py` (append)
- Test: `tests/test_cpp.py` (append)

**Interfaces:**
- Consumes: Task 9.
- Produces:
  - Snapshot shape (built by Task 11, consumed here): `{"id", "name", "url", "visible", "version": {"id", "state", "deepLink", "localizations": {locale: {"id", "promotionalText", "keywords": {norm: keyword_id}, "placements": [{"id","type","group","state","asset","sha"}]}}}}` — `version` is `None` when the page has no versions.
  - `cpp.desired_media(doc, entry, locale, creative_root) -> (list[list[sha]], sha | None)`.
  - `cpp.media_differs(media, placements, creative_supported) -> bool`.
  - `cpp.plan(page, snap, doc, creative_root="assets-out", locales=None, prune=False, creative_supported=True) -> list[action]`. Action `op` values: `create_page` (`deepLink`, `template`: bool, `locales`: {locale: promo}), `create_version` (`page_id`, `deepLink`), `update_deep_link` (`version`, `deepLink`), `create_localization` (`version`, `locale`, `promotionalText`), `update_promo` (`localization`, `locale`, `promotionalText`), `delete_localization` (`localization`, `locale`), `add_keywords` / `remove_keywords` (`localization`, `locale`, `keywords`: [norm]), `sync_media` (`localization`, `locale`), `skip` (`reason`). Every action carries `page` (name) and `live` (True when it edits a live version in place).
  - `cpp.ads_rows(pages, snapshots) -> list[dict]` with keys `page_name, page_id, page_url, visible, latest_state, locale, keywords, deep_link`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cpp.py`)

```python
from asokit.library import reference_name


def live_snap(doc, state="APPROVED", keywords=("bpd", "borderline"), promo="Log mood swings and triggers.",
              media=True, deep_link=None, locales=("en-US",)):
    root = doc["_root"]

    def placements(loc):
        if not media:
            return []
        rows = []
        for n, name in enumerate(("06-entry.png", "02-stats.png")):
            data = (root / "shots" / "en-US" / name).read_bytes()
            rows.append({"id": f"p{n}-{loc}", "type": "APP_SCREENSHOT", "group": "G_IPHONE_L", "state": "PARENT_APPROVED",
                         "asset": f"a{n}", "sha": reference_name(name, data)[1]})
        data = (root / "assets-out" / "bpd" / f"{loc}.png").read_bytes() if (root / "assets-out" / "bpd" / f"{loc}.png").exists() else b"x"
        sha = reference_name(f"{loc}.png", data)[1]
        rows += [{"id": f"ph-{loc}", "type": "PRODUCT_PAGE_HEADER_ASSET", "group": "G_HEADER", "state": "PARENT_APPROVED", "asset": "c", "sha": sha},
                 {"id": f"ps-{loc}", "type": "APP_STORE_SEARCH_RESULTS_ASSET", "group": "G_SEARCH", "state": "PARENT_APPROVED", "asset": "c", "sha": sha}]
        return rows

    return {"id": "page1", "name": "BPD tracker", "url": "https://apps.apple.com/x?ppid=1", "visible": True,
            "version": {"id": "ver1", "state": state, "deepLink": deep_link, "localizations": {
                loc: {"id": f"loc-{loc}", "promotionalText": promo, "keywords": {k: k for k in keywords},
                      "placements": placements(loc)} for loc in locales}}}


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = make_doc(self.tmp.name, [page(extra_locales={"en-GB": {"same": "en-US", "keywords": ["bpd", "borderline"]}})])
        self.page = cpp.expand(self.doc)[0]

    def ops(self, actions):
        return [a["op"] for a in actions]

    def test_missing_page_creates_then_previews_editable_work(self):
        actions = cpp.plan(self.page, None, self.doc)
        self.assertEqual(actions[0]["op"], "create_page")
        self.assertTrue(actions[0]["template"])
        self.assertEqual(set(actions[0]["locales"]), {"en-US", "en-GB"})
        self.assertIn("add_keywords", self.ops(actions))
        self.assertIn("sync_media", self.ops(actions))

    def test_live_unchanged_page_plans_nothing(self):
        snap = live_snap(self.doc, locales=("en-US", "en-GB"))
        self.assertEqual(cpp.plan(self.page, snap, self.doc), [])

    def test_live_promo_and_keyword_change_is_in_place(self):
        snap = live_snap(self.doc, keywords=("bpd",), promo="Old text", locales=("en-US", "en-GB"))
        actions = cpp.plan(self.page, snap, self.doc)
        self.assertNotIn("create_version", self.ops(actions))
        self.assertTrue(all(a["live"] for a in actions))
        self.assertEqual(sorted(self.ops(actions)), ["add_keywords", "add_keywords", "update_promo", "update_promo"])

    def test_live_media_change_needs_a_new_version(self):
        snap = live_snap(self.doc, media=False, locales=("en-US", "en-GB"))
        actions = cpp.plan(self.page, snap, self.doc)
        self.assertEqual(self.ops(actions), ["create_version"])

    def test_live_new_locale_needs_a_new_version(self):
        snap = live_snap(self.doc, locales=("en-US",))
        self.assertEqual(self.ops(cpp.plan(self.page, snap, self.doc)), ["create_version"])

    def test_in_review_is_skipped(self):
        snap = live_snap(self.doc, state="IN_REVIEW", locales=("en-US", "en-GB"))
        self.assertEqual(self.ops(cpp.plan(self.page, snap, self.doc)), ["skip"])

    def test_editable_version_full_diff(self):
        snap = live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", keywords=("bpd", "symptom"), media=False, locales=("en-US",))
        actions = cpp.plan(self.page, snap, self.doc)
        ops = self.ops(actions)
        self.assertIn("create_localization", ops)
        self.assertIn("remove_keywords", ops)
        self.assertEqual(ops.count("sync_media"), 2)
        self.assertFalse(any(a["live"] for a in actions))

    def test_locales_scope_never_deletes(self):
        snap = live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", locales=("en-US", "en-GB", "en-AU"))
        actions = cpp.plan(self.page, snap, self.doc, locales=["en-GB"], prune=True)
        self.assertNotIn("delete_localization", self.ops(actions))
        self.assertTrue(all(a.get("locale") in (None, "en-GB") for a in actions))

    def test_prune_deletes_but_never_the_last_localization(self):
        snap = live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", locales=("en-US", "en-GB", "en-AU"))
        actions = cpp.plan(self.page, snap, self.doc, prune=True)
        self.assertEqual([a["locale"] for a in actions if a["op"] == "delete_localization"], ["en-AU"])
        lone = cpp.expand(make_doc(tempfile.mkdtemp(), [page()]))[0]
        lone["locales"] = {}
        actions = cpp.plan(lone, live_snap(self.doc, state="PREPARE_FOR_SUBMISSION", locales=("en-AU",)), self.doc, prune=True)
        self.assertNotIn("delete_localization", self.ops(actions))

    def test_creative_ignored_when_unsupported(self):
        snap = live_snap(self.doc, locales=("en-US", "en-GB"))
        for loc in snap["version"]["localizations"].values():
            loc["placements"] = [p for p in loc["placements"] if p["type"] == "APP_SCREENSHOT"]
        self.assertEqual(cpp.plan(self.page, snap, self.doc, creative_supported=False), [])

    def test_ads_rows(self):
        snap = live_snap(self.doc, locales=("en-US", "en-GB"))
        rows = cpp.ads_rows([self.page], {"BPD tracker": snap})
        self.assertEqual({r["locale"] for r in rows}, {"en-US", "en-GB"})
        self.assertEqual(rows[0]["page_id"], "page1")
        self.assertEqual(rows[0]["keywords"], "bpd;borderline")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_cpp.py -q -k "Plan"`
Expected: FAIL — `AttributeError: module 'asokit.cpp' has no attribute 'plan'`.

- [ ] **Step 3: Implement** (append to `asokit/cpp.py`)

```python
def desired_media(doc, entry, locale, creative_root):
    screenshots = []
    for shot in entry["screenshots"]:
        screenshots.append([reference_name(p.name, p.read_bytes())[1] for p in select_screenshots(shot, doc["_root"])])
    creative_sha = None
    if entry.get("creative"):
        path = creative_path(doc, creative_root, entry["creative"], locale)
        creative_sha = reference_name(path.name, path.read_bytes())[1]
    return screenshots, creative_sha


def media_differs(media, placements, creative_supported):
    screenshots, creative_sha = media
    groups = {}
    for row in placements:
        groups.setdefault((row["type"], row["group"]), []).append(row.get("sha") or row.get("asset"))
    current_shots = [seq for (ptype, _), seq in groups.items() if ptype == SCREENSHOT]
    if any(seq not in current_shots for seq in screenshots):
        return True
    if creative_sha and creative_supported:
        creative_groups = [seq for (ptype, _), seq in groups.items() if ptype in (HEADER, SEARCH)]
        if not creative_groups or any(seq != [creative_sha] for seq in creative_groups):
            return True
    return False


def _keyword_actions(name, locale, localization, wanted, current, live):
    wanted_set = {norm(k) for k in wanted}
    current_set = set(current)
    actions = []
    add = sorted(wanted_set - current_set)
    remove = sorted(current_set - wanted_set)
    if add:
        actions.append({"op": "add_keywords", "page": name, "locale": locale, "localization": localization, "keywords": add, "live": live})
    if remove:
        actions.append({"op": "remove_keywords", "page": name, "locale": locale, "localization": localization, "keywords": remove, "live": live})
    return actions


def plan(page, snap, doc, creative_root="assets-out", locales=None, prune=False, creative_supported=True):
    name = page["name"]
    wanted = {loc: entry for loc, entry in page["locales"].items() if not locales or loc in locales}
    if snap is None or snap.get("version") is None:
        if snap is None:
            actions = [{"op": "create_page", "page": name, "deepLink": page["deepLink"], "live": False,
                        "template": page["template"] == "appStoreVersion",
                        "locales": {loc: entry.get("promotionalText") for loc, entry in sorted(wanted.items())}}]
            synthetic = {"id": None, "name": name, "url": None, "visible": False, "version": {
                "id": None, "state": "PREPARE_FOR_SUBMISSION", "deepLink": page["deepLink"],
                "localizations": {loc: {"id": None, "promotionalText": entry.get("promotionalText"), "keywords": {}, "placements": []}
                                  for loc, entry in wanted.items()}}}
            return actions + plan(page, synthetic, doc, creative_root, locales, prune, creative_supported)
        return [{"op": "create_version", "page": name, "page_id": snap["id"], "deepLink": page["deepLink"], "live": False}]

    version = snap["version"]
    state = version["state"]
    if state in LOCKED:
        return [{"op": "skip", "page": name, "reason": f"version {state} — in review; re-run after review", "live": False}]
    current = version["localizations"]
    media = {loc: desired_media(doc, entry, loc, creative_root) for loc, entry in wanted.items()}
    deep_link_changed = (page["deepLink"] or None) != (version.get("deepLink") or None)
    extras = [loc for loc in current if loc not in page["locales"]] if (prune and not locales) else []

    if state in LIVE:
        actions = []
        for loc, entry in sorted(wanted.items()):
            if loc not in current:
                continue
            here = current[loc]
            if (entry.get("promotionalText") or "") != (here.get("promotionalText") or ""):
                actions.append({"op": "update_promo", "page": name, "locale": loc, "localization": here["id"],
                                "promotionalText": entry.get("promotionalText") or "", "live": True})
            actions += _keyword_actions(name, loc, here["id"], entry["keywords"], here["keywords"], live=True)
        needs_version = (deep_link_changed or extras
                         or any(loc not in current for loc in wanted)
                         or any(media_differs(media[loc], current[loc]["placements"], creative_supported) for loc in wanted if loc in current))
        if needs_version:
            actions.append({"op": "create_version", "page": name, "page_id": snap["id"], "deepLink": page["deepLink"], "live": False})
        return actions

    actions = []
    if deep_link_changed and version["id"]:
        actions.append({"op": "update_deep_link", "page": name, "version": version["id"], "deepLink": page["deepLink"], "live": False})
    for loc, entry in sorted(wanted.items()):
        here = current.get(loc)
        if here is None:
            actions.append({"op": "create_localization", "page": name, "version": version["id"], "locale": loc,
                            "promotionalText": entry.get("promotionalText") or "", "live": False})
            here = {"id": None, "keywords": {}, "placements": []}
        elif (entry.get("promotionalText") or "") != (here.get("promotionalText") or ""):
            actions.append({"op": "update_promo", "page": name, "locale": loc, "localization": here["id"],
                            "promotionalText": entry.get("promotionalText") or "", "live": False})
        actions += _keyword_actions(name, loc, here["id"], entry["keywords"], here["keywords"], live=False)
        if media_differs(media[loc], here["placements"], creative_supported):
            actions.append({"op": "sync_media", "page": name, "locale": loc, "localization": here["id"], "live": False})
    created = sum(1 for a in actions if a["op"] == "create_localization")
    if extras and len(current) - len(extras) + created >= 1:
        for loc in sorted(extras):
            actions.append({"op": "delete_localization", "page": name, "locale": loc, "localization": current[loc]["id"], "live": False})
    return actions


def ads_rows(pages, snapshots):
    rows = []
    names = [p["name"] for p in pages] + sorted(n for n in snapshots if n not in {p["name"] for p in pages})
    by_name = {p["name"]: p for p in pages}
    for name in names:
        snap = snapshots.get(name) or {}
        version = snap.get("version") or {}
        page = by_name.get(name)
        locales = sorted(set((page or {}).get("locales", {})) | set(version.get("localizations", {})))
        for loc in locales:
            if page and loc in page["locales"]:
                keywords = [norm(k) for k in page["locales"][loc]["keywords"]]
            else:
                keywords = sorted(version["localizations"][loc]["keywords"])
            rows.append({"page_name": name, "page_id": snap.get("id") or "", "page_url": snap.get("url") or "",
                         "visible": snap.get("visible", ""), "latest_state": version.get("state", ""), "locale": loc,
                         "keywords": ";".join(keywords), "deep_link": (page or {}).get("deepLink") or version.get("deepLink") or ""})
    return rows
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest tests/test_cpp.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add asokit/cpp.py tests/test_cpp.py
git commit -m "feat(cpp): pure plan — in-place live edits, versions only for media/deep links, scoped pruning"
```

---
### Task 11: CPP live snapshot and online context

**Files:**
- Create: `asokit/cpp_apply.py`
- Modify: `tests/fakes.py` (append `FakeCppConnect`)
- Test: `tests/test_cpp_apply.py`

**Interfaces:**
- Consumes: `cpp.norm`, `cpp.expand` (Task 9); `library.surface_placements`, `library.Catalog`, `library.SCREENSHOT/HEADER/SEARCH` (Tasks 4–6); `screenshots.LEGACY_BY_CLASS` (Task 9); `asc._localizations`, `asc._screenshot_sets`, `asc.editable_version` (existing).
- Produces:
  - `cpp_apply.live_app_version(app_id, bearer) -> row | None` (state `READY_FOR_SALE` or `READY_FOR_DISTRIBUTION`).
  - `cpp_apply.keyword_pool(version_localization_id, bearer) -> {norm: keyword_id}`.
  - `cpp_apply.list_pages(app_id, bearer) -> list[row]`.
  - `cpp_apply.latest_version(page_id, bearer) -> row | None` (ignores `REPLACED_WITH_NEW_VERSION`, max numeric `version`).
  - `cpp_apply.snapshot_page(row, bearer, with_media=True) -> snapshot` (shape in Task 10).
  - `cpp_apply.online_context(app_id, doc, bearer, catalog) -> dict` with the Task 9 keys plus `pool_ids` ({locale: {norm: id}}), `snapshots` ({name: snapshot}), `live_version_id`.
  - `tests.fakes.FakeCppConnect` with helper `add_page(name, state="APPROVED", locales=None, visible=True) -> (page_id, version_id, {locale: loc_id})`.

- [ ] **Step 1: Append `FakeCppConnect` to `tests/fakes.py`**

```python
class FakeCppConnect(FakeConnect):
    """FakeConnect plus custom product pages, keyword pools and legacy screenshot sets."""

    POOL_US = ["mania", "depression", "hypomania", "episode", "medication", "mental", "health",
               "borderline", "cyclothymia", "bpd", "triggers", "adhd"]
    POOL_GB = ["symptom", "depression", "hypomania", "diary", "medication", "mental", "health",
               "borderline", "cyclothymia", "bpd", "triggers", "adhd"]

    def __init__(self):
        super().__init__()
        self.versions.append({"id": "v0", "attributes": {"appStoreState": "READY_FOR_SALE", "versionString": "2.2.0"}})
        self.version_locs["v0"] = {"en-US": "vl0-en", "en-GB": "vl0-gb"}
        self.version_locs["v1"] = {"en-US": "vl-en", "en-GB": "vl-gb"}
        self.pool = {"vl0-en": list(self.POOL_US), "vl0-gb": list(self.POOL_GB),
                     "vl-en": list(self.POOL_US), "vl-gb": list(self.POOL_GB)}
        self.legacy_sets = {"vl0-en": ["APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"]}
        self.pages = {}       # id -> {"name", "visible", "template"}
        self.cpp_versions = {}  # id -> {"page", "state", "deepLink", "version"}
        self.cpp_locs = {}      # id -> {"version", "locale", "promotionalText", "keywords": [ids]}
        self.create_visible = True
        self.prepopulate = False

    def add_page(self, name, state="APPROVED", locales=None, visible=True):
        page_id = self.next_id("page")
        self.pages[page_id] = {"name": name, "visible": visible, "template": None}
        version_id = self._new_version(page_id, state)
        loc_ids = {}
        for locale, spec in (locales or {}).items():
            loc_ids[locale] = self._new_loc(version_id, locale, spec.get("promo", ""), spec.get("keywords", []))
        return page_id, version_id, loc_ids

    def _new_version(self, page_id, state, deep_link=None):
        version_id = self.next_id("cv")
        number = 1 + sum(1 for v in self.cpp_versions.values() if v["page"] == page_id)
        self.cpp_versions[version_id] = {"page": page_id, "state": state, "deepLink": deep_link, "version": str(number)}
        return version_id

    def _new_loc(self, version_id, locale, promo, keywords):
        loc_id = self.next_id("cl")
        self.cpp_locs[loc_id] = {"version": version_id, "locale": locale, "promotionalText": promo, "keywords": list(keywords)}
        return loc_id

    def page_named(self, name):
        return next(pid for pid, p in self.pages.items() if p["name"] == name)

    def route(self, method, parts, query, body):
        result = super().route(method, parts, query, body)
        return result if result is not None else self.route_cpp(method, parts, query, body)

    def route_cpp(self, method, parts, query, body):
        if method == "GET" and len(parts) == 3 and parts[0] == "appStoreVersionLocalizations" and parts[2] == "searchKeywords":
            return {"data": [{"type": "appKeywords", "id": k} for k in self.pool.get(parts[1], [])]}
        if method == "GET" and len(parts) == 3 and parts[0] == "appStoreVersionLocalizations" and parts[2] == "appScreenshotSets":
            return {"data": [{"id": f"set-{t}", "attributes": {"screenshotDisplayType": t}} for t in self.legacy_sets.get(parts[1], [])]}
        if method == "GET" and len(parts) == 3 and parts[0] == "apps" and parts[2] == "appCustomProductPages":
            return {"data": [{"id": pid, "type": "appCustomProductPages",
                              "attributes": {"name": p["name"], "visible": p["visible"], "url": f"https://apps.apple.com/app/id1?ppid={pid}"}}
                             for pid, p in self.pages.items()]}
        if method == "POST" and parts == ["appCustomProductPages"]:
            return self._create_page(body)
        if method == "PATCH" and parts[:1] == ["appCustomProductPages"]:
            self.pages[parts[1]]["visible"] = body["data"]["attributes"]["visible"]
            return {"data": {"id": parts[1]}}
        if method == "GET" and len(parts) == 3 and parts[0] == "appCustomProductPages" and parts[2] == "appCustomProductPageVersions":
            return {"data": [{"id": vid, "type": "appCustomProductPageVersions",
                              "attributes": {"state": v["state"], "deepLink": v["deepLink"], "version": v["version"]}}
                             for vid, v in self.cpp_versions.items() if v["page"] == parts[1]]}
        if method == "POST" and parts == ["appCustomProductPageVersions"]:
            page_id = body["data"]["relationships"]["appCustomProductPage"]["data"]["id"]
            previous = [vid for vid, v in self.cpp_versions.items() if v["page"] == page_id]
            version_id = self._new_version(page_id, "PREPARE_FOR_SUBMISSION", body["data"].get("attributes", {}).get("deepLink"))
            if self.prepopulate and previous:
                for loc in [l for l in self.cpp_locs.values() if l["version"] == previous[-1]]:
                    self._new_loc(version_id, loc["locale"], loc["promotionalText"], loc["keywords"])
            return {"data": {"id": version_id, "type": "appCustomProductPageVersions"}}
        if method == "PATCH" and parts[:1] == ["appCustomProductPageVersions"]:
            self.cpp_versions[parts[1]]["deepLink"] = body["data"]["attributes"].get("deepLink")
            return {"data": {"id": parts[1]}}
        if method == "GET" and len(parts) == 3 and parts[0] == "appCustomProductPageVersions" and parts[2] == "appCustomProductPageLocalizations":
            return {"data": [{"id": lid, "type": "appCustomProductPageLocalizations",
                              "attributes": {"locale": l["locale"], "promotionalText": l["promotionalText"]}}
                             for lid, l in self.cpp_locs.items() if l["version"] == parts[1]]}
        if method == "POST" and parts == ["appCustomProductPageLocalizations"]:
            version_id = body["data"]["relationships"]["appCustomProductPageVersion"]["data"]["id"]
            attrs = body["data"]["attributes"]
            return {"data": {"id": self._new_loc(version_id, attrs["locale"], attrs.get("promotionalText", ""), [])}}
        if method == "PATCH" and parts[:1] == ["appCustomProductPageLocalizations"]:
            self.cpp_locs[parts[1]]["promotionalText"] = body["data"]["attributes"]["promotionalText"]
            return {"data": {"id": parts[1]}}
        if method == "DELETE" and parts[:1] == ["appCustomProductPageLocalizations"] and len(parts) == 2:
            self.cpp_locs.pop(parts[1])
            return {}
        if method == "GET" and len(parts) == 3 and parts[0] == "appCustomProductPageLocalizations" and parts[2] == "searchKeywords":
            return {"data": [{"type": "appKeywords", "id": k} for k in self.cpp_locs[parts[1]]["keywords"]]}
        if len(parts) == 4 and parts[0] == "appCustomProductPageLocalizations" and parts[2:] == ["relationships", "searchKeywords"]:
            ids = [item["id"] for item in body["data"]]
            keywords = self.cpp_locs[parts[1]]["keywords"]
            if method == "POST":
                keywords.extend(i for i in ids if i not in keywords)
            elif method == "DELETE":
                self.cpp_locs[parts[1]]["keywords"] = [k for k in keywords if k not in ids]
            return {}
        return None

    def _create_page(self, body):
        data = body["data"]
        page_id = self.next_id("page")
        template = data["relationships"].get("appStoreVersionTemplate")
        self.pages[page_id] = {"name": data["attributes"]["name"], "visible": self.create_visible,
                               "template": template and template["data"]["id"]}
        included = body.get("included", [])
        version_item = next(i for i in included if i["type"] == "appCustomProductPageVersions")
        assert data["relationships"]["appCustomProductPageVersions"]["data"][0]["id"] == version_item["id"]
        version_id = self._new_version(page_id, "PREPARE_FOR_SUBMISSION", version_item.get("attributes", {}).get("deepLink"))
        wanted = {ref["id"] for ref in version_item["relationships"]["appCustomProductPageLocalizations"]["data"]}
        for item in included:
            if item["type"] == "appCustomProductPageLocalizations":
                assert item["id"] in wanted and item["id"].startswith("${")
                self._new_loc(version_id, item["attributes"]["locale"], item["attributes"].get("promotionalText", ""), [])
        return {"data": {"id": page_id, "type": "appCustomProductPages", "attributes": {"visible": self.create_visible}}}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_cpp_apply.py
import json
import unittest
from pathlib import Path

from asokit import cpp, cpp_apply, library
from tests.fakes import FakeCppConnect, install
from tests.test_cpp import make_doc, page


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeCppConnect())

    def test_latest_version_ignores_replaced(self):
        page_id, first, _ = self.fake.add_page("BPD tracker", state="REPLACED_WITH_NEW_VERSION")
        second = self.fake._new_version(page_id, "APPROVED")
        self.assertEqual(cpp_apply.latest_version(page_id, "t")["id"], second)

    def test_snapshot_reads_promo_keywords_and_placements(self):
        _, version_id, locs = self.fake.add_page("BPD tracker", locales={"en-US": {"promo": "Hi", "keywords": ["bpd"]}})
        row = cpp_apply.list_pages("1", "t")[0]
        snap = cpp_apply.snapshot_page(row, "t")
        loc = snap["version"]["localizations"]["en-US"]
        self.assertEqual((snap["version"]["id"], snap["version"]["state"]), (version_id, "APPROVED"))
        self.assertEqual((loc["promotionalText"], loc["keywords"]), ("Hi", {"bpd": "bpd"}))
        self.assertEqual(loc["placements"], [])

    def test_online_context(self):
        self.fake.add_page("Old page", locales={"en-US": {"keywords": ["adhd"]}})
        with self._doc() as doc:
            ctx = cpp_apply.online_context("1", doc, "t", library.Catalog.fetch("t"))
        self.assertIn("bpd", ctx["pools"]["en-US"])
        self.assertIn("symptom", ctx["pools"]["en-GB"])
        self.assertEqual(ctx["live_locales"], {"en-US", "en-GB"})
        self.assertEqual(ctx["live_keywords"]["Old page"], {"en-US": {"adhd"}})
        self.assertEqual(ctx["families"], {"APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"})
        self.assertTrue(ctx["creative_supported"])
        self.assertEqual(ctx["live_version_id"], "v0")
        self.assertIsNotNone(ctx["editable_pools"])

    def _doc(self):
        import contextlib
        import tempfile

        @contextlib.contextmanager
        def manager():
            with tempfile.TemporaryDirectory() as tmp:
                yield make_doc(tmp, [page()])
        return manager()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify failure**

Run: `python3.13 -m pytest tests/test_cpp_apply.py -q`
Expected: FAIL — cannot import `cpp_apply`.

- [ ] **Step 4: Implement**

```python
# asokit/cpp_apply.py
"""Execute `cpp.json` plans against App Store Connect.

Reads live state into the snapshot shape `cpp.plan` consumes, runs the
online half of `cpp.check`, and applies plans: page/version/localization
writes, keyword links, and media via the Asset Library (`library.sync_groups`).
New pages are created hidden; only `publish` changes visibility; only
`submit` (through `review.submit`) sends anything to App Review.
"""
import re

from . import asc, cpp, library, review
from . import screenshots as shots
from .ledger import NULL

LIVE_APP_STATES = frozenset({"READY_FOR_SALE", "READY_FOR_DISTRIBUTION"})
FEATURE = "CUSTOM_PRODUCT_PAGES"


def _app_state(row):
    attrs = row.get("attributes") or {}
    return attrs.get("appStoreState") or attrs.get("appVersionState")


def live_app_version(app_id, bearer):
    for row in asc.call("GET", f"/apps/{app_id}/appStoreVersions?limit=10", bearer).get("data", []):
        if _app_state(row) in LIVE_APP_STATES:
            return row
    return None


def keyword_pool(version_localization_id, bearer):
    rows = asc.call_all("GET", f"/appStoreVersionLocalizations/{version_localization_id}/searchKeywords?limit=200", bearer)
    return {cpp.norm(row["id"]): row["id"] for row in rows}


def list_pages(app_id, bearer):
    return asc.call_all("GET", f"/apps/{app_id}/appCustomProductPages?limit=200", bearer)


def _version_key(row):
    text = (row.get("attributes") or {}).get("version") or ""
    return tuple(int(n) for n in re.findall(r"\d+", text)), text


def latest_version(page_id, bearer):
    rows = [row for row in asc.call_all("GET", f"/appCustomProductPages/{page_id}/appCustomProductPageVersions?limit=200", bearer)
            if (row.get("attributes") or {}).get("state") != "REPLACED_WITH_NEW_VERSION"]
    return max(rows, key=_version_key) if rows else None


def snapshot_page(row, bearer, with_media=True):
    attrs = row.get("attributes") or {}
    snap = {"id": row["id"], "name": attrs.get("name"), "url": attrs.get("url"), "visible": attrs.get("visible"), "version": None}
    version = latest_version(row["id"], bearer)
    if version is None:
        return snap
    localizations = {}
    for loc in asc.call_all("GET", f"/appCustomProductPageVersions/{version['id']}/appCustomProductPageLocalizations?limit=200", bearer):
        loc_attrs = loc.get("attributes") or {}
        keywords = asc.call_all("GET", f"/appCustomProductPageLocalizations/{loc['id']}/searchKeywords?limit=200", bearer)
        localizations[loc_attrs["locale"]] = {
            "id": loc["id"], "promotionalText": loc_attrs.get("promotionalText"),
            "keywords": {cpp.norm(k["id"]): k["id"] for k in keywords},
            "placements": library.surface_placements("appCustomProductPageLocalization", loc["id"], bearer) if with_media else [],
        }
    version_attrs = version.get("attributes") or {}
    snap["version"] = {"id": version["id"], "state": version_attrs.get("state"), "deepLink": version_attrs.get("deepLink"),
                       "localizations": localizations}
    return snap


def _families(live_locs, bearer, catalog):
    if not live_locs:
        return set()
    loc_id = live_locs.get("en-US") or next(iter(live_locs.values()))
    groups = {row["group"] for row in library.surface_placements("appStoreVersionLocalization", loc_id, bearer)
              if row["type"] == library.SCREENSHOT}
    families = {shots.LEGACY_BY_CLASS.get(catalog.display_class(g)) for g in groups} - {None}
    if families:
        return families
    # Screenshots uploaded through the deprecated set API may not appear as placements.
    return set(asc._screenshot_sets(loc_id, bearer))


def online_context(app_id, doc, bearer, catalog):
    live = live_app_version(app_id, bearer)
    if live is None:
        raise asc.ASCError("the app has no version on sale — custom product pages need one Ready for Distribution")
    live_locs = asc._localizations(live["id"], bearer)
    pool_ids = {locale: keyword_pool(loc_id, bearer) for locale, loc_id in live_locs.items()}
    editable = asc.editable_version(app_id, bearer)
    editable_pools = None
    if editable:
        editable_pools = {locale: set(keyword_pool(loc_id, bearer)) for locale, loc_id in asc._localizations(editable["id"], bearer).items()}
    in_file = {p["name"] for p in cpp.expand(doc)}
    snapshots = {}
    for row in list_pages(app_id, bearer):
        name = (row.get("attributes") or {}).get("name")
        snapshots[name] = snapshot_page(row, bearer, with_media=name in in_file)
    live_keywords = {name: {locale: set(loc["keywords"]) for locale, loc in ((snap["version"] or {}).get("localizations") or {}).items()}
                     for name, snap in snapshots.items()}
    return {
        "pools": {locale: set(ids) for locale, ids in pool_ids.items()}, "pool_ids": pool_ids,
        "editable_pools": editable_pools, "live_locales": set(live_locs), "live_pages": set(snapshots),
        "live_keywords": live_keywords, "families": _families(live_locs, bearer, catalog),
        "creative_supported": catalog.supports(FEATURE, library.HEADER) and catalog.supports(FEATURE, library.SEARCH),
        "snapshots": snapshots, "live_version_id": live["id"],
    }
```

(`review` and `NULL` are used by Tasks 12–13.)

- [ ] **Step 5: Run tests**

Run: `python3.13 -m pytest tests/test_cpp_apply.py -q`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add asokit/cpp_apply.py tests/fakes.py tests/test_cpp_apply.py
git commit -m "feat(cpp): live snapshot of custom product pages and online validation context"
```

---

### Task 12: CPP push executor

**Files:**
- Modify: `asokit/cpp_apply.py` (append)
- Test: `tests/test_cpp_apply.py` (append)

**Interfaces:**
- Consumes: Tasks 9–11, `library.sync_groups`, `library.library_id`.
- Produces:
  - `cpp_apply.create_page_body(app_id, name, deep_link, locales, template_version_id) -> dict`.
  - `cpp_apply.push(app_id, doc, bearer, apply, creative_root="assets-out", pages=None, locales=None, prune=False, allow_protected=(), lint=True, ledger=NULL, out=print) -> {"problems", "warnings", "actions", "context"}`.
  - `cpp_apply.describe(action) -> str` (one-line human description, used by the CLI).

- [ ] **Step 1: Write the failing tests** (append)

```python
import tempfile

from tests.test_creative import png_bytes


class PushTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeCppConnect())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = make_doc(self.tmp.name, [page(extra_locales={"en-GB": {"same": "en-US", "keywords": ["bpd", "borderline"]}})])
        self.lines = []

    def push(self, apply=True, **kwargs):
        return cpp_apply.push("1", self.doc, "t", apply, out=self.lines.append, **kwargs)

    def test_dry_run_new_page_writes_nothing(self):
        result = self.push(apply=False)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["actions"][0]["op"], "create_page")
        self.assertEqual(self.fake.writes(), [])

    def test_apply_creates_hidden_page_with_keywords_and_media(self):
        result = self.push()
        self.assertEqual(result["problems"], [])
        page_id = self.fake.page_named("BPD tracker")
        self.assertFalse(self.fake.pages[page_id]["visible"])
        self.assertEqual(self.fake.pages[page_id]["template"], "v0")
        locs = {l["locale"]: (lid, l) for lid, l in self.fake.cpp_locs.items()}
        self.assertEqual(sorted(locs["en-US"][1]["keywords"]), ["borderline", "bpd"])
        en_us = locs["en-US"][0]
        self.assertEqual(self.fake.group(en_us, "G_IPHONE_L"), ["06-entry.png", "02-stats.png"])
        self.assertEqual(self.fake.group(en_us, "G_HEADER"), ["en-US.png"])
        self.assertEqual(self.fake.group(en_us, "G_SEARCH"), ["en-US.png"])

    def test_second_push_is_a_no_op(self):
        self.push()
        before = len(self.fake.writes())
        result = self.push()
        self.assertEqual([a for a in result["actions"]], [])
        self.assertEqual(len(self.fake.writes()), before)

    def test_live_page_keyword_change_applies_in_place(self):
        self.push()
        page_id = self.fake.page_named("BPD tracker")
        for version in self.fake.cpp_versions.values():
            if version["page"] == page_id:
                version["state"] = "APPROVED"
        for loc in self.fake.cpp_locs.values():
            loc["keywords"] = ["bpd"]
        versions_before = len(self.fake.cpp_versions)
        self.push()
        self.assertEqual(len(self.fake.cpp_versions), versions_before)
        self.assertTrue(all(sorted(l["keywords"]) == ["borderline", "bpd"] for l in self.fake.cpp_locs.values()))

    def test_live_media_change_creates_version_and_fills_it(self):
        self.push()
        page_id = self.fake.page_named("BPD tracker")
        for version in self.fake.cpp_versions.values():
            version["state"] = "APPROVED"
        self.doc["pages"][0]["locales"]["en-US"]["screenshots"][0]["order"] = ["02", "06"]
        self.push()
        versions = [v for v in self.fake.cpp_versions.values() if v["page"] == page_id]
        self.assertEqual(len(versions), 2)
        newest = max(self.fake.cpp_versions, key=lambda vid: int(self.fake.cpp_versions[vid]["version"]))
        new_locs = {l["locale"]: lid for lid, l in self.fake.cpp_locs.items() if l["version"] == newest}
        self.assertEqual(set(new_locs), {"en-US", "en-GB"})
        self.assertEqual(self.fake.group(new_locs["en-US"], "G_IPHONE_L"), ["02-stats.png", "06-entry.png"])

    def test_prepopulated_new_version_is_not_duplicated(self):
        self.fake.prepopulate = True
        self.test_live_media_change_creates_version_and_fills_it()

    def test_validation_problems_stop_before_any_write(self):
        self.doc["pages"][0]["locales"]["en-US"]["keywords"] = ["anxiety"]
        result = self.push()
        self.assertTrue(result["problems"])
        self.assertEqual(self.fake.writes(), [])

    def test_pages_scope(self):
        self.doc["pages"].append(page(name="Report", keywords=()))
        self.push(pages=["Report"])
        self.assertEqual([p["name"] for p in self.fake.pages.values()], ["Report"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_cpp_apply.py -q -k Push`
Expected: FAIL — `AttributeError: ... 'push'`.

- [ ] **Step 3: Implement** (append to `asokit/cpp_apply.py`)

```python
def create_page_body(app_id, name, deep_link, locales, template_version_id):
    version_ref = "${new-version}"
    loc_refs = [f"${{new-loc-{index}}}" for index in range(len(locales))]
    included = [{
        "type": "appCustomProductPageVersions", "id": version_ref,
        "attributes": {"deepLink": deep_link} if deep_link else {},
        "relationships": {"appCustomProductPageLocalizations": {"data": [
            {"type": "appCustomProductPageLocalizations", "id": ref} for ref in loc_refs]}},
    }]
    for ref, (locale, promo) in zip(loc_refs, sorted(locales.items())):
        attributes = {"locale": locale}
        if promo:
            attributes["promotionalText"] = promo
        included.append({"type": "appCustomProductPageLocalizations", "id": ref, "attributes": attributes})
    relationships = {
        "app": {"data": {"type": "apps", "id": str(app_id)}},
        "appCustomProductPageVersions": {"data": [{"type": "appCustomProductPageVersions", "id": version_ref}]},
    }
    if template_version_id:
        relationships["appStoreVersionTemplate"] = {"data": {"type": "appStoreVersions", "id": template_version_id}}
    return {"data": {"type": "appCustomProductPages", "attributes": {"name": name}, "relationships": relationships},
            "included": included}


def _visible_body(page_id, visible):
    return {"data": {"type": "appCustomProductPages", "id": page_id, "attributes": {"visible": visible}}}


def describe(action):
    op = action["op"]
    where = f"{action['page']}" + (f" {action['locale']}" if action.get("locale") else "")
    live = " (live, in place)" if action.get("live") else ""
    if op in ("add_keywords", "remove_keywords"):
        return f"  {op:<20} {where}: {', '.join(action['keywords'])}{live}"
    if op == "create_page":
        return f"  create_page          {action['page']} (hidden; locales {', '.join(action['locales'])}; template {action['template']})"
    if op == "skip":
        return f"  skip                 {action['page']}: {action['reason']}"
    return f"  {op:<20} {where}{live}"


def _refresh(app_id, name, bearer):
    for row in list_pages(app_id, bearer):
        if (row.get("attributes") or {}).get("name") == name:
            return snapshot_page(row, bearer)
    return None


def _keyword_body(ids):
    return {"data": [{"type": "appKeywords", "id": i} for i in ids]}


def _execute(app_id, page, snap, actions, doc, ctx, catalog, lib, bearer, creative_root, ledger, out):
    """Apply one plan. Returns True when a page/version was created and the caller must re-plan."""
    name = page["name"]
    localizations = ((snap or {}).get("version") or {}).get("localizations") or {}
    loc_ids = {locale: loc["id"] for locale, loc in localizations.items()}
    media = []
    for action in actions:
        op = action["op"]
        if op == "skip":
            continue
        if op == "create_page":
            template = ctx["live_version_id"] if action["template"] else None
            created = asc.call("POST", "/appCustomProductPages", bearer,
                               create_page_body(app_id, name, action["deepLink"], action["locales"], template))["data"]
            if (created.get("attributes") or {}).get("visible"):
                asc.call("PATCH", f"/appCustomProductPages/{created['id']}", bearer, _visible_body(created["id"], False))
            ledger.record("cpp push", "create_page", page_name=name, page_id=created["id"])
            return True
        if op == "create_version":
            attributes = {"deepLink": action["deepLink"]} if action["deepLink"] else {}
            created = asc.call("POST", "/appCustomProductPageVersions", bearer, {"data": {
                "type": "appCustomProductPageVersions", "attributes": attributes,
                "relationships": {"appCustomProductPage": {"data": {"type": "appCustomProductPages", "id": action["page_id"]}}},
            }})["data"]
            ledger.record("cpp push", "create_version", page_name=name, page_id=action["page_id"], version_id=created["id"])
            return True
        locale = action.get("locale")
        if op == "update_deep_link":
            asc.call("PATCH", f"/appCustomProductPageVersions/{action['version']}", bearer, {"data": {
                "type": "appCustomProductPageVersions", "id": action["version"], "attributes": {"deepLink": action["deepLink"]}}})
        elif op == "create_localization":
            created = asc.call("POST", "/appCustomProductPageLocalizations", bearer, {"data": {
                "type": "appCustomProductPageLocalizations",
                "attributes": {"locale": locale, "promotionalText": action["promotionalText"]},
                "relationships": {"appCustomProductPageVersion": {"data": {"type": "appCustomProductPageVersions", "id": action["version"]}}},
            }})["data"]
            loc_ids[locale] = created["id"]
        elif op == "update_promo":
            asc.call("PATCH", f"/appCustomProductPageLocalizations/{action['localization']}", bearer, {"data": {
                "type": "appCustomProductPageLocalizations", "id": action["localization"],
                "attributes": {"promotionalText": action["promotionalText"]}}})
        elif op == "delete_localization":
            asc.call("DELETE", f"/appCustomProductPageLocalizations/{action['localization']}", bearer)
        elif op == "add_keywords":
            ids = [ctx["pool_ids"][locale][k] for k in action["keywords"]]
            target = action["localization"] or loc_ids[locale]
            asc.call("POST", f"/appCustomProductPageLocalizations/{target}/relationships/searchKeywords", bearer, _keyword_body(ids))
        elif op == "remove_keywords":
            ids = [localizations[locale]["keywords"][k] for k in action["keywords"]]
            asc.call("DELETE", f"/appCustomProductPageLocalizations/{action['localization']}/relationships/searchKeywords",
                     bearer, _keyword_body(ids))
        elif op == "sync_media":
            media.append(action)
            continue
        ledger.record("cpp push", op, page_name=name, locale=locale, live=action.get("live") or None,
                      keywords=action.get("keywords"))

    requests = []
    for action in media:
        entry = page["locales"][action["locale"]]
        parent = action["localization"] or loc_ids[action["locale"]]
        for shot in entry["screenshots"]:
            files = cpp.select_screenshots(shot, doc["_root"])
            requests.append({"locale": action["locale"], "parent_kind": "appCustomProductPageLocalization", "parent_id": parent,
                             "placement_types": [library.SCREENSHOT], "category": library.MEDIA,
                             "display_class": shots.LEGACY_DISPLAY_CLASS.get(shot["display"]),
                             "files": [(p.name, p.read_bytes()) for p in files]})
        if entry.get("creative") and ctx["creative_supported"]:
            path = cpp.creative_path(doc, creative_root, entry["creative"], action["locale"])
            requests.append({"locale": action["locale"], "parent_kind": "appCustomProductPageLocalization", "parent_id": parent,
                             "placement_types": [library.HEADER, library.SEARCH], "category": library.CREATIVE,
                             "files": [(path.name, path.read_bytes())]})
    if requests:
        library.sync_groups(requests, catalog, FEATURE, lib, bearer, True, ledger=ledger, command="cpp push",
                            progress=lambda a: out(f"    {a.get('locale', ''):<8} {a['type']:<32} {a['mode']}"))
    return False


def push(app_id, doc, bearer, apply, creative_root="assets-out", pages=None, locales=None, prune=False,
         allow_protected=(), lint=True, ledger=NULL, out=print):
    catalog = library.Catalog.fetch(bearer)
    ctx = online_context(app_id, doc, bearer, catalog)
    problems, warnings = cpp.check(doc, creative_root, allow_protected, lint, online=ctx)
    result = {"problems": problems, "warnings": warnings, "actions": [], "context": ctx}
    selected = [p for p in cpp.expand(doc) if not pages or p["name"] in pages] if not problems else []
    unknown = sorted(set(pages or []) - {p["name"] for p in cpp.expand(doc)}) if not problems else []
    if unknown:
        result["problems"].append(f"not in the file: {', '.join(unknown)}")
    if result["problems"]:
        return result
    lib = library.library_id(app_id, bearer)
    for page in selected:
        snap = ctx["snapshots"].get(page["name"])
        for _ in range(3):
            actions = cpp.plan(page, snap, doc, creative_root, locales, prune, ctx["creative_supported"])
            for action in actions:
                out(describe(action))
            if not apply or not actions or all(a["op"] == "skip" for a in actions):
                result["actions"] += actions
                break
            replan = _execute(app_id, page, snap, actions, doc, ctx, catalog, lib, bearer, creative_root, ledger, out)
            if not replan:
                result["actions"] += actions
                break
            result["actions"].append(next(a for a in actions if a["op"] in ("create_page", "create_version")))
            snap = _refresh(app_id, page["name"], bearer)
    return result
```

Note on `test_second_push_is_a_no_op`: after the first push the page's version is `PREPARE_FOR_SUBMISSION` with all localizations, keywords and placements matching, so `cpp.plan` returns `[]` and `result["actions"]` is empty.

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest tests/test_cpp_apply.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add asokit/cpp_apply.py tests/test_cpp_apply.py
git commit -m "feat(cpp): push executor — hidden page creation, in-place live edits, media via the library"
```

---

### Task 13: `publish` and `submit`

**Files:**
- Modify: `asokit/cpp_apply.py` (append)
- Test: `tests/test_cpp_apply.py` (append)

**Interfaces:**
- Consumes: Tasks 8 (`review.submit`), 11–12.
- Produces:
  - `cpp_apply.PublishError(asc.ASCError)`.
  - `cpp_apply.publish(app_id, names, bearer, apply, hide=False, ledger=NULL, out=print) -> list[dict]` (`{"page", "from", "to", "keywords": {locale: [kw]}}`).
  - `cpp_apply.submit(app_id, doc, names, bearer, apply, ledger=NULL, out=print) -> dict` (the `review.submit` result).

- [ ] **Step 1: Write the failing tests** (append)

```python
from asokit import review


class PublishSubmitTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeCppConnect())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = make_doc(self.tmp.name, [page()])
        cpp_apply.push("1", self.doc, "t", True, out=lambda line: None)
        self.page_id = self.fake.page_named("BPD tracker")

    def set_state(self, state):
        for version in self.fake.cpp_versions.values():
            version["state"] = state

    def test_publish_refuses_unapproved(self):
        with self.assertRaises(cpp_apply.PublishError):
            cpp_apply.publish("1", ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertFalse(self.fake.pages[self.page_id]["visible"])

    def test_publish_and_hide(self):
        self.set_state("APPROVED")
        changes = cpp_apply.publish("1", ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertTrue(self.fake.pages[self.page_id]["visible"])
        self.assertEqual(changes[0]["keywords"]["en-US"], ["borderline", "bpd"])
        cpp_apply.publish("1", ["BPD tracker"], "t", apply=True, hide=True, out=lambda line: None)
        self.assertFalse(self.fake.pages[self.page_id]["visible"])

    def test_publish_dry_run_changes_nothing(self):
        self.set_state("APPROVED")
        cpp_apply.publish("1", ["BPD tracker"], "t", apply=False, out=lambda line: None)
        self.assertFalse(self.fake.pages[self.page_id]["visible"])

    def test_submit_adds_only_the_named_page_version(self):
        result = cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
        items = self.fake.submissions[result["submission"]]["items"]
        self.assertEqual([i[0] for i in items], ["appCustomProductPageVersion"])

    def test_submit_refuses_failed_placement(self):
        for placement in self.fake.placements.values():
            placement["state_override"] = "FAILED"
        original = self.fake._surface

        def failing(kind, parent):
            result = original(kind, parent)
            for row in result["data"]:
                row["attributes"]["state"] = "FAILED"
            return result
        self.fake._surface = failing
        with self.assertRaises(review.SubmissionBlocked):
            cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
        self.assertEqual(self.fake.submissions, {})

    def test_submit_refuses_in_review_page(self):
        self.set_state("IN_REVIEW")
        with self.assertRaises(review.SubmissionBlocked):
            cpp_apply.submit("1", self.doc, ["BPD tracker"], "t", apply=True, out=lambda line: None)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_cpp_apply.py -q -k PublishSubmit`
Expected: FAIL — missing `publish`.

- [ ] **Step 3: Implement** (append)

```python
class PublishError(asc.ASCError):
    pass


def _page_row(app_id, name, bearer):
    for row in list_pages(app_id, bearer):
        if (row.get("attributes") or {}).get("name") == name:
            return row
    raise PublishError(f"no custom product page named '{name}' in App Store Connect")


def publish(app_id, names, bearer, apply, hide=False, ledger=NULL, out=print):
    """Make pages visible (organic routing goes live) or hide them."""
    changes = []
    for name in names:
        row = _page_row(app_id, name, bearer)
        snap = snapshot_page(row, bearer, with_media=False)
        state = (snap["version"] or {}).get("state")
        if not hide and state not in cpp.LIVE:
            raise PublishError(f"'{name}' latest version is {state} — publish only after Apple approves it (`asokit cpp submit` first)")
        keywords = {locale: sorted(loc["keywords"]) for locale, loc in ((snap["version"] or {}).get("localizations") or {}).items()}
        target = not hide
        change = {"page": name, "from": bool(snap["visible"]), "to": target, "keywords": keywords}
        changes.append(change)
        verb = "hide" if hide else "publish"
        if bool(snap["visible"]) == target:
            out(f"  {name}: already {'visible' if target else 'hidden'}")
            continue
        for locale, kws in sorted(keywords.items()):
            effect = "stops routing" if hide else "starts routing"
            out(f"  {name} {locale}: {effect} organic search for {', '.join(kws) or '(no keywords)'}")
        if apply:
            asc.call("PATCH", f"/appCustomProductPages/{row['id']}", bearer, _visible_body(row["id"], target))
            ledger.record("cpp publish", verb, page_name=name, page_id=row["id"], keywords=keywords)
    return changes


SUBMITTABLE = frozenset({"PREPARE_FOR_SUBMISSION", "REJECTED", "READY_FOR_REVIEW"})
BAD_PLACEMENT = frozenset({"ASSET_PROCESSING", "FAILED"})


def submit(app_id, doc, names, bearer, apply, ledger=NULL, out=print):
    catalog = library.Catalog.fetch(bearer)
    supported = catalog.supports(FEATURE, library.HEADER)
    pages = {p["name"]: p for p in cpp.expand(doc)}
    items = []
    for name in names:
        row = _page_row(app_id, name, bearer)
        snap = snapshot_page(row, bearer)
        version = snap["version"]
        if version is None or version["state"] not in SUBMITTABLE:
            raise review.SubmissionBlocked(f"'{name}' has nothing to submit (latest version {version and version['state']})")
        for locale, loc in version["localizations"].items():
            states = {p["state"] for p in loc["placements"]}
            if states & BAD_PLACEMENT:
                raise review.SubmissionBlocked(f"'{name}' {locale}: placements still {sorted(states & BAD_PLACEMENT)} — wait or re-push")
            declared = (pages.get(name) or {}).get("locales", {}).get(locale) or {}
            types = {p["type"] for p in loc["placements"]}
            if declared.get("screenshots") and library.SCREENSHOT not in types:
                raise review.SubmissionBlocked(f"'{name}' {locale}: the file declares screenshots but none are placed — run cpp push")
            if declared.get("creative") and supported and library.HEADER not in types:
                raise review.SubmissionBlocked(f"'{name}' {locale}: the file declares a creative but none is placed — run cpp push")
        items.append(("appCustomProductPageVersion", "appCustomProductPageVersions", version["id"]))
        out(f"  {name}: version {version['id']} ({version['state']})")
    return review.submit(app_id, items, bearer, apply, ledger=ledger, command="cpp submit")
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add asokit/cpp_apply.py tests/test_cpp_apply.py
git commit -m "feat(cpp): publish/hide with routing preview, guarded submit"
```

---

### Task 14: `cpp` commands, ads export, and `assets push --target cpp:`

**Files:**
- Modify: `asokit/cli.py`
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: Tasks 8–13.
- Produces: CLI `asokit cpp check|status|push|publish|submit`; `--ads-export PATH` on `cpp status` and `cpp push`; `assets push --target cpp:<name>`; `cli._write_ads(path, rows)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli.py`)

```python
from tests.fakes import FakeCppConnect
from tests.test_cpp import make_doc, page as cpp_page


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
        with self.assertRaises(SystemExit):
            self.run_cli("cpp", "submit", "--apply")
        with self.assertRaises(SystemExit):
            self.run_cli("cpp", "publish", "--apply")

    def test_assets_push_cpp_target_needs_editable_version(self):
        out = self.root / "assets-out" / "bpd"
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("assets", "push", str(out), "--target", "cpp:BPD tracker")
        self.assertIn("cpp push", str(caught.exception))
        self.run_cli("cpp", "push", "--apply")
        self.run_cli("assets", "push", str(out), "--target", "cpp:BPD tracker", "--locales", "en-US")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_cli.py -q -k Cpp`
Expected: FAIL — argparse error: invalid choice `cpp`.

- [ ] **Step 3: Implement**

In `asokit/cli.py`, add `cpp`, `cpp_apply` to the `from . import (...)` block, extend the docstring with:

```
  asokit cpp check [--offline]         validate cpp.json (keywords, limits, files)
  asokit cpp status [--ads-export P]   live custom product pages
  asokit cpp push [--apply]            converge pages to cpp.json (created hidden)
  asokit cpp submit --pages N [--apply]   send page versions to App Review
  asokit cpp publish --pages N [--apply]  make approved pages visible (routing goes live)
```

Add above `build_parser()`:

```python
import csv

ADS_FIELDS = ["page_name", "page_id", "page_url", "visible", "latest_state", "locale", "keywords", "deep_link"]


def _cpp_doc(args):
    path = Path(args.file) if args.file else _config_path(args).resolve().parent / "cpp.json"
    if not path.exists():
        sys.exit(f"no {path} — see the README for the cpp.json format")
    return cpp.load(path)


def _write_ads(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ADS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"ads export → {path} ({len(rows)} rows)")


def _pages_arg(args, required):
    names = [n.strip() for n in (args.pages or "").split(",") if n.strip()]
    if required and not names:
        sys.exit("--pages is required (comma-separated page names) — this command never acts on every page at once")
    return names or None


def _report(problems, warnings):
    for warning in warnings:
        print(f"  warning: {warning}")
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)


def cmd_cpp_check(args):
    doc = _cpp_doc(args)
    allow = [k for k in (args.allow_protected or "").split(",") if k]
    online = None
    if not args.offline:
        _, app_id = _require_app_id(args)
        bearer = _bearer()
        online = cpp_apply.online_context(app_id, doc, bearer, library.Catalog.fetch(bearer))
    problems, warnings = cpp.check(doc, args.creative_root, allow, not args.no_lint, online=online)
    _report(problems, warnings)
    print(f"ok — {len(cpp.expand(doc))} page(s) valid{' (offline: keyword pools not checked)' if args.offline else ''}")


def cmd_cpp_status(args):
    _, app_id = _require_app_id(args)
    bearer = _bearer()
    book = ledger_module.for_config(_config_path(args), True)
    snapshots = {}
    for row in cpp_apply.list_pages(app_id, bearer):
        snap = cpp_apply.snapshot_page(row, bearer, with_media=False)
        snapshots[snap["name"]] = snap
        version = snap["version"] or {}
        print(f"{snap['name']}  id {snap['id']}  {'visible' if snap['visible'] else 'hidden'}  {version.get('state', '(no version)')}"
              f"  published {book.last('publish', page_id=snap['id']) or '-'}")
        for locale, loc in sorted((version.get("localizations") or {}).items()):
            print(f"  {locale:<8} {', '.join(sorted(loc['keywords'])) or '(no keywords)'}")
    if args.ads_export:
        pages = cpp.expand(_cpp_doc(args)) if (args.file or (_config_path(args).resolve().parent / "cpp.json").exists()) else []
        _write_ads(args.ads_export, cpp.ads_rows(pages, snapshots))


def cmd_cpp_push(args):
    doc = _cpp_doc(args)
    _, app_id = _require_app_id(args)
    bearer = _bearer()
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        result = cpp_apply.push(app_id, doc, bearer, args.apply, creative_root=args.creative_root,
                                pages=_pages_arg(args, required=False),
                                locales=[l for l in (args.locales or "").split(",") if l] or None,
                                prune=args.prune, allow_protected=[k for k in (args.allow_protected or "").split(",") if k],
                                lint=not args.no_lint, ledger=book, out=print)
    except asc.ASCError as error:
        print(f"\naborted — {error}\nRe-running is safe: every step re-diffs against live state.", flush=True)
        sys.exit(1)
    _report(result["problems"], result["warnings"])
    if args.ads_export:
        _write_ads(args.ads_export, cpp.ads_rows(cpp.expand(doc), result["context"]["snapshots"]))
    if not result["actions"]:
        print("no changes — App Store Connect already matches cpp.json")
    print("\napplied — pages stay hidden until `asokit cpp publish`." if args.apply else "\nDRY RUN — nothing written. Re-run with --apply to push.")


def cmd_cpp_publish(args):
    names = _pages_arg(args, required=True)
    _, app_id = _require_app_id(args)
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        cpp_apply.publish(app_id, names, _bearer(), args.apply, hide=args.hide, ledger=book)
    except asc.ASCError as error:
        sys.exit(str(error))
    print("applied." if args.apply else "\nDRY RUN — nothing written. Re-run with --apply.")


def cmd_cpp_submit(args):
    names = _pages_arg(args, required=True)
    doc = _cpp_doc(args)
    _, app_id = _require_app_id(args)
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        result = cpp_apply.submit(app_id, doc, names, _bearer(), args.apply, ledger=book)
    except asc.ASCError as error:
        sys.exit(str(error))
    print(f"submission {result['submission']}: +{len(result['add'])} item(s), {len(result['existing'])} already in it")
    print("submitted for review." if result["submitted"] else "\nDRY RUN — nothing written. Re-run with --apply to submit.")
```

Extend `_resolve_target` (from Task 8):

```python
def _resolve_target(args, app_id, bearer):
    if args.target == "default":
        return _default_target(app_id, bearer)
    if args.target.startswith("cpp:"):
        name = args.target[4:]
        row = next((r for r in cpp_apply.list_pages(app_id, bearer) if (r.get("attributes") or {}).get("name") == name), None)
        if row is None:
            sys.exit(f"no custom product page named '{name}' — run `asokit cpp push` first")
        snap = cpp_apply.snapshot_page(row, bearer, with_media=False)
        version = snap["version"]
        if version is None or version["state"] not in cpp.EDITABLE:
            sys.exit(f"'{name}' has no editable version ({version and version['state']}) — run `asokit cpp push` first; "
                     "assets push never creates page versions")
        parents = {locale: loc["id"] for locale, loc in version["localizations"].items()}
        return "appCustomProductPageLocalization", parents, cpp_apply.FEATURE
    sys.exit(f"unknown target '{args.target}' — use 'default' or 'cpp:<page name>'")
```

Extend `cmd_assets_status` (Task 8) so it also lists each custom product page's latest version — append at the end of the function:

```python
    for row in cpp_apply.list_pages(app_id, bearer):
        snap = cpp_apply.snapshot_page(row, bearer)
        version = snap["version"] or {}
        print(f"custom product page '{snap['name']}' ({version.get('state', 'no version')}):")
        for locale, loc in sorted((version.get("localizations") or {}).items()):
            rows = [p for p in loc["placements"] if p["type"] in (library.HEADER, library.SEARCH)]
            line = ", ".join(f"{p['type'].split('_')[0].lower()}:{p['state']}" for p in rows) or "(no header/search assets)"
            print(f"  {locale:<8} {line}")
```

Move the early `return` for "no editable App Store version" in `cmd_assets_status` so the CPP listing still runs (print the message, skip only the version block).

Parser (before `return parser`):

```python
    cpp_command = subcommands.add_parser("cpp", help="custom product pages from cpp.json")
    cpp_sub = cpp_command.add_subparsers(dest="cpp_command", required=True)

    def cpp_common(sub, apply=False):
        sub.add_argument("--file", help="path to cpp.json (default: next to the config)")
        sub.add_argument("--app-id")
        if apply:
            sub.add_argument("--apply", action="store_true")

    cpp_check = cpp_sub.add_parser("check", help="validate cpp.json (online unless --offline)")
    cpp_common(cpp_check)
    cpp_check.add_argument("--offline", action="store_true")
    cpp_check.add_argument("--allow-protected", help="comma-separated protected keywords to allow")
    cpp_check.add_argument("--creative-root", default="assets-out")
    cpp_check.add_argument("--no-lint", action="store_true")
    cpp_check.set_defaults(func=cmd_cpp_check)

    cpp_status = cpp_sub.add_parser("status", help="live pages, versions, visibility and keywords")
    cpp_common(cpp_status)
    cpp_status.add_argument("--ads-export", help="write page/keyword CSV for Apple Ads ad groups")
    cpp_status.set_defaults(func=cmd_cpp_status)

    cpp_push = cpp_sub.add_parser("push", help="converge App Store Connect to cpp.json (dry run unless --apply)")
    cpp_common(cpp_push, apply=True)
    cpp_push.add_argument("--pages", help="comma-separated page names (default: all in the file)")
    cpp_push.add_argument("--locales", help="comma-separated locales; never deletes outside them")
    cpp_push.add_argument("--prune", action="store_true", help="delete page localizations missing from the file")
    cpp_push.add_argument("--allow-protected")
    cpp_push.add_argument("--creative-root", default="assets-out")
    cpp_push.add_argument("--no-lint", action="store_true")
    cpp_push.add_argument("--ads-export")
    cpp_push.set_defaults(func=cmd_cpp_push)

    cpp_publish = cpp_sub.add_parser("publish", help="make approved pages visible — organic routing goes live")
    cpp_common(cpp_publish, apply=True)
    cpp_publish.add_argument("--pages", help="comma-separated page names (required)")
    cpp_publish.add_argument("--hide", action="store_true", help="hide instead of publish")
    cpp_publish.set_defaults(func=cmd_cpp_publish)

    cpp_submit = cpp_sub.add_parser("submit", help="send page versions to App Review")
    cpp_common(cpp_submit, apply=True)
    cpp_submit.add_argument("--pages", help="comma-separated page names (required)")
    cpp_submit.set_defaults(func=cmd_cpp_submit)
```

`make_doc` in the test writes the cpp.json next to `asokit.json` (both in `self.root`) and `assets-out/` there, which is what the defaults expect.

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add asokit/cli.py tests/test_cli.py
git commit -m "feat(cli): cpp check/status/push/publish/submit, ads export, assets push to a CPP"
```

---

## Phase C — Library engine for `screenshots`

### Task 15: `screenshots status/push --engine library`

**Files:**
- Modify: `asokit/cli.py` (`cmd_screenshots_status`, `cmd_screenshots_push`, screenshots parser)
- Test: `tests/test_screenshots_library.py`

**Interfaces:**
- Consumes: `library.*`, `screenshots.LEGACY_DISPLAY_CLASS/LEGACY_BY_CLASS`, `cli._bearer`, `cli._default_target` (Task 8).
- Produces: `--engine {sets,library}` on `screenshots status` and `screenshots push` (default `sets`, existing code path untouched); `cli._format_status(report) -> list[str]` shared by both engines; `cli._library_status(app_id, bearer) -> (version_string, {locale: {display: count}})`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_screenshots_library.py
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3.13 -m pytest tests/test_screenshots_library.py -q`
Expected: FAIL — `unrecognized arguments: --engine`.

- [ ] **Step 3: Implement**

Add helpers above `cmd_screenshots_status`:

```python
def _format_status(report):
    lines = []
    for locale, families in report.items():
        line = ", ".join(f"{d} ×{n}" for d, n in sorted(families.items())) or "(inherits primary locale)"
        lines.append(f"  {locale:<8} {line}")
    return lines


def _library_status(app_id, bearer):
    version = asc.editable_version(app_id, bearer)
    if not version:
        raise asc.ASCError("No editable App Store version — screenshots are only writable in Prepare for Submission.")
    catalog = library.Catalog.fetch(bearer)
    report = {}
    for locale, loc_id in sorted(asc._localizations(version["id"], bearer).items()):
        counts = {}
        for row in library.surface_placements("appStoreVersionLocalization", loc_id, bearer):
            if row["type"] != library.SCREENSHOT:
                continue
            name = shots.LEGACY_BY_CLASS.get(catalog.display_class(row["group"]), row["group"])
            counts[name] = counts.get(name, 0) + 1
        report[locale] = counts
    return version["attributes"]["versionString"], report
```

Replace `cmd_screenshots_status` with:

```python
def cmd_screenshots_status(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")
    if args.engine == "library":
        version, report = _library_status(app_id, _bearer())
    else:
        version, report = asc.screenshots_status(app_id, asc.token())
    print(f"editable version: {version}")
    print("\n".join(_format_status(report)))
```

At the top of `cmd_screenshots_push`, right after `problems = shots.check(plan)` handling, branch:

```python
    if args.engine == "library":
        return _screenshots_push_library(args, app_id, plan)
```

and add:

```python
def _screenshots_push_library(args, app_id, plan):
    bearer = _bearer()
    parent_kind, parents, feature = _default_target(app_id, bearer)
    missing = sorted(set(plan) - set(parents))
    if missing:
        sys.exit(f"{', '.join(missing)}: no localization on the editable version — push metadata for it first")
    catalog = library.Catalog.fetch(bearer)
    lib = library.library_id(app_id, bearer)
    requests = []
    for locale, families in sorted(plan.items()):
        for display, files in families.items():
            requests.append({"locale": locale, "parent_kind": parent_kind, "parent_id": parents[locale],
                             "placement_types": [library.SCREENSHOT], "category": library.MEDIA,
                             "display_class": shots.LEGACY_DISPLAY_CLASS.get(display),
                             "files": [(Path(f).name, Path(f).read_bytes()) for f in files]})
    if args.mirror:
        source = parents.get(args.mirror_from)
        if not source:
            sys.exit(f"{args.mirror_from} has no localization on the editable version")
        rows = library.surface_placements(parent_kind, source, bearer)
        for display in args.mirror.split(","):
            display_class = shots.LEGACY_DISPLAY_CLASS.get(display)
            picked = [r for r in rows if r["type"] == library.SCREENSHOT and catalog.display_class(r["group"]) == display_class]
            if not picked:
                sys.exit(f"{args.mirror_from} has no {display} screenshots to mirror")
            group = picked[0]["group"]
            assets = [{"asset": r["asset"], "sha": r["sha"], "name": r["asset"], "specId": None} for r in picked if r["group"] == group]
            for locale in sorted(plan):
                if locale != args.mirror_from:
                    requests.append({"locale": locale, "parent_kind": parent_kind, "parent_id": parents[locale],
                                     "placement_types": [library.SCREENSHOT], "category": library.MEDIA,
                                     "assets": assets, "groups": [group]})
            print(f"mirroring {display} ×{len(assets)} from {args.mirror_from} into every other locale")
    book = ledger_module.for_config(_config_path(args), args.apply)
    try:
        library.sync_groups(requests, catalog, feature, lib, bearer, args.apply, ledger=book, command="screenshots push",
                            progress=lambda a: _print_actions([a]))
    except asc.ASCError as error:
        print(f"\naborted — {error}\nRe-running is safe: uploads are reused and unchanged groups are skipped.", flush=True)
        sys.exit(1)
    print("\napplied — verify in App Store Connect before submitting." if args.apply else "\nDRY RUN — nothing written. Re-run with --apply to push.")
```

Parser — add to both `screenshots_status` and `screenshots_push`:

```python
    screenshots_status.add_argument("--engine", choices=["sets", "library"], default="sets",
                                    help="sets = deprecated screenshot-set API (default until parity is verified); library = Asset Library")
```

```python
    screenshots_push.add_argument("--engine", choices=["sets", "library"], default="sets",
                                  help="sets = deprecated screenshot-set API (default until parity is verified); library = Asset Library")
```

- [ ] **Step 4: Run tests**

Run: `python3.13 -m pytest -q`
Expected: all pass, including the untouched `tests/test_screenshots.py` (sets engine).

- [ ] **Step 5: Commit**

```bash
git add asokit/cli.py tests/test_screenshots_library.py
git commit -m "feat(screenshots): opt-in Asset Library engine with diffing and id-based mirroring"
```

---

## Phase D — Featuring nominations

### Task 16: Nominations

**Files:**
- Create: `asokit/nominations.py`
- Modify: `asokit/cli.py`, `tests/fakes.py` (append `FakeNominationConnect`)
- Test: `tests/test_nominations.py`

**Interfaces:**
- Consumes: `asc.*`, `ledger.NULL`.
- Produces: `nominations.TYPES`, `nominations.load(path)`, `nominations.to_datetime(value) -> str | None`, `nominations.check(doc, today=None, force=False) -> (problems, warnings)`, `nominations.push(app_id, doc, bearer, apply, submit_name=None, ledger=NULL, out=print) -> list[dict]` (`{"name", "op": "create"|"update"|"skip"|"unchanged"|"submit", ...}`); CLI `asokit nominations check|push`.

- [ ] **Step 1: Append the fake** to `tests/fakes.py`

```python
class FakeNominationConnect(FakeConnect):
    def __init__(self):
        super().__init__()
        self.nominations = {}   # id -> attributes (incl. "state")

    def route(self, method, parts, query, body):
        if parts[:1] == ["nominations"]:
            if method == "GET" and len(parts) == 1:
                assert "filter[state]" in query, "GET /v1/nominations requires filter[state]"
                wanted = set(query["filter[state]"].split(","))
                return {"data": [{"id": nid, "type": "nominations", "attributes": dict(attrs)}
                                 for nid, attrs in self.nominations.items() if attrs["state"] in wanted]}
            if method == "POST":
                attrs = dict(body["data"]["attributes"])
                assert all(isinstance(a["id"], str) for a in body["data"]["relationships"]["relatedApps"]["data"])
                attrs["state"] = "SUBMITTED" if attrs.pop("submitted") else "DRAFT"
                nid = self.next_id("nom")
                self.nominations[nid] = attrs
                return {"data": {"id": nid, "type": "nominations", "attributes": attrs}}
            if method == "PATCH":
                attrs = dict(body["data"]["attributes"])
                if attrs.pop("submitted", False):
                    self.nominations[parts[1]]["state"] = "SUBMITTED"
                self.nominations[parts[1]].update(attrs)
                return {"data": {"id": parts[1]}}
        return super().route(method, parts, query, body)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_nominations.py
import datetime
import unittest

from asokit import nominations
from tests.fakes import FakeNominationConnect, install

TODAY = datetime.date(2026, 10, 11)


def doc(**overrides):
    entry = {"name": "MoodSync — new product page", "type": "APP_ENHANCEMENTS", "description": "New header and search art.",
             "publishStartDate": "2026-11-16", "deviceFamilies": ["IPHONE", "IPAD"], "locales": ["en-US"]}
    entry.update(overrides)
    return {"nominations": [entry]}


class CheckTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(nominations.check(doc(), today=TODAY)[0], [])

    def test_limits_type_and_notice(self):
        problems, _ = nominations.check(doc(name="N" * 61, description="d" * 1001, type="APP_ENHANCEMENT",
                                            publishStartDate="2026-10-20"), today=TODAY)
        text = "\n".join(problems)
        for needle in ("60", "1000", "APP_ENHANCEMENT", "14 days"):
            self.assertIn(needle, text)

    def test_force_downgrades_notice_to_warning(self):
        problems, warnings = nominations.check(doc(publishStartDate="2026-10-20"), today=TODAY, force=True)
        self.assertEqual(problems, [])
        self.assertTrue(warnings)

    def test_dates_become_datetimes(self):
        self.assertEqual(nominations.to_datetime("2026-11-16"), "2026-11-16T00:00:00Z")
        self.assertIsNone(nominations.to_datetime(None))


class PushTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeNominationConnect())

    def test_create_as_draft_then_no_change(self):
        nominations.push("6757342494", doc(), "t", apply=True, out=lambda line: None)
        (attrs,) = self.fake.nominations.values()
        self.assertEqual(attrs["state"], "DRAFT")
        self.assertEqual(attrs["publishStartDate"], "2026-11-16T00:00:00Z")
        before = len(self.fake.writes())
        actions = nominations.push("6757342494", doc(), "t", apply=True, out=lambda line: None)
        self.assertEqual([a["op"] for a in actions], ["unchanged"])
        self.assertEqual(len(self.fake.writes()), before)

    def test_draft_is_patched_and_submitted_one_is_skipped(self):
        nominations.push("1", doc(), "t", apply=True, out=lambda line: None)
        actions = nominations.push("1", doc(description="Changed."), "t", apply=True, out=lambda line: None)
        self.assertEqual(actions[0]["op"], "update")
        nid = next(iter(self.fake.nominations))
        self.fake.nominations[nid]["state"] = "SUBMITTED"
        actions = nominations.push("1", doc(description="Again."), "t", apply=True, out=lambda line: None)
        self.assertEqual(actions[0]["op"], "skip")

    def test_submit_only_the_named_nomination(self):
        two = doc()
        two["nominations"].append(dict(two["nominations"][0], name="Other"))
        nominations.push("1", two, "t", apply=True, submit_name="Other", out=lambda line: None)
        states = {a["name"]: a["state"] for a in self.fake.nominations.values()}
        self.assertEqual(states, {"MoodSync — new product page": "DRAFT", "Other": "SUBMITTED"})

    def test_dry_run_writes_nothing(self):
        nominations.push("1", doc(), "t", apply=False, out=lambda line: None)
        self.assertEqual(self.fake.writes(), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify failure**

Run: `python3.13 -m pytest tests/test_nominations.py -q`
Expected: FAIL — cannot import `nominations`.

- [ ] **Step 4: Implement**

```python
# asokit/nominations.py
"""Featuring nominations from `nominations.json`, created as drafts.

  {"nominations": [{"name", "type", "description", "publishStartDate": "YYYY-MM-DD",
                    "publishEndDate"?, "deviceFamilies"?, "locales"?, "notes"?,
                    "relatedApps"? (default: the config's appId), "supplementalMaterialsUris"?,
                    "hasInAppEvents"?, "launchInSelectMarketsFirst"?, "preOrderEnabled"?}]}

Nothing is submitted unless `push(..., submit_name=NAME)` names it.
"""
import datetime
import json
from pathlib import Path

from . import asc
from .ledger import NULL

TYPES = frozenset({"APP_LAUNCH", "APP_ENHANCEMENTS", "NEW_CONTENT"})
FAMILIES = frozenset({"IPHONE", "IPAD", "APPLE_TV", "APPLE_WATCH", "MAC", "VISION"})
NAME_MAX, DESCRIPTION_MAX, NOTICE_DAYS = 60, 1000, 14
ATTRIBUTES = ("description", "type", "publishStartDate", "publishEndDate", "deviceFamilies", "locales", "notes",
              "hasInAppEvents", "launchInSelectMarketsFirst", "preOrderEnabled", "supplementalMaterialsUris")
DATES = ("publishStartDate", "publishEndDate")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def to_datetime(value):
    if not value:
        return None
    return f"{value}T00:00:00Z" if len(value) == 10 else value


def _date(value):
    return value[:10] if value else None


def check(doc, today=None, force=False):
    today = today or datetime.date.today()
    problems, warnings = [], []
    names = [n.get("name", "") for n in doc.get("nominations", [])]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"nomination name '{name}' appears more than once")
    for entry in doc.get("nominations", []):
        name = entry.get("name", "")
        for field in ("name", "type", "description", "publishStartDate"):
            if not entry.get(field):
                problems.append(f"'{name}': {field} is required")
        if len(name) > NAME_MAX:
            problems.append(f"'{name}': name is {len(name)} characters, limit {NAME_MAX}")
        if len(entry.get("description", "")) > DESCRIPTION_MAX:
            problems.append(f"'{name}': description exceeds {DESCRIPTION_MAX} characters")
        if entry.get("type") and entry["type"] not in TYPES:
            problems.append(f"'{name}': type {entry['type']} is not one of {', '.join(sorted(TYPES))}")
        bad = set(entry.get("deviceFamilies", [])) - FAMILIES
        if bad:
            problems.append(f"'{name}': unknown device families {sorted(bad)}")
        start = entry.get("publishStartDate")
        if start:
            days = (datetime.date.fromisoformat(start[:10]) - today).days
            if days < NOTICE_DAYS:
                message = f"'{name}': publishStartDate is {days} days away — Apple needs at least {NOTICE_DAYS} days' notice"
                (warnings if force else problems).append(message + (" (--force)" if force else ""))
    return problems, warnings


def _attributes(entry):
    attrs = {key: entry[key] for key in ATTRIBUTES if entry.get(key) is not None}
    for key in DATES:
        if key in attrs:
            attrs[key] = to_datetime(attrs[key])
    return attrs


def _changes(entry, live):
    wanted = _attributes(entry)
    changed = {}
    for key, value in wanted.items():
        current = live.get(key)
        same = _date(value) == _date(current) if key in DATES else value == current
        if not same:
            changed[key] = value
    return changed


def push(app_id, doc, bearer, apply, submit_name=None, ledger=NULL, out=print):
    rows = asc.call_all("GET", f"/nominations?filter[state]=DRAFT,SUBMITTED&filter[relatedApps]={app_id}&limit=200", bearer)
    live = {row["attributes"].get("name"): row for row in rows}
    names = [entry["name"] for entry in doc.get("nominations", [])]
    if submit_name and submit_name not in names:
        raise asc.ASCError(f"--name '{submit_name}' is not in the nominations file")
    actions = []
    for entry in doc.get("nominations", []):
        name = entry["name"]
        row = live.get(name)
        related = [str(a) for a in entry.get("relatedApps", [app_id])]
        if row is None:
            actions.append({"name": name, "op": "create"})
            out(f"  create   {name} (draft)")
            if apply:
                created = asc.call("POST", "/nominations", bearer, {"data": {
                    "type": "nominations",
                    "attributes": {"name": name, "submitted": False, **_attributes(entry)},
                    "relationships": {"relatedApps": {"data": [{"type": "apps", "id": a} for a in related]}},
                }})["data"]
                ledger.record("nominations push", "create", nomination_id=created["id"], name=name)
                row = created
        elif row["attributes"].get("state") == "SUBMITTED":
            actions.append({"name": name, "op": "skip"})
            out(f"  skip     {name} (already submitted)")
            continue
        else:
            changes = _changes(entry, row["attributes"])
            actions.append({"name": name, "op": "update" if changes else "unchanged", "changes": sorted(changes)})
            out(f"  {'update' if changes else 'ok':<8} {name}" + (f": {', '.join(sorted(changes))}" if changes else ""))
            if apply and changes:
                asc.call("PATCH", f"/nominations/{row['id']}", bearer, {"data": {"type": "nominations", "id": row["id"], "attributes": changes}})
                ledger.record("nominations push", "update", nomination_id=row["id"], name=name, changed=sorted(changes))
        if submit_name == name:
            actions.append({"name": name, "op": "submit"})
            out(f"  submit   {name}")
            if apply:
                asc.call("PATCH", f"/nominations/{row['id']}", bearer, {"data": {"type": "nominations", "id": row["id"], "attributes": {"submitted": True}}})
                ledger.record("nominations push", "submit", nomination_id=row["id"], name=name)
    return actions
```

- [ ] **Step 5: CLI**

Add `nominations` to the import block and docstring (`asokit nominations check|push`), then above `build_parser()`:

```python
def _nominations_doc(args):
    path = Path(args.file) if args.file else _config_path(args).resolve().parent / "nominations.json"
    if not path.exists():
        sys.exit(f"no {path}")
    return nominations.load(path)


def cmd_nominations_check(args):
    problems, warnings = nominations.check(_nominations_doc(args), force=args.force)
    _report(problems, warnings)
    print("ok")


def cmd_nominations_push(args):
    doc = _nominations_doc(args)
    if args.submit and not (args.name and args.apply):
        sys.exit("--submit needs --name NAME and --apply — nominations are submitted one at a time")
    problems, warnings = nominations.check(doc, force=args.force)
    _report(problems, warnings)
    _, app_id = _require_app_id(args)
    if asc.editable_version(app_id, _bearer()) is None:
        print("  warning: no App Store version in preparation — make sure the nominated release can ship by its date")
    book = ledger_module.for_config(_config_path(args), args.apply)
    nominations.push(app_id, doc, _bearer(), args.apply, submit_name=args.name if args.submit else None, ledger=book)
    print("applied." if args.apply else "\nDRY RUN — nothing written. Re-run with --apply.")
```

Parser:

```python
    nominations_command = subcommands.add_parser("nominations", help="App Store featuring nominations")
    nominations_sub = nominations_command.add_subparsers(dest="nominations_command", required=True)
    nominations_check = nominations_sub.add_parser("check", help="validate nominations.json")
    nominations_check.add_argument("--file")
    nominations_check.add_argument("--force", action="store_true", help="allow < 14 days' notice")
    nominations_check.set_defaults(func=cmd_nominations_check)
    nominations_push = nominations_sub.add_parser("push", help="create/update drafts (dry run unless --apply)")
    nominations_push.add_argument("--file")
    nominations_push.add_argument("--app-id")
    nominations_push.add_argument("--apply", action="store_true")
    nominations_push.add_argument("--force", action="store_true")
    nominations_push.add_argument("--submit", action="store_true", help="submit the nomination named by --name")
    nominations_push.add_argument("--name")
    nominations_push.set_defaults(func=cmd_nominations_push)
```

- [ ] **Step 6: Run tests**

Run: `python3.13 -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add asokit/nominations.py asokit/cli.py tests/fakes.py tests/test_nominations.py
git commit -m "feat: featuring nominations as drafts, single named submit"
```

---

### Task 17: Documentation and version

**Files:**
- Modify: `README.md`, `pyproject.toml` (`version = "0.5.0"`), `asokit/__init__.py` (version string if present)

- [ ] **Step 1: README** — add a section "App Store creatives, custom product pages and nominations" after the screenshots section, containing:
  - Install: `pip install 'aso-keyword-toolkit[connect,render]'`.
  - `assets.json` schema (copy the example from the spec's `render.py` section) and `asokit assets render` / `status --catalog` / `push --target default|cpp:<name>` / `submit`.
  - `cpp.json` schema (copy the spec's example), the keyword ownership + protected keyword rules, and the lifecycle: `cpp check` → `cpp push --apply` (hidden) → `cpp submit --pages X --apply` → after approval `cpp publish --pages X --apply`.
  - `nominations.json` example and `nominations check` / `push` / `push --submit --name N --apply`.
  - `screenshots push --engine library` and the flip criterion (status parity + one verified full push).
  - The ledger file and how to read it against App Analytics.
  - Module list update: `library`, `creative`, `render`, `cpp`, `cpp_apply`, `review`, `nominations`, `ledger`.
- [ ] **Step 2: Bump version** to `0.5.0` in `pyproject.toml` (and `asokit/__init__.py` if it carries `__version__`).
- [ ] **Step 3: Full test run**

Run: `python3.13 -m pytest -q`
Expected: all pass. Also run `python3.13 -m asokit --help` and `python3.13 -m asokit assets --help`, `cpp --help`, `nominations --help` — each prints usage without error.

- [ ] **Step 4: Commit**

```bash
git add README.md pyproject.toml asokit/__init__.py
git commit -m "docs: creatives, custom product pages, nominations; v0.5.0"
```

---

## MoodSync content (repo `/Users/ggapp/Projects/mobileapps/moodsync`)

Before Task 18, check `git status` in the MoodSync repo: unrelated uncommitted changes exist (project.pbxproj, string catalogs, project.yml). **Stage only the files named in each task.**

### Task 18: `assets.json` and hero headlines

**Files:**
- Create: `assets.json`
- Modify: `screenshots/store/headlines.json` (add a `"hero"` key to every locale that has its own `"h"`), `.gitignore`

- [ ] **Step 1: Write `assets.json`**

```json
{
  "canvas": {"width": 5244, "height": 2950},
  "safeInset": 0.03,
  "brand": {"background": "#4338CA", "text": "#FFFFFF", "frame": "#1C1C1E"},
  "fonts": {
    "default": {"path": "/Library/Fonts/SF-Pro-Display-Black.otf"},
    "ja": {"path": "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", "index": 0},
    "ko": {"path": "/System/Library/Fonts/AppleSDGothicNeo.ttc", "index": 6},
    "zh-Hans": {"path": "/System/Library/Fonts/STHeiti Medium.ttc", "index": 0},
    "zh-Hant": {"path": "/System/Library/Fonts/STHeiti Medium.ttc", "index": 0},
    "th": {"path": "/System/Library/Fonts/Supplemental/Thonburi.ttc", "index": 1},
    "hi": {"path": "/System/Library/Fonts/Kohinoor.ttc", "index": 3},
    "ar-SA": {"path": "/System/Library/Fonts/SFArabic.ttf", "variation": "Bold"},
    "he": {"path": "/System/Library/Fonts/SFHebrew.ttf", "variation": "Bold"}
  },
  "noSpaceWrap": ["ja", "zh-Hans", "zh-Hant"],
  "type": {"verb": {"size": 520, "min": 300, "step": 10, "lines": 1, "leading": 1.02},
           "descriptor": {"size": 250, "min": 170, "step": 6, "lines": 2, "leading": 1.12},
           "tight": {"verb": 340, "descriptor": 190}},
  "variants": {
    "default": {
      "captures": ["{ui}/01-log-home.png", "{ui}/03-stats-insights.png"],
      "capturesRoot": "screenshots/store/src",
      "headlines": {"from": "screenshots/store/headlines.json", "slot": "hero", "fallbackSlot": 0}
    },
    "bpd": {
      "captures": ["{ui}/06-add-entry-details.png", "{ui}/02-stats-patterns.png"],
      "capturesRoot": "screenshots/store/src", "ui": "en",
      "headlines": {"en-US": ["LOG MOOD SWINGS", "TRIGGERS, SYMPTOMS & PATTERNS"],
                    "en-GB": {"same": "en-US"}, "en-CA": {"same": "en-US"}, "en-AU": {"same": "en-US"}}
    },
    "meds-triggers": {
      "captures": ["{ui}/06-add-entry-details.png", "{ui}/05-settings-health.png"],
      "capturesRoot": "screenshots/store/src", "ui": "en",
      "headlines": {"en-US": ["MEDS & SLEEP", "SEE WHAT SHIFTS YOUR MOOD"],
                    "en-GB": {"same": "en-US"}, "en-CA": {"same": "en-US"}, "en-AU": {"same": "en-US"}}
    },
    "depression-anxiety": {
      "captures": ["{ui}/09-weekly-review.png", "{ui}/02-stats-patterns.png"],
      "capturesRoot": "screenshots/store/src", "ui": "en",
      "headlines": {"en-US": ["YOUR WEEK, REVIEWED", "LOW AND ANXIOUS DAYS IN CONTEXT"],
                    "en-GB": {"same": "en-US"}, "en-CA": {"same": "en-US"}, "en-AU": {"same": "en-US"}}
    },
    "report": {
      "captures": ["{ui}/04-pdf-preview.png", "{ui}/03-stats-insights.png"],
      "capturesRoot": "screenshots/store/src", "ui": "en",
      "headlines": {"en-US": ["BRING A REPORT", "A CLEAR SUMMARY FOR YOUR THERAPIST"],
                    "en-GB": {"same": "en-US"}, "en-CA": {"same": "en-US"}, "en-AU": {"same": "en-US"}}
    }
  }
}
```

- [ ] **Step 2: Add `"hero"` to `headlines.json`.** For every locale entry that has its own `"h"` (skip entries that only carry `"same"` — they inherit), add `"hero": [VERB, DESCRIPTOR]`, translating the English pair `["SEE THE PATTERNS", "MOOD, SLEEP & MEDS IN ONE PLACE"]`. Follow the file's existing conventions: same casing as that locale's `"h"` entries, ZWSP break hints for Thai like the existing Thai lines, no claims (no "detect", "diagnose", "best", prices). Edit the JSON by loading and re-dumping with `ensure_ascii=False, indent=2` **only if** that reproduces the file byte-for-byte when no change is made; otherwise splice the `"hero"` lines textually after each `"h": [...]` block. Add to `_notes`: `"hero = product page header/search creative line (assets.json default variant). Claude-drafted 2026-10-11; native review owed except en."`

- [ ] **Step 3: `.gitignore`** — append:

```
# asokit creative renders
assets-out/
```

- [ ] **Step 4: Render and inspect**

Run (from the MoodSync repo root): `asokit assets render`
Expected: five variants written to `assets-out/<variant>/`, contact sheets in `assets-out/_contact/`, zero `FAILED` lines. If a locale fails to fit, shorten that locale's hero line rather than lowering the type minimums. Open `assets-out/_contact/default.png` and `assets-out/_contact/bpd.png` and check visually that no text or device is clipped and Arabic/Hebrew read right-to-left.

- [ ] **Step 5: Commit** (MoodSync repo; stage only these files)

```bash
git add assets.json screenshots/store/headlines.json .gitignore
git commit -m "aso: assets.json for header/search creatives + hero headline per locale (native review owed)"
```

---

### Task 19: `cpp.json` and `nominations.json`

**Files:**
- Create: `cpp.json`, `nominations.json`

- [ ] **Step 1: Write `cpp.json`**

Screenshot file names come from `screenshots/store/out/<locale>/` (`NN-<slot>.png`, e.g. `06-doctor-asks.png`); `order` selects by the two-digit prefix.

```json
{
  "protectedKeywords": {"*": ["cyclothymia", "depression", "hypomania", "mania", "episode"]},
  "pages": [
    {
      "name": "BPD tracker",
      "template": "appStoreVersion",
      "deepLink": null,
      "locales": {
        "en-US": {"promotionalText": "Log mood swings, triggers and symptoms in seconds. See your patterns over weeks and share a clear report with your therapist. Private, no account needed.",
                  "keywords": ["bpd", "borderline"],
                  "screenshots": [{"dir": "screenshots/store/out/en-US", "order": ["02", "08", "04", "01"], "display": "APP_IPHONE_67"}],
                  "creative": "bpd"},
        "en-GB": {"same": "en-US", "keywords": ["bpd", "borderline"], "screenshots": [{"dir": "screenshots/store/out/en-GB", "order": ["02", "08", "04", "01"], "display": "APP_IPHONE_67"}]},
        "en-CA": {"same": "en-US", "keywords": ["bpd", "borderline"], "screenshots": [{"dir": "screenshots/store/out/en-CA", "order": ["02", "08", "04", "01"], "display": "APP_IPHONE_67"}]},
        "en-AU": {"same": "en-US", "keywords": ["bpd", "borderline"], "screenshots": [{"dir": "screenshots/store/out/en-AU", "order": ["02", "08", "04", "01"], "display": "APP_IPHONE_67"}]}
      }
    },
    {
      "name": "Meds & triggers",
      "template": "appStoreVersion",
      "deepLink": null,
      "locales": {
        "en-US": {"promotionalText": "Track medication, sleep and triggers alongside your mood. Apple Health can fill in sleep for you, and patterns show what shifts your days.",
                  "keywords": ["medication", "triggers"],
                  "screenshots": [{"dir": "screenshots/store/out/en-US", "order": ["05", "02", "06", "01"], "display": "APP_IPHONE_67"}],
                  "creative": "meds-triggers"},
        "en-GB": {"same": "en-US", "keywords": ["medication", "triggers"], "screenshots": [{"dir": "screenshots/store/out/en-GB", "order": ["05", "02", "06", "01"], "display": "APP_IPHONE_67"}]},
        "en-CA": {"same": "en-US", "keywords": ["medication", "triggers"], "screenshots": [{"dir": "screenshots/store/out/en-CA", "order": ["05", "02", "06", "01"], "display": "APP_IPHONE_67"}]},
        "en-AU": {"same": "en-US", "keywords": ["medication", "triggers"], "screenshots": [{"dir": "screenshots/store/out/en-AU", "order": ["05", "02", "06", "01"], "display": "APP_IPHONE_67"}]}
      }
    },
    {
      "name": "Depression & anxiety",
      "template": "appStoreVersion",
      "deepLink": null,
      "locales": {
        "en-US": {"promotionalText": "Log low and anxious days in seconds. A weekly review shows how your mood, sleep and energy move together over time.",
                  "keywords": [],
                  "screenshots": [{"dir": "screenshots/store/out/en-US", "order": ["09", "08", "02", "01"], "display": "APP_IPHONE_67"}],
                  "creative": "depression-anxiety"},
        "en-GB": {"same": "en-US", "screenshots": [{"dir": "screenshots/store/out/en-GB", "order": ["09", "08", "02", "01"], "display": "APP_IPHONE_67"}]},
        "en-CA": {"same": "en-US", "screenshots": [{"dir": "screenshots/store/out/en-CA", "order": ["09", "08", "02", "01"], "display": "APP_IPHONE_67"}]},
        "en-AU": {"same": "en-US", "screenshots": [{"dir": "screenshots/store/out/en-AU", "order": ["09", "08", "02", "01"], "display": "APP_IPHONE_67"}]}
      }
    },
    {
      "name": "Therapist report",
      "template": "appStoreVersion",
      "deepLink": null,
      "locales": {
        "en-US": {"promotionalText": "Turn your logs into a clear PDF summary of mood, sleep and medication to bring to your next appointment.",
                  "keywords": [],
                  "screenshots": [{"dir": "screenshots/store/out/en-US", "order": ["04", "06", "03", "01"], "display": "APP_IPHONE_67"}],
                  "creative": "report"},
        "en-GB": {"same": "en-US", "screenshots": [{"dir": "screenshots/store/out/en-GB", "order": ["04", "06", "03", "01"], "display": "APP_IPHONE_67"}]},
        "en-CA": {"same": "en-US", "screenshots": [{"dir": "screenshots/store/out/en-CA", "order": ["04", "06", "03", "01"], "display": "APP_IPHONE_67"}]},
        "en-AU": {"same": "en-US", "screenshots": [{"dir": "screenshots/store/out/en-AU", "order": ["04", "06", "03", "01"], "display": "APP_IPHONE_67"}]}
      }
    }
  ]
}
```

Before writing, list `screenshots/store/out/en-US/` and confirm each `order` prefix matches exactly one file and shows what the page is about (slot order in `headlines.json` `_slots`: 01 track, 02 spot, 03 catch, 04 doctor-report, 05 autofill-health, 06 doctor-asks, 07 year-in-pixels, 08 highs-lows, 09 weekly-review, 10 habit). Adjust prefixes if the files differ; keep 4 screenshots per page.

- [ ] **Step 2: Write `nominations.json`**

```json
{
  "_notes": "Draft for the NEXT app version. Set publishStartDate once that version's date is firm (>= 14 days out), then `asokit nominations push --apply` (draft) and later `--submit --name ... --apply`.",
  "nominations": [
    {
      "name": "MoodSync — new product page and languages",
      "type": "APP_ENHANCEMENTS",
      "description": "MoodSync is a private mood, sleep and medication tracker built for people living with bipolar disorder. This update brings a redesigned App Store presence with localized header and search artwork in 39 languages, focused product pages for BPD, medication and mood review, and full in-app German and French. Everything stays on the device with no account required.",
      "publishStartDate": "2026-12-07",
      "deviceFamilies": ["IPHONE", "IPAD"],
      "locales": ["en-US", "en-GB", "de-DE", "fr-FR"],
      "notes": "Native review of German and French completes before submission."
    }
  ]
}
```

- [ ] **Step 3: Validate offline**

Run (MoodSync repo root): `asokit cpp check --offline` and `asokit nominations check`
Expected: `ok — 4 page(s) valid (offline…)` and `ok`. Lint must pass on every promo text.

- [ ] **Step 4: Commit** (stage only these files)

```bash
git add cpp.json nominations.json
git commit -m "aso: cpp.json (4 pages, en locales; wave 1 = BPD) and draft featuring nomination"
```

---

## Live gates (user-run — NOT executed by implementers)

Each step needs the user's explicit go-ahead; the dry runs are read-only.

**Phase A**
1. `asokit assets status --catalog` — confirm universal spec 5244×2950 exists under `APP_STORE_VERSIONS` and `CUSTOM_PRODUCT_PAGES` for both header and search; note group ids and limits.
2. `asokit assets status` — library reachable; current header/search placements.
3. Upload one rendered default creative through the App Store Connect web Preview tool (or `assets push --target default --locales en-US` dry run) and check crop/overlay before trusting all 39.
4. `asokit assets push assets-out/default --target default` dry run; `--apply` only once the next version is in Prepare for Submission.

**Phase B**
1. `asokit cpp status` — confirms `AppKeyword` ids are the keyword text and lists live pages.
2. `asokit cpp check` (online).
3. `asokit cpp push --pages "BPD tracker" --locales en-US` dry run → `--apply`. Inspect the hidden page in App Store Connect (template media inherited? creative placed?).
4. Remaining locales/pages with `--apply` (all stay hidden).
5. `asokit cpp submit --pages "BPD tracker" --apply` → after approval `asokit cpp publish --pages "BPD tracker" --apply`. Next page after a 14-day App Analytics read.

**Phase C**
1. `asokit screenshots status` and `asokit screenshots status --engine library` against the editable version — outputs must match before any `--engine library --apply`.

**Phase D**
1. `asokit nominations push` dry run; `--apply` creates the draft once `publishStartDate` is firm.
