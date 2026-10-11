# Asset Library, creative assets, custom product pages and featuring nominations

**Date:** 2026-10-11 (rev. 2 — after three-agent review: API correctness, codebase fit, ASO/safety)
**Status:** Draft — awaiting user review
**Driving app:** MoodSync (ASC app id `6757342494`), then the rest of the portfolio
**Background research:** `~/Projects/mobileapps/docs/app-store-oct-2026-dossier.md`

## Problem

On 2026-10-05 Apple shipped two new App Store surfaces — a **product page header** and a **search results asset** (iOS 27+/iPadOS 27+) — and the **App Asset Library**, a per-app media library where an asset is uploaded once and *placed* on any number of surfaces. With it, the set-based screenshot resources `asokit screenshots push` uses (`appScreenshotSets`, `appScreenshots`, `appPreviewSets`, `appPreviews`) are **deprecated** (App Store Connect API 4.5.1 release notes).

The portfolio cannot use any of this without hand work in the web UI:

1. Nothing renders the new 16:9 creative per app and per locale. MoodSync has a bespoke portrait compositor (`screenshots/store/compose.py`); nothing is shared across apps.
2. Nothing uploads or places creatives. The search asset *replaces* the screenshot strip in search, so it is the highest-leverage item for a search-driven app, and it wants a localized file per storefront (39 for MoodSync).
3. **Custom product pages (CPPs)** can carry their own search keywords (Oct 2025) and their own creatives. By hand that is page × locale × (promo text, keywords, screenshots, creatives, review) with no trail, and keyword routing mistakes silently move the default page's traffic to a weaker page.
4. **Featuring nominations** have an API (`/v1/nominations`) but are filed by hand.

## Goals

- Render a localized universal creative (5244×2950 PNG) per app, per variant, per locale from a declarative config — no per-app rendering code in asokit.
- Upload and place creatives on the default product page and on CPPs through the Asset Library.
- Declare CPPs in `cpp.json` and converge App Store Connect to it idempotently, **without ever changing organic search routing unless explicitly published**.
- Validate CPP keywords against the live keyword pool, against each other, and against live pages before any write; protect the default page's core keywords.
- Record every applied change in a local ledger so results can be measured against go-live dates.
- Offer a library-based engine for `asokit screenshots push`, opt-in until verified at parity with the current set-based engine.
- Create featuring nominations from a file, as drafts by default.
- Every write is a dry run unless `--apply`; every review submission or visibility change needs its own explicit flag.
- `asokit` core stays stdlib-only; rendering is an optional extra.

## Non-goals

- **iPhone Duo.** Deferred by decision. When picked up it needs one display-class map entry and a render canvas; groups and specs come from the catalog.
- **Video creatives and app previews.** Images first; `appAssetLibraryVideos` mirrors the image flow.
- **Dedicated 21:9 / 3:2 files.** One universal 16:9 file serves both placements.
- **Retention Messaging** (API prerelease), **PPO tests**, **new in-app deep links** (MoodSync handles only `moodsync://log?mood=N`), **deleting CPPs or assets**, **submitting the app version** (default-page creatives ride with it; the user submits).
- **Placing creatives on the live (Ready for Sale) version.** Help docs describe updating a live version with approved assets; the API guide says placements need an editable parent. Unverified, so out of scope; see Future.
- **Apple Ads API.** The ads export is a CSV the user applies by hand.

## Verified API surface

Source: Apple's App Store Connect API reference (DocC JSON at `developer.apple.com/tutorials/data/documentation/appstoreconnectapi/<slug>.json`) and App Store Connect Help, read 2026-10-11. "Help:" marks help-page evidence; "Field report" marks third-party observation.

### Asset Library

| Purpose | Call |
|---|---|
| Library id (stable) | `GET /v1/apps/{id}/assetLibrary` |
| Spec catalog | `GET /v1/appAssetLibraryRefData` (filters `features`, `placementTypes`, `placementProfileGroups`, `specs`; sparse fields) — one `AppAssetLibraryRefDatum` with six parallel arrays: `features`, `placementProfileGroups`, `placementTypes`, `imageSpecs`, `videoSpecs`, … |
| List library images | `GET /v1/appAssetLibraries/{id}/images` — `filter[referenceName\|state\|category\|specId\|id]`, `include=placements`, `limit` ≤ 200 |
| Reserve image | `POST /v1/appAssetLibraryImages` — attrs `fileName`, `fileSize`, `category` (req), `referenceName` (opt); rel `assetLibrary` (req) |
| Upload | `uploadOperations[]` (`method`, `url`, `offset`, `length`, `requestHeaders`); URLs unauthenticated and time-limited |
| Commit | `PATCH /v1/appAssetLibraryImages/{id}` `uploaded: true` only — no checksum; size validated against the reservation |
| Poll | `GET /v1/appAssetLibraryImages/{id}` (or batch via the list endpoint `filter[id]=a,b,c`) → `state`, `stateDetails`, `specId`, `imageAsset` |
| Place | `POST /v1/appAssetLibraryPlacements` — attrs `placementType`, `placementGroup`; rel `image`/`video` + exactly one parent: `appStoreVersionLocalization`, `appCustomProductPageLocalization`, `appEventLocalization`, `appStoreVersionExperimentTreatmentLocalization` |
| Remove placement | `DELETE /v1/appAssetLibraryPlacements/{id}` (204). Placements **cannot be modified**: delete, create, reorder |
| Order | `POST /v1/appAssetLibraryPlacementOrderingRequests` — attr `placementGroup`; rels `orderedPlacements` + one localization parent |
| Placements on a surface | `GET /v1/appStoreVersionLocalizations/{id}/placements`, `GET /v1/appCustomProductPageLocalizations/{id}/placements` (`sort=placementGroupPosition`, `include=image`) |

