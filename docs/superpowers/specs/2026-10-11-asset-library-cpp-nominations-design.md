# Asset Library, creative assets, custom product pages and featuring nominations

**Date:** 2026-10-11
**Status:** Draft — under review
**Driving app:** MoodSync (ASC app id `6757342494`), then the rest of the portfolio
**Background research:** `~/Projects/mobileapps/docs/app-store-oct-2026-dossier.md`

## Problem

On 2026-10-05 Apple shipped two new App Store surfaces — a **product page header** and a **search results asset** (iOS 27+/iPadOS 27+) — and the **App Asset Library**, a per-app media library where an asset is uploaded once and *placed* on any number of surfaces. Alongside it, the set-based screenshot resources that `asokit screenshots push` uses (`appScreenshotSets`, `appScreenshots`) are now **deprecated**.

The portfolio cannot use any of this today without hand work in the web UI:

1. There is no way to produce the new 16:9 creative per app and per locale. MoodSync has a bespoke PIL compositor (`screenshots/store/compose.py`) for portrait screenshots; nothing renders landscape creatives, and nothing is shared across apps.
2. There is no way to upload or place creatives. The search asset is the highest-leverage item for a search-driven app (it *replaces* the screenshot strip in search), and it needs a localized file per storefront — 39 locales for MoodSync.
3. **Custom product pages (CPPs)** can now carry their own search keywords (Oct 2025) and their own header/search creatives. Building a CPP by hand means: create page, create version, create one localization per locale, set promo text, link keywords, upload screenshots, place creatives, submit. That is per page × per locale clicks with no review trail, and the keyword-uniqueness rule ("each keyword combination is unique to a single product page") is easy to break by hand.
4. **Featuring nominations** have a full API (`/v1/nominations`) but are filed by hand.

## Goals

- Render a localized universal creative (5244×2950 PNG) per app, per variant, per locale from a declarative config — no per-app rendering code.
- Upload and place creatives on the default product page and on CPPs through the Asset Library.
- Declare CPPs in a file (`cpp.json`) and converge App Store Connect to it, idempotently.
- Validate CPP keywords against the app's live keyword field and against each other *before* any write.
- Export the CPP → keyword mapping for Apple Ads ad-group setup.
- Move `asokit screenshots push` onto the Asset Library with its CLI surface unchanged.
- Create featuring nominations from a file, as drafts by default.
- Every write is a dry run unless `--apply` is passed, matching the existing idiom.
- `asokit` stays stdlib-only at its core; rendering is an optional extra.

## Non-goals

Each excluded for a reason:

- **iPhone Duo screenshots/creatives.** Deferred by decision; the Duo display class (`IPHONE_DUO`) arrives through the reference-data catalog with no code change when we pick it up.
- **Video creatives and app previews.** Images first; the video upload path (`appAssetLibraryVideos`) mirrors the image one and can be added later.
- **Dedicated 21:9 header / 3:2 search files.** One universal 16:9 file covers both placements; dedicated files are a later optimisation.
- **Retention Messaging.** Its API is still prerelease; one-time setup per subscription app is done by hand.
- **Product page optimization (PPO) tests.** Placement into experiment treatments is supported by the API but not built here. Note: a running PPO test has been observed to block placement on the default page; `assets push` detects and reports it (see Errors).
- **New in-app deep links.** MoodSync handles only `moodsync://log?mood=N`. `cpp.json` accepts a `deepLink`; adding new routes to the app is separate app work.
- **Deleting CPPs or assets.** Not automated. Pages can be hidden (`visible: false`); assets are left in the library.
- **Submitting the app version.** Default-page creatives ride with the next app version, submitted by the user.

## Verified API surface

All from Apple's App Store Connect API reference (DocC JSON, read 2026-10-11). Identifiers in `code` are exact.

### Asset Library