Enumerations: asset `category` `CREATIVE_ASSETS` / `APP_SCREENSHOTS_AND_PREVIEWS` (immutable after reservation); placement types `APP_SCREENSHOT`, `IMESSAGE_APP_SCREENSHOT`, `APP_PREVIEW`, `PRODUCT_PAGE_HEADER_ASSET`, `APP_STORE_SEARCH_RESULTS_ASSET`, `SEARCH_RESULTS_ADS_ASSET`, `TODAY_TAB_ADS_ASSET`, `EVENT_CARD_ASSET`, `EVENT_DETAILS_PAGE_ASSET`, `RETENTION_MESSAGE_ASSET`; asset states `AWAITING_UPLOAD`, `UPLOAD_COMPLETE`, `COMPLETE`, `PREPARE_FOR_SUBMISSION`, `READY_FOR_REVIEW`, `WAITING_FOR_REVIEW`, `IN_REVIEW`, `ACCEPTED`, `APPROVED`, `FAILED`, `REJECTED`, `ARCHIVED`; placement states `ASSET_PROCESSING`, `FAILED`, `PARENT_PREPARE_FOR_SUBMISSION` … `PARENT_APPROVED`; features include `APP_STORE_VERSIONS`, `CUSTOM_PRODUCT_PAGES`, `PRODUCT_PAGE_OPTIMIZATIONS`, `IN_APP_EVENTS` (iterate the features the catalog returns).

Rules the design depends on:

- **Groups and specs are runtime data.** Read the catalog; resolve a file to a group by its matched `specId` → `placementTypes[].specMappings` → group → `placementProfileGroups[].displayClassId`.
- **Type × group × category must agree** (else `409 ENTITY_ERROR.ATTRIBUTE.INVALID`).
- **Parent must be editable** (else `409 STATE_ERROR.INVALID_STATE`).
- **Per-group limits** from `features[].placementPolicies[].groupLimits[].maxCount` (App Store versions: 10 screenshots, 3 previews, 1 header asset per group); CPP/PPO policies differ.
- **Assets with placements cannot be deleted** (`STATE_ERROR.ASSET_HAS_PLACEMENTS`).
- **Universal creative:** 5244×2950 PNG, no alpha, accepted for both header and search; one universal asset may back both placements (Help: "you can use it for both your product page header and search results placement"). Whether header/search groups are split per device family is catalog data — the code places into **every** group of the type whose spec mapping contains the matched spec.
- **Crop anchor** of the 21:9 header and 3:2 search crops is undocumented; centred is assumed (see `render.py`).
- **Rate limit:** `X-Rate-Limit: user-hour-lim:3500;user-hour-rem:N` per key per rolling hour.

### Custom product pages

| Purpose | Call |
|---|---|
| List pages | `GET /v1/apps/{id}/appCustomProductPages` — attrs `name`, `url`, `visible` |
| Create page | `POST /v1/appCustomProductPages` — attr `name` (req); rel `app` (req); rel `appCustomProductPageVersions` with `${local-id}` placeholders resolved from `included[]`: an `AppCustomProductPageVersionInlineCreate` (attr `deepLink`; rel `appCustomProductPageLocalizations` → placeholders) and `AppCustomProductPageLocalizationInlineCreate` items (attr `locale` req, `promotionalText`); optional rel `appStoreVersionTemplate` (Help: copies the product page for the primary localization) or `customProductPageTemplate`. Precondition (Help): app Ready for Distribution in ≥ 1 region |
| Page visibility | `PATCH /v1/appCustomProductPages/{id}` `visible` |
| Versions | `GET /v1/appCustomProductPages/{id}/appCustomProductPageVersions` (filter `state`); `POST /v1/appCustomProductPageVersions` (attr `deepLink`; rel `appCustomProductPage`); `PATCH` (`deepLink`) |
| Version `state` | `PREPARE_FOR_SUBMISSION`, `READY_FOR_REVIEW`, `WAITING_FOR_REVIEW`, `IN_REVIEW`, `ACCEPTED`, `APPROVED`, `REPLACED_WITH_NEW_VERSION`, `REJECTED`; `version` is a string |
| Localizations | `GET …/appCustomProductPageVersions/{id}/appCustomProductPageLocalizations`; `POST/PATCH/DELETE /v1/appCustomProductPageLocalizations` (`locale`, `promotionalText`). Promo text editable at any time except during review |
| CPP keywords | `GET /v1/appCustomProductPageLocalizations/{id}/searchKeywords`; `POST`/`DELETE …/{id}/relationships/searchKeywords` body `[{type: "appKeywords", id}]`. Assignable any time except during review (Help) |
| Keyword pool | `GET /v1/appStoreVersionLocalizations/{id}/searchKeywords` on the latest approved version; cross-check `GET /v1/apps/{id}/searchKeywords?filter[locale]=…`. `AppKeyword` has **no attributes**: the keyword text is the `id` |
| Review | `GET /v1/reviewSubmissions?filter[app]=…&filter[platform]=IOS&filter[state]=…` (filter[app] required); `POST /v1/reviewSubmissions`; `POST /v1/reviewSubmissionItems` rel `appCustomProductPageVersion` or `appAssetLibraryImage`; `PATCH /v1/reviewSubmissions/{id}` `submitted: true`; `GET /v1/reviewSubmissions/{id}/items` |
| Experiments (PPO guard) | `GET /v1/apps/{id}/appStoreVersionExperimentsV2?filter[state]=…` — states `PREPARE_FOR_SUBMISSION`, `READY_FOR_REVIEW`, `WAITING_FOR_REVIEW`, `IN_REVIEW`, `ACCEPTED`, `APPROVED`, `REJECTED`, `COMPLETED`, `STOPPED` |