| Purpose | Call |
|---|---|
| Library id (stable for the app's life) | `GET /v1/apps/{id}/assetLibrary` → `appAssetLibraries.id` |
| Spec catalog | `GET /v1/appAssetLibraryRefData` (filterable: `filter[features]`, `filter[placementTypes]`, `filter[placementProfileGroups]`, `filter[specs]`; sparse `fields[appAssetLibraryRefData]`) |
| Reserve image | `POST /v1/appAssetLibraryImages` — attrs `fileName`, `fileSize`, `category`, optional `referenceName`; rel `assetLibrary` |
| Upload | `uploadOperations[]` → `method`/`url`/`offset`/`length`/`requestHeaders` (unauthenticated, time-limited) |
| Commit | `PATCH /v1/appAssetLibraryImages/{id}` with `uploaded: true` only (**no checksum**; size is validated against the reservation) |
| Poll | `GET /v1/appAssetLibraryImages/{id}` → `state`, `stateDetails`, `specId`, `imageAsset` |
| Place | `POST /v1/appAssetLibraryPlacements` — attrs `placementType`, `placementGroup`; rel `image` (or `video`) + exactly one parent: `appStoreVersionLocalization` / `appCustomProductPageLocalization` / `appEventLocalization` / `appStoreVersionExperimentTreatmentLocalization` |
| Order | `POST /v1/appAssetLibraryPlacementOrderingRequests` — attr `placementGroup`; rel `orderedPlacements` + parent localization |
| List placements on a surface | `GET /v1/appStoreVersionLocalizations/{id}/placements`, `GET /v1/appCustomProductPageLocalizations/{id}/placements` (`sort=placementGroupPosition`) |
| Placements of an asset | `GET /v1/appAssetLibraryImages/{id}/placements` |
| Remove a placement | `DELETE /v1/appAssetLibraryPlacements/{id}` |

Enumerations:

- `AppAssetLibraryAssetCategory`: `CREATIVE_ASSETS`, `APP_SCREENSHOTS_AND_PREVIEWS` — **set at reservation, immutable**.
- `AppAssetLibraryPlacementType`: `APP_SCREENSHOT`, `IMESSAGE_APP_SCREENSHOT`, `APP_PREVIEW`, `PRODUCT_PAGE_HEADER_ASSET`, `APP_STORE_SEARCH_RESULTS_ASSET`, `SEARCH_RESULTS_ADS_ASSET`, `TODAY_TAB_ADS_ASSET`, `EVENT_CARD_ASSET`, `EVENT_DETAILS_PAGE_ASSET`, `RETENTION_MESSAGE_ASSET`.
- Asset `state`: `AWAITING_UPLOAD` → `UPLOAD_COMPLETE` → `PREPARE_FOR_SUBMISSION` → `READY_FOR_REVIEW` → `WAITING_FOR_REVIEW` → `IN_REVIEW` → `ACCEPTED` → `APPROVED`; off-path `FAILED`, `REJECTED`, `ARCHIVED` (`COMPLETE` also exists in the enum).
- Placement `state`: `ASSET_PROCESSING`, `FAILED`, `PARENT_PREPARE_FOR_SUBMISSION` … `PARENT_APPROVED` — mirrors the parent surface's review state.
- `AppAssetLibraryFeature`: includes `APP_STORE_VERSIONS`, `CUSTOM_PRODUCT_PAGES`, `PRODUCT_PAGE_OPTIMIZATIONS`, `IN_APP_EVENTS`. Iterate the features the catalog *returns*; an absent feature is unavailable to the app.

Rules Apple states that the design depends on:

- **Placement groups and specs are runtime data.** Never hard-code `placementGroup` strings or spec ids; read the catalog. Image specs are exact dimensions for screenshots; Apple matches the uploaded file to a spec and reports `specId`, which must be checked against the intended spec.
- **Type × group × category must agree** or the placement fails with `409 ENTITY_ERROR.ATTRIBUTE.INVALID`.
- **Parent must be editable** or the placement fails with `409 STATE_ERROR.INVALID_STATE`. Editable = App Store version in `PREPARE_FOR_SUBMISSION` (and the other pre-review states), or a CPP version not yet approved.
- **Per-group limits** live in `features[].placementPolicies[].groupLimits[].maxCount` (App Store versions: 10 screenshots, 3 previews, 1 header asset per group). CPP and PPO policies differ — read, don't assume.
- **Assets with placements cannot be deleted** (`STATE_ERROR.ASSET_HAS_PLACEMENTS`); delete placements first.
- **Placements go through review with their parent surface.** Standalone asset review also exists: `reviewSubmissionItems` accepts an `appAssetLibraryImage` relationship.

### Custom product pages

| Purpose | Call |
|---|---|
| List | `GET /v1/apps/{id}/appCustomProductPages` |
| Create page | `POST /v1/appCustomProductPages` — attr `name` (req); rel `app` (req); optional inline `appCustomProductPageVersions` (attr `deepLink`) and inline localizations (attr `locale` req, `promotionalText`); optional template rel `appStoreVersionTemplate` / `customProductPageTemplate` |
| Page attrs | `name`, `url` (read-only), `visible` (PATCH) |
| Versions | `GET /v1/appCustomProductPages/{id}/appCustomProductPageVersions`; `POST /v1/appCustomProductPageVersions` (attr `deepLink`; rel `appCustomProductPage` req); `PATCH` (attr `deepLink`); attrs `state`, `version` |
| Localizations | `GET /v1/appCustomProductPageVersions/{id}/appCustomProductPageLocalizations`; `POST/PATCH/DELETE /v1/appCustomProductPageLocalizations` (attrs `locale`, `promotionalText`) |
| Keywords on a CPP localization | `GET …/{id}/searchKeywords` (filters `locale`, `platform`); `POST`/`DELETE …/{id}/relationships/searchKeywords` with `[{type, id}]` of `appKeywords` |
| Keyword pool | `GET /v1/appStoreVersionLocalizations/{id}/searchKeywords` → `AppKeyword` resources (ids opaque; read, never constructed) |
| Submit | `POST /v1/reviewSubmissions` + `POST /v1/reviewSubmissionItems` with rel `appCustomProductPageVersion` |

Constraint from Apple's help (not the API): CPP keywords are **selected** from the keywords on the latest approved app version's keyword field per localization — no free entry — and each keyword combination may belong to only one page.

### Featuring nominations

`POST /v1/nominations`, `GET /v1/nominations`, `GET|PATCH|DELETE /v1/nominations/{id}`.
Create attrs: `name` (req), `description` (req), `type` (req), `publishStartDate` (req), `submitted` (req), and optional `publishEndDate`, `deviceFamilies` (`IPHONE`, `IPAD`, …), `locales`, `notes`, `hasInAppEvents`, `launchInSelectMarketsFirst`, `preOrderEnabled`, `supplementalMaterialsUris`. Rels: `relatedApps` (req), `inAppEvents`, `supportedTerritories`. Help-page limits: name ≤ 60 chars, description ≤ 1000 chars; types as shown in the UI are App Launch / App Enhancements / New Content (API enum spelling read at runtime from an error or the docs during implementation — see Open items).

## Architecture

Four new modules, each with one purpose; `asc.py` keeps transport.

| Module | Responsibility | Depends on |
|---|---|---|
| `asokit/asc.py` (existing) | JWT, `call`/`call_all`, retry policy, version/localization lookups. **Set-based screenshot functions are removed** and replaced by `library.py`. | stdlib (+ pyjwt for `token`) |
| `asokit/library.py` (new) | Asset Library engine: catalog, library id, image upload, placements, ordering, surface inventory. Pure functions over `asc.call`. | `asc` |
| `asokit/render.py` (new) | Universal creative renderer from `assets.json`. Imports Pillow lazily; a clear error names the extra if it's missing. | Pillow (optional) |
| `asokit/creative.py` (new) | Plans and validates a creative directory (dimensions, no alpha, file type) and lints headline text against App Store rejection rules. No imaging library — reads PNG IHDR like `screenshots.py`. | stdlib |
| `asokit/cpp.py` (new) | Loads/validates `cpp.json`, diffs against live state, produces an ordered action plan, executes it via `library` + `asc`, exports Apple Ads CSV. | `asc`, `library`, `creative`, `screenshots` |
| `asokit/nominations.py` (new) | Loads/validates `nominations.json`, diffs by `name` against `GET /v1/nominations`, creates/patches. | `asc` |
| `asokit/screenshots.py` (existing) | Keeps `plan_from_directory` and `check`; `DISPLAY_SIZES` becomes a fallback used only when the catalog is unreachable during `check` (dry, offline validation). | stdlib |
| `asokit/cli.py` (existing) | New `assets`, `cpp`, `nominations` subcommands; `screenshots push` rewired. | all |

`pyproject.toml`: new optional extra `render = ["Pillow>=10"]`. Core dependencies stay `[]`.

### `library.py` interface

```python
class Catalog:
    """Parsed appAssetLibraryRefData. Built once per run."""
    @classmethod
    def fetch(cls, bearer, features=None) -> "Catalog"
    def group_for(self, feature, placement_type, display_class) -> str       # placementGroup id
    def groups_for(self, feature, placement_type) -> list[str]
    def max_count(self, feature, placement_type, group) -> int
    def accepts(self, placement_type) -> set[str]                           # asset categories
    def spec(self, spec_id) -> dict
    def specs_for(self, placement_type, group) -> list[dict]

def library_id(app_id, bearer) -> str
def upload_image(library, path_or_bytes, category, reference_name, bearer) -> str   # asset id, committed
def wait_processed(asset_ids, bearer, timeout_s=600) -> dict[str, dict]             # id -> {state, specId, stateDetails}
def placements(parent_kind, parent_id, bearer) -> list[dict]                        # sorted by group position
def place(asset_id, placement_type, group, parent_kind, parent_id, bearer) -> str
def unplace(placement_id, bearer) -> None
def order(group, placement_ids, parent_kind, parent_id, bearer) -> None
```

`parent_kind` is one of `"appStoreVersionLocalization"`, `"appCustomProductPageLocalization"` — the relationship name, used verbatim in request bodies and to build the `…/placements` path.

**Upload reuse.** Each uploaded asset gets `referenceName = "asokit:<sha256[:16]>:<original file name>"`. Before reserving, `upload_image` lists library images once per run (`GET /v1/appAssetLibraries/{id}/images` or the equivalent relationship read — exact path confirmed at implementation, see Open items) and reuses an asset whose `referenceName` hash matches and whose state is not `FAILED`/`ARCHIVED`. This makes a re-run after a partial failure upload nothing it already uploaded, and lets one file back many placements (e.g. the default variant reused across en-US/GB/CA/AU when the headline is identical).

**Spec confirmation.** After processing, the returned `specId` must be one of `catalog.specs_for(placement_type, group)`. A mismatch aborts that file's placements with a message naming expected vs matched spec.

### `render.py`

Input `assets.json` (per app, path via `--assets`, default `assets.json` next to `asokit.json`):

```json
{
  "canvas": {"width": 5244, "height": 2950},
  "brand": {"background": "#4338CA", "text": "#FFFFFF", "frame": "#1C1C1E"},
  "fonts": {"latin": "/Library/Fonts/SF-Pro-Display-Black.otf",
            "ja": ["/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", 0], "…": "…"},
  "noSpaceWrap": ["ja", "zh-Hans", "zh-Hant"],
  "rtl": ["ar-SA", "he"],
  "variants": {
    "default": {
      "captures": ["{ui}/01-log-home.png", "{ui}/03-stats-insights.png", "{ui}/04-pdf-preview.png"],
      "capturesRoot": "screenshots/store/src",
      "headlines": {"from": "screenshots/store/headlines.json", "slot": 0}
    },
    "bpd": {
      "captures": ["{ui}/06-add-entry-details.png", "{ui}/02-stats-patterns.png"],
      "capturesRoot": "screenshots/store/src",
      "headlines": {"en-US": ["TRACK BPD", "Mood swings, triggers & symptoms"], "en-GB": {"same": "en-US"}}
    }
  },
  "locales": {"en-US": {"ui": "en"}, "de-DE": {"ui": "de"}, "…": "…"}
}
```

- `headlines.from` + `slot` reuses an existing per-locale headline file shaped like MoodSync's `headlines.json` (`{locale: {"h": [[verb, descriptor], …], "same"?: locale, "rtl"?: bool, "ui": str}}`). Inline headlines are `[verb, descriptor]` or `{"same": locale}`.
- `{ui}` in capture paths is replaced by the locale's `ui` value (the captured UI language).
- Font table and wrapping rules are lifted from `compose.py` (per-script faces, per-character wrap for CJK, ZWSP-aware Thai, RTL right-aligned) into config, so no app-specific code remains in asokit.

**Layout (universal 16:9).** Two safe boxes, both centred on the canvas:

- **Header crop (21:9):** full width × `round(5244 × 9 / 21)` = 5244 × 2247.
- **Search crop (3:2):** `round(2950 × 3 / 2)` = 4425 × 2950.
- **Safe box = intersection** = **4425 × 2247**, origin (409, 351). All text and every device frame are drawn inside it; background may bleed to the full canvas.

Inside the safe box: headline block on the leading side (left for LTR, right for RTL) taking ~45% width — verb line large, descriptor smaller, both auto-fit with the `fit()` algorithm from `compose.py` (max 1 verb line, max 2 descriptor lines). Device mockups (the `device()` frame from `compose.py`) on the trailing side: 1 device centred, 2 devices side by side, 3 devices fanned with the middle one raised; device height is fixed so that the tallest device fits the safe box height minus padding. Output is RGB (no alpha), PNG, optimised.

Outputs: `<out>/<variant>/<locale>.png` and `<out>/<variant>/_contact.png` (a grid of thumbnails for every locale in the variant, for human review). `render` also prints the same TIGHT FITS report `compose.py` prints (verb shrunk below threshold, descriptor over 2 lines).

`render` runs `creative.lint()` on every headline before drawing and refuses (non-zero exit, nothing written for that variant) on a violation.

### `creative.py`

- `plan_from_directory(dir) -> {locale: Path}` for `DIR/<locale>.png` (one file per locale) — the shape `render` writes.
- `check(plan) -> [problem]`: PNG only, exactly 5244×2950, colour type without alpha (IHDR colour type 2, or 3 without a `tRNS` chunk), file ≤ 500 MB.
- `lint(text, locale) -> [problem]`: rejects currency symbols and amounts (`$`, `€`, `£`, `¥`, `R$`, digits followed by `%`), `%`, `©`, `®`, `™`, URLs/domains (`http`, `www.`, `.com`, `.app`, `.io`), "#1", ranking claims ("No. 1", "best app"), and Apple-designation phrases ("Editor's Choice", "App of the Day", "Apple Design Award") — English patterns plus a per-locale list file `asokit/data/creative_lint.json` that is extended as locales are localized. Lint is advisory-strict: it blocks `render` and `assets push`; `--no-lint` overrides with a printed warning.

### `cpp.py`

`cpp.json` (path via `--file`, default `cpp.json` next to `asokit.json`):

```json
{
  "pages": [
    {
      "name": "BPD tracker",
      "visible": true,
      "deepLink": null,
      "locales": {
        "en-US": {
          "promotionalText": "…",
          "keywords": ["bpd", "borderline", "cyclothymia"],
          "screenshots": {"dir": "screenshots/store/out/en-US", "order": ["06", "02", "03", "01"], "display": "APP_IPHONE_67"},
          "creative": "bpd"
        },
        "en-GB": {"same": "en-US"}
      }
    }
  ]
}
```

- `name`: CPP name in App Store Connect (≤ 30 chars, unique within the file) — the join key against live pages.
- `screenshots.order`: file-name prefixes selected and ordered from `dir`; omitted = all files in name order. `display` uses the existing display-type names (mapped to a placement group via the catalog, see `screenshots push`).
- `creative`: a variant name; the file is `<creativeRoot>/<variant>/<locale>.png` (`creativeRoot` from `--creative-root`, default `assets-out`).
- `{"same": locale}` copies another locale's entry (keywords are still validated against *this* locale's pool).