Apple's keyword guidance (Help): keywords are selected from the latest approved version's keyword field per localization; a page appears in search "for those selected keywords, rather than your default product page"; "select a unique set of keywords for each page" is phrased as a **tip, not an enforced rule**; a page is searchable "only after it's approved and set to visible"; deep links require review.

### Featuring nominations

`GET /v1/nominations` (**`filter[state]` required**: `DRAFT`, `SUBMITTED`, `ARCHIVED`; also `filter[relatedApps]`, `filter[type]`), `POST /v1/nominations`, `GET|PATCH|DELETE /v1/nominations/{id}`.
Create attrs: `name`, `description`, `type` (`APP_LAUNCH`, `APP_ENHANCEMENTS`, `NEW_CONTENT`), `publishStartDate` (**date-time**), `submitted` — all required; optional `publishEndDate` (date-time), `deviceFamilies` (`IPHONE`, `IPAD`, `APPLE_TV`, `APPLE_WATCH`, `MAC`, `VISION`), `locales`, `notes`, `hasInAppEvents`, `launchInSelectMarketsFirst`, `preOrderEnabled`, `supplementalMaterialsUris`. Rels: `relatedApps` (req, `{type: "apps", id: "<string>"}`), `inAppEvents`, `supportedTerritories`. Help limits: name ≤ 60, description ≤ 1000; ≥ 2 weeks' notice.

## Architecture

House pattern (as in `products.py` / `screenshots.py` vs `asc.py`): **pure modules load, validate and plan; network executors live beside `asc`**. All network code calls `asc.call` / `asc._raw` through the module attribute so the existing fake-connect test patching intercepts it.

| Module | Responsibility | Depends on |
|---|---|---|
| `asc.py` (existing) | JWT, `call`/`call_all`, retry, version lookups. Gains: rate-limit header parsing with backoff below 10 % remaining; a `bearer` provider (`asc.Bearer`) that re-mints the JWT when < 3 min of validity remain. Set-based screenshot functions **stay** (legacy engine). | stdlib, pyjwt |
| `library.py` (new) | Asset Library executor: `Catalog`, library id, upload/reuse, batch wait, placements, ordering, surface inventory. | `asc` |
| `creative.py` (new, pure) | Plan/validate a creative directory; lint text. | stdlib |
| `render.py` (new) | Render universal creatives from `assets.json`. Lazy Pillow import with a clear error naming `pip install 'aso-keyword-toolkit[render]'`. | Pillow ≥ 10.1 (optional) |
| `cpp.py` (new, pure) | Load/validate `cpp.json`; build a plan from (file, live snapshot); ads CSV. | `creative`, `screenshots` |
| `cpp_apply.py` (new) | Snapshot live CPP state; execute a `cpp` plan; publish; submit. | `asc`, `library`, `cpp` |
| `nominations.py` (new) | Load/validate/plan (pure) + push executor (small enough for one file). | `asc` |
| `ledger.py` (new) | Append-only `asokit-ledger.jsonl` next to `asokit.json`. | stdlib |
| `screenshots.py` (existing) | Unchanged `plan_from_directory`/`check` (static `DISPLAY_SIZES` stays the offline check). | stdlib |
| `cli.py` (existing) | New `assets`, `cpp`, `nominations` subcommands; `screenshots push/status --engine`. | all |

`pyproject.toml`: extra `render = ["Pillow>=10.1"]`; `[tool.setuptools.package-data] asokit = ["data/*.json"]` for `asokit/data/creative_lint.json`. Core `dependencies = []` unchanged.

### `library.py`

```python
class Catalog:
    @classmethod
    def fetch(cls, bearer, features=None) -> "Catalog"
    def features(self) -> set[str]
    def supports(self, feature, placement_type) -> bool
    def groups_for_spec(self, feature, placement_type, spec_id) -> list[str]   # every group whose specMappings contain spec_id
    def specs_matching(self, placement_type, width, height) -> list[dict]       # by exact dimensions
    def max_count(self, feature, placement_type, group) -> int
    def accepts(self, placement_type) -> set[str]                                # asset categories
    def display_class(self, group) -> str

def library_id(app_id, bearer) -> str
def find_reusable(library, sha, category, bearer) -> dict | None
def upload_image(library, name, data, category, bearer) -> str      # reserve → PUT parts → commit
def wait_processed(ids, bearer, timeout_s=900) -> dict[str, dict]    # batch poll, backoff 5 → 30 s, re-mints bearer each iteration
def surface_placements(parent_kind, parent_id, bearer) -> list[dict] # include=image, sorted by group position
def place(asset_id, placement_type, group, parent_kind, parent_id, bearer) -> str
def unplace(placement_id, bearer) -> None
def order(group, placement_ids, parent_kind, parent_id, bearer) -> None   # then re-read to verify order
def replace_group(desired_asset_ids, placement_type, group, parent_kind, parent_id, max_count, bearer, apply) -> list[action]
```

`parent_kind` ∈ `appStoreVersionLocalization`, `appCustomProductPageLocalization` — the relationship name used verbatim in bodies and paths. `bearer` arguments accept a string (tests) or an `asc.Bearer`.

**Upload reuse.** `referenceName = "asokit:" + sha256[:16] + ":" + file_name[:40]`. Before reserving, `find_reusable` queries `…/images?filter[referenceName]=…&filter[category]=…`. Reuse rules:

| Found state | Action |
|---|---|
| `UPLOAD_COMPLETE`, `COMPLETE`, `PREPARE_FOR_SUBMISSION`, `READY_FOR_REVIEW`, `WAITING_FOR_REVIEW`, `IN_REVIEW`, `ACCEPTED`, `APPROVED` | reuse |
| `AWAITING_UPLOAD` (orphaned reservation; URLs expired), `FAILED`, `ARCHIVED` | ignore; reserve fresh |
| `REJECTED` | stop for that file: "this exact image was rejected by App Review — change it" |

Each run also keeps an in-memory `{(sha, category): id}` cache so identical files in one run (e.g. `same` locales) upload once.

**Spec confirmation.** After processing, `specId` must be among `catalog.specs_matching(type, w, h)` and have at least one group in `groups_for_spec`; otherwise that file's placements are skipped and the run reports expected vs matched spec.

**`replace_group` (the only placement mutator).**
1. Read current placements of `(type, group)` on the parent with their asset ids.
2. If the asset-id sequence already equals `desired` → no writes.
3. If `len(current) + len(desired) ≤ max_count` → place all new, then unplace old, then order. Otherwise → unplace old, place new, order; on abort between the two, report "`<locale>` `<group>` left with N of M placements — re-run".
4. Order, then re-read and verify the sequence.

### Run shape (every write command)

Two phases, so nothing destructive happens until every file in scope is accepted:

1. **Prepare** — validate offline → fetch catalog + live snapshot → validate online → upload/reuse every file in scope → one `wait_processed` over all ids → spec confirmation. Any failure: stop; live surfaces untouched.
2. **Apply** — per surface/locale: `replace_group` / CPP writes in plan order; re-mint bearer per locale; ledger entry per write.

Dry run executes Phase 1's reads (no uploads) and prints the full action list, using `(new)` placeholders for parents that do not exist yet.

### `creative.py` (pure)