**Validation (`cpp check`, offline + online):**

Offline:
- Page names unique, ≤ 30 chars; ≤ 70 pages; every locale is a valid ASC locale code.
- `promotionalText` ≤ 170 chars.
- `deepLink`, if set, parses as a URI with a scheme.
- Screenshot plan passes `screenshots.check`; creative file passes `creative.check`; `≤ maxCount` per group (catalog when online, 10 offline).
- **Keyword-combination uniqueness:** for each locale, the *set* of keywords on each page must differ from every other page's set in that locale; a duplicate set is an error naming both pages. Overlap between pages (shared single keywords) is allowed but reported as a warning, since the page Apple shows for a shared keyword is not specified.

Online (needs credentials; GET only):
- Every keyword exists in that locale's pool, read from `GET /v1/appStoreVersionLocalizations/{id}/searchKeywords` on the **latest READY_FOR_SALE version** (the keyword field CPP keywords are selected from). Missing keyword → error naming the locale and listing the available keywords.
- Every locale in `cpp.json` exists on the live version (a CPP localization for a locale the app doesn't ship is rejected by Apple).

**Diff and plan (`cpp status`, `cpp push`).** For each page in the file, matched by `name` to `GET /v1/apps/{id}/appCustomProductPages`:

1. Page missing → `create_page` (name, inline version with `deepLink`, inline localizations with `promotionalText`).
2. Page exists; latest version is editable (`state` not in an approved/in-review state) → work on it. Latest version approved → `create_version` (copies nothing implicitly: every localization is re-created from the file). Latest version in review → stop for that page with "in review — re-run after review".
3. Per locale: create/patch localization (`promotionalText`); delete localizations on the editable version that are not in the file.
4. Keywords: compute desired keyword ids from the pool (match on the keyword text attribute of `AppKeyword`; exact attribute name confirmed at implementation, see Open items); `POST` additions, `DELETE` removals on `…/relationships/searchKeywords`.
5. Screenshots: replace the `APP_SCREENSHOT` placements of the target group on that localization with the planned files (unplace existing → upload/reuse → place → order).
6. Creative: replace `PRODUCT_PAGE_HEADER_ASSET` and `APP_STORE_SEARCH_RESULTS_ASSET` placements with the locale's creative (one asset, two placements, groups from the catalog under feature `CUSTOM_PRODUCT_PAGES`).
7. `visible`: PATCH the page if it differs.

Idempotence: a second `push` against an unchanged file and unchanged live state performs no writes (each step diffs first; placements are compared by asset `referenceName` hash and order).

**Submit (`cpp submit [--pages …] --apply`).** Creates one `reviewSubmission` for the app (platform `IOS`) and adds one `reviewSubmissionItem` per editable CPP version with changes; then submits it (`PATCH reviewSubmissions/{id}` `submitted: true`). Refuses if any page's placements are still `ASSET_PROCESSING` or `FAILED`.

**Apple Ads export (`cpp push --ads-export PATH` or `cpp status --ads-export PATH`).** CSV columns: `page_name, page_id, page_url, locale, keywords (semicolon-joined), deep_link`. Live `page_url` comes from the page's `url` attribute; for pages not yet created the row has an empty URL.

### `nominations.py`

`nominations.json`:

```json
{
  "nominations": [
    {
      "name": "MoodSync 2.2 — German & French",
      "type": "APP_ENHANCEMENTS",
      "description": "…",
      "publishStartDate": "2026-10-27",
      "publishEndDate": null,
      "deviceFamilies": ["IPHONE", "IPAD"],
      "locales": ["de-DE", "fr-FR"],
      "notes": "…",
      "relatedApps": [6757342494],
      "supplementalMaterialsUris": []
    }
  ]
}
```

- `check`: name ≤ 60, description ≤ 1000, `publishStartDate` ≥ today + 14 days (warning, not error — Apple's minimum notice), required fields present, `type` in the API enum.
- `push --apply`: matches by `name` against `GET /v1/nominations` (filtered to the app); missing → `POST` with `submitted: false`; existing and not yet submitted → `PATCH` changed attributes; existing and submitted → skipped with a note. **`--submit`** additionally sets `submitted: true` on the nominations in the file (requires `--apply`; prints each nomination being submitted first).

## Commands

All read the app id from `asokit.json` (`app.appId`) or `--app-id`, like existing commands. Every write command is dry-run unless `--apply`.

| Command | Reads | Writes (with `--apply`) |
|---|---|---|
| `assets render [--assets F] [--variant V …] [--locales L,…] [--out DIR]` | `assets.json`, captures | local PNGs only |
| `assets status` | library, assets (state), header/search placements on the editable version and every CPP's latest version | — |
| `assets push DIR --target default\|cpp:<name> [--locales …]` | `DIR/<locale>.png`, catalog, surface | uploads, header + search placements per locale |
| `screenshots status` | unchanged output; now reads placements | — |
| `screenshots push DIR --display T [--locales] [--mirror …] [--mirror-from L]` | unchanged flags | same semantics (replace the group per locale), via library |
| `cpp check [--file F] [--offline]` | `cpp.json`, live keyword pool unless `--offline` | — |
| `cpp status [--file F] [--ads-export P]` | live pages | CSV file only |
| `cpp push [--file F] [--pages …] [--locales …] [--ads-export P]` | everything above | pages, versions, localizations, keywords, placements |
| `cpp submit [--pages …]` | editable versions + placement states | review submission |
| `nominations check [--file F]` | file | — |
| `nominations push [--file F] [--submit]` | live nominations | create/patch; submit with `--submit` |

### `assets push` details

- `--target default` → the editable App Store version (`asc.editable_version`); none → error "no editable version — create the next version in App Store Connect first; default-page creatives ride with it". Feature for catalog lookups: `APP_STORE_VERSIONS`.
- `--target cpp:<name>` → that page's editable version (creating a new version if the latest is approved, same rule as `cpp push` step 2). Feature: `CUSTOM_PRODUCT_PAGES`.
- Per locale: upload/reuse the file (category `CREATIVE_ASSETS`), wait for processing, confirm `specId`, unplace existing header + search placements on that localization, place both, done.
- Locales in `DIR` with no localization on the surface → error before any write.
- **Running PPO test**: before writing to `default`, `GET /v1/appStoreVersions/{id}/appStoreVersionExperimentsV2` (or the app-level experiments read); if any experiment is running, abort with the experiment name — field reports say placement fails while one runs.

### `screenshots push` migration

- Flags, plan format, validation, mirroring, and output lines unchanged.
- `--display` keeps the legacy display-type names (`APP_IPHONE_67`, `APP_IPAD_PRO_3GEN_129`, `APP_WATCH_ULTRA`, …). A static map translates each to an `AppAssetLibraryDisplayClass` (`APP_IPHONE_67` → `IPHONE_DYNAMIC_ISLAND_LARGE_DISPLAY`, `APP_IPHONE_61` → `IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY`, `APP_IPHONE_65` → `IPHONE_FACE_ID_LARGE_DISPLAY`, `APP_IPAD_PRO_3GEN_129` → `IPAD_13_DISPLAY`, `APP_IPAD_PRO_129` → `IPAD_129_DISPLAY`, `APP_WATCH_ULTRA` → `WATCH_ULTRA`, `APP_WATCH_SERIES_10` → `WATCH_SERIES_10`); the catalog's `placementProfileGroups` then yields the placement group for `(APP_SCREENSHOT, display class)`. The display class map is the only static table; group ids are never hard-coded.
- Mirroring reads the source locale's placements (`sort=placementGroupPosition`) and **re-places the same asset ids** on the other locales — no download/re-upload (the old path downloaded bytes from the CDN).
- Replacement order per locale and group: upload/reuse all new files → wait processed → unplace old placements → place new → order. Uploading first means a failed upload leaves the live set untouched.
- `screenshots status` prints the same `{locale: {display: count}}`, derived from placements grouped by `placementGroup` and mapped back to the legacy display names.

## Data flow (MoodSync)

```
capture_store.sh → screenshots/store/src/<ui>/*.png
                 ├─ compose.py → screenshots/store/out/<locale>/NN-*.png ─┬─ screenshots push (default page)
                 │                                                        └─ cpp push (CPP screenshots, reordered per page)
                 └─ asokit assets render (assets.json) → assets-out/<variant>/<locale>.png
                                                        ├─ assets push --target default
                                                        └─ cpp push (creative per page)
asokit cpp check ← live keyword pool (READY_FOR_SALE version)
asokit cpp push --ads-export ads-groups.csv → Apple Ads ad groups (manual)
asokit nominations push → draft nomination (submit later with --submit)
```

## Errors and safety

- **Dry run by default.** Every write path prints the full action list and "DRY RUN — nothing written".
- **Validate everything before the first write.** `push` commands run their `check` first; any problem → "validation failed — nothing sent" and exit 1 (existing idiom).
- **Upload before unplace.** A failed upload or a processing `FAILED` leaves the live placements intact.
- **Never delete assets.** Only placements are removed. Assets accumulate in the library; that is harmless and keeps re-runs cheap.
- **Never touch approved surfaces.** Writes only go to an editable App Store version or a CPP version that is not approved/in review; anything else stops with a message.
- **Token freshness.** Re-mint the JWT per locale on `--apply` (existing pattern) and before every poll loop.
- **Retry policy unchanged.** 429 retried for any method; 5xx retried for GET only. Re-runs converge because every step diffs live state first.
- **Partial failure.** On abort, print what completed and that a re-run is safe (existing message pattern).
- **Destructive diffs are visible.** `cpp push` dry run lists every localization deletion and keyword removal explicitly; `--pages`/`--locales` scope a push so a partial file cannot delete other pages' data (pages not in the file are never touched; localizations are deleted only on pages in scope).
- **ASC write authorization.** These are new App Store Connect write paths. The user authorized them for this project on 2026-10-11 under the dry-run-default + explicit `--apply` rule.

## Testing

Unit tests (`unittest`, stdlib), following `tests/test_screenshots.py` / `test_asc.py`: a fake App Store Connect object with an in-memory model and a `call(method, path, bearer, body)` that the tests install over `asc.call`.

- `test_library.py`: catalog traversal (feature → policy → group → spec), `max_count`, category acceptance; upload reserve/upload/commit sequence and byte slicing per `uploadOperations`; reuse by `referenceName` hash; `specId` mismatch aborts; placement replace order (upload → unplace → place → order); `ASSET_HAS_PLACEMENTS` never triggered (no asset deletes issued).
- `test_creative.py`: dimension and alpha detection (colour types 2, 3, 3+tRNS, 4, 6); lint positives/negatives per rule.
- `test_render.py` (skipped when Pillow is absent): output is 5244×2950 RGB; every non-background pixel of text and devices lies inside the safe box (render a variant on a sentinel background and scan); RTL places the headline on the right; CJK wraps per character; `{"same": …}` and `headlines.from` resolution.
- `test_cpp.py`: validation (name length, promo length, combination uniqueness error, overlap warning, unknown keyword, unknown locale); plan for new page / editable version / approved version (new version) / in-review (stop); keyword add/remove diff; second push is a no-op; `--pages` scoping never touches other pages; ads CSV shape.
- `test_nominations.py`: validation; create vs patch vs skip-submitted; `--submit` only with `--apply`.
- `test_screenshots.py` updated: legacy display name → display class → group via catalog; mirror re-places asset ids without download; `status` maps groups back to display names.
- CLI tests in `test_cli.py` for argument wiring and dry-run output.

Live verification (in order, each gated on the previous):

1. `asokit assets status` and `asokit cpp status` against MoodSync — read-only; confirms paths, catalog shape, keyword `AppKeyword` attributes.
2. `asokit cpp check` online against the real keyword pool.
3. Dry runs of `assets push`, `cpp push`, `nominations push`, `screenshots push`.
4. `cpp push --pages "BPD tracker" --locales en-US --apply` — one page, one locale. User inspects it in App Store Connect.
5. Remaining pages and locales; `cpp submit` once the user confirms.
6. `nominations push --apply` (draft); submission later by explicit `--submit`.
7. `assets push --target default` only when the next app version exists in Prepare for Submission.

## MoodSync content (first consumer)

Lives in the MoodSync repo, not asokit:

- `assets.json` at repo root (next to `asokit.json`): brand `#4338CA`, fonts from `compose.py`, locales/ui from `headlines.json`.
  - Variant **default**: headline from `headlines.json` slot 0 per locale (all 39 locales, already translated); captures: log home, stats insights, PDF preview.
  - Variants **bpd**, **meds-sleep**, **depression-anxiety**, **report**: English headlines (en-US; en-GB/CA/AU `same`), captures chosen per intent.
- `cpp.json`: four pages, en-US + en-GB + en-CA + en-AU:

| Page | Keywords (must exist in the live keyword field; confirmed by `cpp check`) | Screenshot lead | Creative |
|---|---|---|---|
| BPD tracker | `bpd`, `borderline`, `cyclothymia` | entry details (symptom scales), patterns | `bpd` |
| Meds & sleep | `medication`, `symptom` (+ `sleep` if present) | Health autofill settings, entry details | `meds-sleep` |
| Depression & anxiety | `depression`, `mental`, `health` (+ `anxiety` if present) | weekly review, patterns | `depression-anxiety` |
| Therapist report | none (Apple Ads + link only until the keyword field changes) | PDF preview, insights | `report` |

  The en-US keyword field is read live; the table's keywords are drawn from the en-AU field in `all-locales-metadata.json` and adjusted after step 1 of live verification.
- `nominations.json`: one draft, type App Enhancements, for the 2.2 German/French localization release.
- `.gitignore`: `assets-out/`.

Promo text and headline copy for the four pages is drafted during implementation and reviewed by the user before `--apply`.

## Open items (resolved during implementation, read-only)

1. Exact path to list library images for reuse (`GET /v1/appAssetLibraries/{id}/…` relationship name) — read from the `app-asset-libraries` reference.
2. `AppKeyword` attribute carrying the keyword text (the resource page lists only `id`/`type`/`links`; text may be the id itself) — confirmed by `cpp status` against the live app.
3. Nomination `type` enum spelling (`APP_ENHANCEMENTS` vs `APP_ENHANCEMENT`) — read from the `Nomination` reference.
4. CPP placement-policy limits for header/search (`CUSTOM_PRODUCT_PAGES` feature in the catalog).
5. Running-experiment read path for the PPO guard.

None of these change the design; each is a field name or path confirmed by one GET.