- `plan_from_directory(dir) -> {locale: Path}` for `DIR/<locale>.png`; files and folders starting with `_` or `.` are ignored.
- `check(plan, expected=(5244, 2950), max_bytes=None) -> [problem]`: PNG signature; exact expected size (online callers pass the catalog spec's size and `maxFileSize`); bit depth 8; colour type 2 (RGB) — reject 0/4 (grayscale), 6 (RGBA), and 3 with a `tRNS` chunk.
- `lint(text, locale) -> [problem]`, rules from `asokit/data/creative_lint.json`, matched case-insensitively on word boundaries:
  - **Pricing/offers:** currency symbols and amounts (`$ € £ ¥ R$`), `%`, free, trial, sale, discount, "off".
  - **Links/marks:** `http`, `www.`, domains (`.com .app .io .net .org`), `©`, `®`, `™`.
  - **Rank/award claims:** "#1", "No. 1", "number one", "best", "top-rated", "award", "Editor's Choice", "App of the Day", "Apple Design Award".
  - **Other platforms:** Android, Google Play, Galaxy, Wear OS, Fitbit, Samsung.
  - **Health/medical claims:** diagnose/diagnosis, treat/treatment, cure, prevent, predict, detect/early detection, clinical-grade, clinically proven, FDA, "medical device", "doctor/psychiatrist/therapist approved|recommended".
  - **Distress content:** suicide, self-harm, overdose, crisis.
  - Launch coverage: `en`, `de`, `fr`, `es`, `pt`, `it` word lists (the languages MoodSync ships UI in, plus Italian). Locales without a list get a **warning** ("unlinted — needs native review") listed at the end of the run; `--strict-lint` turns warnings into errors.
- Lint runs where text exists: `assets render` (headlines) and `cpp check`/`push` (`promotionalText`). A violation fails that locale; `--no-lint` overrides with a printed warning per suppressed hit.

### `render.py`

`assets.json` (path `--assets`, default next to `asokit.json`):

```json
{
  "canvas": {"width": 5244, "height": 2950},
  "safeInset": 0.03,
  "brand": {"background": "#4338CA", "text": "#FFFFFF", "frame": "#1C1C1E"},
  "fonts": {
    "default": {"path": "/Library/Fonts/SF-Pro-Display-Black.otf"},
    "ja": {"path": "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", "index": 0},
    "ar-SA": {"path": "/System/Library/Fonts/SFArabic.ttf", "variation": "Bold"}
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
      "capturesRoot": "screenshots/store/src",
      "headlines": {"en-US": ["LOG MOOD SWINGS", "Triggers, symptoms & patterns"], "en-GB": {"same": "en-US"}},
      "ui": "en"
    }
  }
}
```

Fonts and type sizes are **keyed by locale** (as in `compose.py`), each entry `{path, index?, variation?}`; `default` covers the rest.

Headline resolution:

- `headlines.from` reads a file shaped like MoodSync's `headlines.json` (`{locale: {"h": [[verb, descriptor], …] | "same": locale, "ui": str, "rtl"?: bool}}` plus `_`-prefixed metadata keys, which are skipped). `slot` is an index or a `_slots` name; if the locale entry lacks that slot (e.g. a new `"hero"` key `{"hero": [verb, descriptor]}`), `fallbackSlot` is used and the locale is listed as "fallback". `same` resolves one hop. `ui` and `rtl` come from the source file.
- Inline headlines: `[verb, descriptor]` or `{"same": locale}`; `ui` from the variant (`"ui"` key) or per-locale `{"h": [...], "ui": ...}`; `rtl` from a top-level `rtl` list.
- A variant renders exactly the locales it can resolve a headline for, intersected with `--locales`; a requested locale it cannot resolve is an error.

**Geometry.** Header crop 21:9 = 5244 × 2247.43 (origin y 351.29); search crop 3:2 = 4425 × 2950 (origin x 409.5). **Safe box = intersection** = 4425 × 2247.43 centred; the code floors the origin and ceils the inset to integer pixels (409, 351, 4426, 2249 → box (409, 351)–(4835, 2600)), then shrinks by `safeInset` (3 %) on every side because the crop anchor is undocumented. All text, device frames **and their shadows** are drawn inside the inset safe box; only the flat background bleeds.

**Layout.** Headline block on the leading side (left LTR, right RTL), ~44 % of safe-box width; verb then descriptor, fitted with the `compose.py` algorithm parameterised by `type`. If a line still does not fit at `min` within `lines`, **the locale fails** (no overflow fallback). Devices on the trailing side: **1 or 2 devices** (3 is rejected — illegible at search-row size), the `compose.py` flat frame, sized so device height = inset safe-box height × 0.92; two devices sit side by side with 4 % overlap, the second offset down 6 %. Output RGB PNG, optimised.

**Outputs.** `<out>/<variant>/<locale>.png`; contact sheets in `<out>/_contact/<variant>.png`. A report prints per locale: verb/descriptor sizes, lines, TIGHT flags (below `tight` thresholds), fallback headline use, and device width as % of canvas.

**RTL.** Requires Pillow built with libraqm. If any RTL locale is in scope and `PIL.features.check("raqm")` is false, `render` stops with an install hint before drawing.

`render.py` duplicates `compose.py`'s `fit`/`wrap`/`device` logic. Accepted for now; porting MoodSync's portrait compositor onto `render.py` is a later, separate change.

### `cpp.py` (pure) and `cpp_apply.py`

`cpp.json` (path `--file`, default next to `asokit.json`):

```json
{
  "protectedKeywords": {"*": ["cyclothymia", "depression", "hypomania", "mania", "episode"]},
  "pages": [
    {
      "name": "BPD tracker",
      "deepLink": null,
      "template": "appStoreVersion",
      "locales": {
        "en-US": {
          "promotionalText": "…",
          "keywords": ["bpd", "borderline"],
          "screenshots": [
            {"dir": "screenshots/store/out/en-US", "order": ["06", "02", "03", "01"], "display": "APP_IPHONE_67"}
          ],
          "creative": "bpd"
        },
        "en-GB": {"same": "en-US", "keywords": ["bpd", "borderline"]}
      }
    }
  ]
}
```

- `name` ≤ 30 chars, unique — the join key with live pages.
- `template: "appStoreVersion"` creates the page from the current App Store version so every device family (iPhone, iPad, Watch) inherits the default screenshots; `screenshots` then replaces only the listed families. Without a template, `cpp check` requires a `screenshots` entry for every family the app's live version has.
- `screenshots[]`: one entry per family; `order` selects and orders by file-name prefix; `display` is a legacy display-type name. Online, the group is resolved from the files' pixel dimensions via the catalog; the legacy name is only a tie-breaker (e.g. Watch 410×502 matches both Series 10 and Ultra).
- `creative`: variant name → `<creativeRoot>/<variant>/<locale>.png` (`--creative-root`, default `assets-out`).
- `same` copies `promotionalText`, `screenshots`, `creative` and `deepLink` — **never keywords**; keywords are always explicit per locale (pools differ by locale).
- There is **no `visible` field**. New pages are created hidden; visibility changes only through `cpp publish`.

**Validation (`cpp check`).**

Offline:
- Names unique and ≤ 30 chars; locales are valid ASC codes; `promotionalText` ≤ 170 and passes lint; `deepLink` parses with a scheme (warning: "deep-link changes require review").
- Screenshot plans pass `screenshots.check` (≤ 10 per family); creative files pass `creative.check`.
- **Keyword ownership (asokit policy, stricter than Apple's tip):** within a locale, a keyword may belong to at most one page. Empty keyword sets are allowed on any number of pages.
- **Protected keywords:** assigning any keyword listed in `protectedKeywords["*"]` or `protectedKeywords["<locale>"]` is an error unless `--allow-protected <kw,…>` names it.

Online (GET only; also run automatically by `push`):
- Every keyword is in that locale's pool (matched case- and whitespace-insensitively against `AppKeyword` ids, read from the **latest approved** version; also checked against the **editable** version's pool if one exists — a keyword missing there is a warning: "will stop routing when the next version ships").
- Keyword ownership includes **live pages not in the file** (their keywords are read from their latest live version).
- Page count (live + new) ≤ 70; locales exist on the latest approved version.
- If the catalog's `CUSTOM_PRODUCT_PAGES` feature lacks `PRODUCT_PAGE_HEADER_ASSET` / `APP_STORE_SEARCH_RESULTS_ASSET`, `creative` entries produce a warning and are skipped.
- PPO guard (below).

**Version states.**

| State of latest version (max numeric `version`, `REPLACED_WITH_NEW_VERSION` ignored) | Meaning for asokit |
|---|---|
| `PREPARE_FOR_SUBMISSION`, `REJECTED` | editable: all writes allowed |
| `READY_FOR_REVIEW` | in an unsubmitted draft submission: writes allowed, `cpp submit` handles it |
| `WAITING_FOR_REVIEW`, `IN_REVIEW` | locked: page skipped with "in review — re-run after review" |
| `ACCEPTED`, `APPROVED` | live |

**Plan for one page (`cpp.plan(file_page, live_snapshot)` → ordered actions).** The live snapshot includes, for the latest version: localizations, promo text, keyword ids per localization, placements per localization (asset `referenceName` hash, group, order) and `deepLink`.

1. **Page missing** → `create_page` (name; inline version with `deepLink`; inline localizations with `promotionalText`; `appStoreVersionTemplate` if `template`). Then re-read the created version and plan steps 3–6 against what actually exists.
2. **Page live** (`ACCEPTED`/`APPROVED`): diff everything.
   - Promo text and keyword differences → **applied in place on the live version** (no new version, no review).
   - Screenshot, creative or deep-link differences → `create_version`, re-read it (it may be pre-populated), then apply steps 3–6 on the new version.
   - No differences → no writes.
3. **Localizations:** create missing; patch `promotionalText`. **Deletion** of localizations not in the file happens only with `--prune`, never under `--locales`, never for the last remaining localization, and every deletion is listed in the dry run.
4. **Keywords:** `POST` additions, `DELETE` removals on `…/relationships/searchKeywords`. Removals are listed explicitly in the dry run.
5. **Screenshots:** `replace_group` per family (`APP_SCREENSHOT`, feature `CUSTOM_PRODUCT_PAGES`).
6. **Creative:** one asset; `replace_group` for `PRODUCT_PAGE_HEADER_ASSET` and for `APP_STORE_SEARCH_RESULTS_ASSET` in every group the catalog maps the spec to.

Pages in the live app but not in the file are never written. `--pages`/`--locales` scope a push.

Idempotence: a second `push` with an unchanged file and unchanged live state writes nothing — every step diffs first, placements compare by asset hash sequence, and a live page only gets a new version when screenshot/creative/deep-link content differs.

**`cpp publish --pages NAME[,…] --apply`.** Sets `visible: true` (or `--hide` sets false). Refuses unless the page's latest version is `APPROVED`/`ACCEPTED`. Dry run prints the keywords this will start routing per locale and warns if the page appears in the last ads export. This is the moment organic routing changes; it is logged in the ledger.

**`cpp submit --pages NAME[,…] --apply`** (`--pages` required):
1. `GET /v1/reviewSubmissions?filter[app]=…&filter[platform]=IOS&filter[state]=READY_FOR_REVIEW,WAITING_FOR_REVIEW,IN_REVIEW,UNRESOLVED_ISSUES`.
2. A submission `WAITING_FOR_REVIEW`/`IN_REVIEW`/`UNRESOLVED_ISSUES` exists → stop ("a submission is in flight").
3. A `READY_FOR_REVIEW` draft exists → read its items; if it holds anything other than the named pages' CPP versions (e.g. the app version), **stop** and tell the user to submit or clear it in App Store Connect. Otherwise reuse it.
4. None → create one.
5. Add one item per named page whose latest version is `PREPARE_FOR_SUBMISSION`/`REJECTED`; refuse if any in-scope placement is `ASSET_PROCESSING`/`FAILED` or any in-scope group is empty while the file declares content.
6. Re-read the submission's items, print them, verify they are exactly the planned CPP versions, then `PATCH submitted: true`.

**Ads export (`--ads-export PATH` on `cpp status` or `cpp push`).** CSV: `page_name, page_id, page_url, visible, latest_state, locale, keywords, deep_link`. Rows for pages not yet created have empty id/url.

### `nominations.py`

`nominations.json`:

```json
{
  "nominations": [
    {
      "name": "MoodSync — new product page & localizations",
      "type": "APP_ENHANCEMENTS",
      "description": "…",
      "publishStartDate": "2026-11-16",
      "deviceFamilies": ["IPHONE", "IPAD"],
      "locales": ["en-US", "de-DE", "fr-FR"],
      "notes": "…",
      "supplementalMaterialsUris": []
    }
  ]
}
```

- `relatedApps` defaults to the config's `appId`; ids are serialised as strings.
- Dates accept `YYYY-MM-DD` and are sent as `YYYY-MM-DDT00:00:00Z`; diffs compare normalised dates.
- `check`: required fields; name ≤ 60; description ≤ 1000; `type` in the enum; **`publishStartDate` ≥ today + 14 days is an error** unless `--force`; warning if the app has no version in `PREPARE_FOR_SUBMISSION` or later that could ship by that date.
- `push --apply`: lists `GET /v1/nominations?filter[state]=DRAFT,SUBMITTED&filter[relatedApps]=<appId>`; matches by `name`. Missing → create with `submitted: false`. `DRAFT` with differences → `PATCH`. `SUBMITTED` → skip with a note.
- `push --apply --submit --name NAME`: sets `submitted: true` on that one nomination only (prints it first).

### `ledger.py`

Every `--apply` write appends one JSON line to `asokit-ledger.jsonl` (next to `asokit.json`): `{ts, command, surface, page_id?, page_name?, version_id?, locale?, action, keywords_added?, keywords_removed?, asset_sha?, placement_type?, group?, submission_id?, nomination_id?}`. `cpp status` prints each page's id, latest state, visibility and the ledger's last publish/submit dates, so App Analytics (Acquisition → product page) can be filtered by go-live date. Commit the ledger to the app repo.

### PPO guard

Before any placement write to the **default** page (`assets push --target default`, `screenshots push --engine library`), read `GET /v1/apps/{id}/appStoreVersionExperimentsV2?filter[state]=READY_FOR_REVIEW,WAITING_FOR_REVIEW,IN_REVIEW,ACCEPTED,APPROVED`; any experiment in `ACCEPTED`/`APPROVED` with a start date ≤ now and no end date, or in review, aborts with its name. (Field report, not Apple documentation: placement fails while a test runs.)

## Commands

App id from `asokit.json` or `--app-id`. Writes are dry runs unless `--apply`.

| Command | Writes (with `--apply`) |
|---|---|
| `assets render [--assets F] [--variant V …] [--locales …] [--out DIR] [--no-lint] [--strict-lint]` | local PNGs |
| `assets status` | — (library, asset states, header/search placements on the editable version and every CPP's latest version) |
| `assets push DIR --target default\|cpp:<name> [--locales …]` | uploads; header + search placements. `cpp:` targets must already have an editable version — asokit never creates CPP versions here ("run `cpp push` first") |
| `assets submit DIR [--locales …]` | standalone review submission of the uploaded creatives (`reviewSubmissionItems.appAssetLibraryImage`), no placements; same submission guards as `cpp submit` |
| `screenshots status [--engine sets\|library]` | — |
| `screenshots push DIR --display T [--locales] [--mirror …] [--mirror-from L] [--engine sets\|library]` | replace screenshot groups per locale |
| `cpp check [--file F] [--offline] [--allow-protected …] [--no-lint]` | — |
| `cpp status [--file F] [--ads-export P]` | CSV only |
| `cpp push [--file F] [--pages …] [--locales …] [--prune] [--allow-protected …] [--creative-root D] [--ads-export P]` | pages, versions, localizations, keywords, placements (pages created hidden) |
| `cpp publish --pages … [--hide]` | page visibility |
| `cpp submit --pages …` | review submission |
| `nominations check [--file F] [--force]` | — |
| `nominations push [--file F] [--submit --name N] [--force]` | create/patch drafts; submit one |

### `screenshots` engines

- `--engine sets` (**default**): today's code path, unchanged, tests unchanged.
- `--engine library`: same flags, plan format, validation and output lines; implemented with `library.replace_group` under feature `APP_STORE_VERSIONS`. Groups are resolved from file dimensions via the catalog (legacy `--display` as tie-breaker). Mirroring re-places the source locale's **asset ids** (no CDN download). Unlike the sets engine it diffs: an unchanged group is not rewritten.
- `screenshots status --engine library` maps groups back to legacy display names through `display_class` and an inverse map that is tested to be one-to-one.
- **Flip criterion:** the default becomes `library` in a later release only after (a) `screenshots status` prints identical output under both engines for MoodSync's editable version, and (b) one full-locale `--engine library` push has been verified in App Store Connect. Until then the sets engine stays the default.

## Data flow (MoodSync)

```
capture_store.sh → screenshots/store/src/<ui>/*.png
  ├─ compose.py → screenshots/store/out/<locale>/NN-*.png ─┬─ screenshots push (default page)
  │                                                         └─ cpp push (CPP iPhone screenshots, re-ordered)
  └─ asokit assets render → assets-out/<variant>/<locale>.png
                              ├─ assets submit (optional pre-approval)
                              ├─ assets push --target default   (rides with next app version)
                              └─ cpp push (creative per page)
asokit cpp check   ← live keyword pools + live pages
asokit cpp push    → hidden pages + asokit-ledger.jsonl + ads-groups.csv
asokit cpp submit  → review;   asokit cpp publish → visible (routing goes live)
asokit nominations push → draft
```

## Errors and safety

- **Validate before writing.** Offline checks, then online checks, then Phase 1 uploads; any problem → "validation failed — nothing sent", exit 1.
- **Routing changes need two explicit steps.** Pages are created hidden; `cpp submit --pages` sends them to review; `cpp publish --pages` makes them visible. No command changes organic routing implicitly.
- **Default page untouched outside a version.** Placements go only to an editable App Store version; asokit never edits the live version's media.
- **Submissions can't sweep in the app version.** See `cpp submit` steps 3 and 6.
- **No asset deletion; no page deletion.** Only placements are removed; localizations only with `--prune`.
- **Uploads before unplacing; place-before-unplace when capacity allows** (`replace_group`).
- **Token:** `asc.Bearer` re-mints automatically, including inside poll loops.
- **Rate limits:** parse `X-Rate-Limit`; below 10 % remaining, sleep until the budget recovers; batch polls.
- **Retry policy unchanged:** 429 any method; 5xx GET only. Re-runs converge.
- **Partial failure:** print completed actions, the exact locale/group state left behind, and that a re-run is safe.
- **ASC write authorization:** these write paths were authorized by the user on 2026-10-11 under dry-run-default + `--apply`, with `--submit`/`publish` as separate explicit steps.

## Testing

`unittest`, stdlib, fake App Store Connect objects with in-memory state installed over `asc.call` (pattern of `tests/test_screenshots.py`).

- `test_library.py`: catalog traversal (spec → groups, dimensions → specs, max count, category acceptance, Watch 410×502 ambiguity resolved by tie-breaker); upload byte slicing per `uploadOperations`; reuse table (each state → reuse / fresh / stop); in-run cache; spec mismatch skip; `replace_group` — unchanged sequence → zero writes, place-first under capacity, unplace-first at capacity, abort between unplace and place reports the gap; order verified; no asset DELETE ever issued; bearer re-minted during a long wait; rate-limit backoff.
- `test_creative.py`: `_`/`.` entries ignored; size check; colour types 0, 2, 3, 3+tRNS, 4, 6 and 16-bit depth; each lint category positive/negative; unlinted-locale warning and `--strict-lint`.
- `test_render.py` (skipped without Pillow; RTL cases skipped without raqm; fonts via `ImageFont.load_default(size)`): 5244×2950 RGB output; every non-background pixel (text, devices, shadows) inside the inset safe box; RTL mirrors; CJK per-character wrap; over-long headline fails the locale; `_slots` name and index; `hero` → `fallbackSlot`; `_`-prefixed keys skipped; one-hop `same`; 3 captures rejected; contact sheet path.
- `test_cpp.py`: validation (name, promo length + lint, ownership error across file pages and live pages, empty sets allowed, protected keyword error and `--allow-protected`, `same` never copies keywords, pool membership by id, editable-pool warning, page cap incl. live); plans for missing page (dry run with `(new)` placeholders), editable version, live page with only promo/keyword change (in place, no new version), live page with screenshot change (new version, re-read), live page unchanged (zero actions), in-review (skip); `--locales` never deletes; `--prune` deletes but never the last localization; ads CSV.
- `test_cpp_apply.py`: create-page body with `${local-id}` placeholders and `included[]`; publish refuses unapproved; submit — in-flight stop, foreign item in draft stop, reuse clean draft, create new, item verification before `submitted: true`.
- `test_nominations.py`: `filter[state]` + `filter[relatedApps]` on list; date normalisation (no PATCH on unchanged); string ids; 14-day error and `--force`; create/patch/skip by state; `--submit` requires `--name` and `--apply`.
- `test_ledger.py`: one line per applied write; nothing on dry run.
- `test_screenshots.py`: existing tests kept for the sets engine; library engine — status parity on a fake holding the same media, group from dimensions, mirror re-places asset ids, unchanged group not rewritten, inverse display map one-to-one.
- `test_cli.py`: wiring, required flags (`--pages` on submit/publish, `--name` with `--submit`), dry-run banners.

## Rollout

Four phases, each with its own live gate. Each phase is shippable alone.

**Phase A — library + creatives.** `library`, `creative`, `render`, `ledger`, `assets *`, `asc.Bearer`/rate-limit.
1. Read-only: `assets status` against MoodSync; dump the catalog and confirm: universal spec dims, header/search groups per feature (incl. `CUSTOM_PRODUCT_PAGES`), limits.
2. Render default + CPP variants; user reviews contact sheets.
3. ASC Preview tool check of one rendered locale (crop/overlay) before rendering all 39.
4. `assets push --target default` dry run; `--apply` only when the next version exists in Prepare for Submission.

**Phase B — CPPs.** `cpp`, `cpp_apply`.
1. Read-only: `cpp status` (confirms `AppKeyword` id format, live pages); `cpp check` online.
2. `cpp push --pages "BPD tracker" --locales en-US --apply` → hidden page. User inspects in App Store Connect; confirm whether `create_page` with template pre-populates media.
3. Remaining en-* locales and pages, hidden.
4. `cpp submit --pages "BPD tracker"`; after approval, `cpp publish --pages "BPD tracker"`. One page per wave; next page after a 14-day read of that page's App Analytics.

**Phase C — screenshots library engine.** Parity check (status under both engines identical), then one full-locale `--engine library` push on the next version. Flip the default in a later release.

**Phase D — nominations.** `nominations check`/`push` (draft). Submit when the target version and date are firm.

## MoodSync content (first consumer)

In the MoodSync repo:

- `assets.json` (repo root): brand `#4338CA`, fonts and per-locale type sizes from `compose.py`.
  - **default** variant: new `"hero"` headline key added to `headlines.json` for all 39 locales — one line distinct from screenshot 1's headline, so the header does not repeat the first screenshot. Claude-drafted; English reviewed by the user; native review owed for the rest (they render with a fallback to slot 0 until a `hero` exists). Captures: log home + stats insights (2 devices).
  - **bpd**, **meds-triggers**, **depression-anxiety**, **report** variants: English headlines (en-US; en-GB/CA/AU `same`). Copy claims only existing features; "BPD" appears in keywords only, never in the creative.
- `cpp.json` — protected keywords (all en locales): `cyclothymia`, `depression`, `hypomania`, `mania`, `episode` (bipolar-core terms; `cyclothymia` ranks #4 organically and is a live Apple Ads exact keyword). Keyword fields read 2026-10-11 from the latest baseline: en-US `mania,depression,hypomania,episode,medication,mental,health,borderline,cyclothymia,bpd,triggers,adhd`; en-GB `symptom,depression,hypomania,diary,medication,mental,health,borderline,cyclothymia,bpd,triggers,adhd`; en-CA/AU as en-GB with `emotion` for `hypomania`. Re-confirmed live by `cpp check`.

| Page | Keywords per en locale (wave 1) | Screenshot lead (iPhone; other families from template) | Creative | Wave |
|---|---|---|---|---|
| BPD tracker | `bpd`, `borderline` | entry details, patterns | `bpd` | 1 |
| Meds & triggers | `medication`, `triggers` | entry details, Health settings | `meds-triggers` | 2 |
| Depression & anxiety | none in wave 1 (`mental`, `health` would capture "mental health tracker"; decide after wave 1 data) — Apple Ads ad group for `depression tracker` / `mental health tracker` | weekly review, patterns | `depression-anxiety` | 2 (ads-only) |
| Therapist report | none — Apple Ads + link only | PDF preview, insights | `report` | 3 (ads-only) |

- `nominations.json`: one `APP_ENHANCEMENTS` draft for the **next** app version (new product page creatives + de/fr after native review). `publishStartDate` set once that version's date is firm; not pushed before then.
- `.gitignore`: `assets-out/`. `asokit-ledger.jsonl` is committed.

Promo text and all headline copy is drafted during implementation and reviewed by the user before any `--apply`.

## Open items (resolved by Phase A/B read-only steps)

1. `AppKeyword` id format (expected: the keyword text) — `cpp status`.
2. Header/search groups and limits under `APP_STORE_VERSIONS` and `CUSTOM_PRODUCT_PAGES`; universal spec id and dimensions — catalog dump.
3. Whether a CPP created with `appStoreVersionTemplate`, or a new version of a live page, is pre-populated — first `cpp push --apply` (the plan re-reads either way).
4. Crop/overlay of the universal asset in header and search — ASC Preview tool.

## Future (not in this spec)

- Standalone-approved creatives placed on the live version, if the API allows it (Help says the UI does).
- Video creatives; iPhone Duo; PPO treatment placements; porting `compose.py` onto `render.py`; Apple Ads ad-variation automation.
