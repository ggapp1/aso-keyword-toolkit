---
name: aso-localize
description: Data-driven per-market App Store metadata (name/subtitle/keywords) using free Apple endpoints. Use when localizing an App Store listing to a new market, refreshing keywords for an existing one, or researching what people actually search in a given storefront.
---

# ASO localization playbook

Produces a per-locale App Store metadata set grounded in real per-storefront
data, then pushes it to App Store Connect. Six phases; phases 4 and 6 have
human review gates.

Requires `aso-keyword-toolkit` (`pip install aso-keyword-toolkit`) and an
`asokit.json` config in the repo root. If there is no config yet, build one
from the app's live listing rather than inventing seeds:

```bash
asokit init --app-id <id> --markets de,fr
asokit doctor          # config, connectivity, credentials
```

To add a market to a config that already exists, use `--add` — it keeps the
existing markets and their curated seeds:

```bash
asokit init --add --markets it,pl
```

Review the suggested seeds with the user before running research — they are
derived from English-language listings and need native terms added per market.

Make sure `app.appId` is set. Without it there is no rank column, and the
off-category filter below is silently disabled.

**Scope: App Store metadata only.** Not in-app strings, not screenshots.
Before shipping ASO for a market whose app UI isn't localized, weigh that
mismatch — search traffic landing on an app in the wrong language converts
worse. Flag it rather than silently proceeding.

## Phase 1 — Seeds

Seeds live in `asokit.json` per market: native terms in that language, both
the formal and everyday wording for what the app does, plus English terms.
Include English seeds even for non-English markets — in many stores users
search in English, and phase 3 settles the mix empirically rather than by
assumption.

Write seeds with correct diacritics; autocomplete is accent-sensitive. In
the Spanish store `credito` and `crédito` return different suggestion sets.
Check for cross-language collisions too, and check intent before committing a
slot: in the US store `mint` leads with a wireless carrier, not a budget app.

## Phase 2 & 3 — Expand and score

```bash
asokit research --market de
```

Runs each seed through that storefront's autocomplete, then scores every
candidate against the top-50 ranked apps. Writes `report.md`, `scores.json`,
`expansion.json`. Responses cache, so re-runs are free.

Read the report for four things:

1. **Where the app already ranks** (`our rank`). Existing strength is an asset
   to protect, not to overwrite.
2. **Where it's invisible** on terms with low `comp`. That's the opening.
3. **The competitor table.** A rival's title is their keyword bet.
4. **The off-category section.** Terms answered by apps in another App Store
   category are separated out automatically. Do not resurrect them because the
   numbers look good — they belong to a different audience.

Then apply the judgment the scores still can't. Off-category catches a
different *category*; it cannot catch a term that is in our category but
serves a different intent. Check who actually ranks before committing a slot.

## Phase 4 — Compose (review gate)

Write a metadata file keyed by App Store Connect locale. Rules in priority
order:

1. **Never repeat a term across name, subtitle, and keywords.** Apple indexes
   all three as one pool; duplicates waste a 100-character budget.
   This includes **shared stems** — a title saying "Tracker" already covers a
   subtitle saying "Track". `metadata check` flags both cases; run it rather
   than eyeballing.
2. Limits: name 30, subtitle 30, keywords 100, promotional text 170.
3. Keyword field: comma-separated, no spaces after commas, singular forms.
4. Prefer distinct single words in the keyword field over repeating a phrase
   already in the name — Apple combines words across fields.
5. Let the data decide the English-versus-native mix. Don't translate the
   English listing; compose natively from what that storefront shows.
6. Compound-word languages can't assemble compounds from parts across fields,
   so each compound must appear whole. Budget for it.

```bash
asokit metadata check de.json
```

**Gate: a human reviews before anything uploads.** These are proxies, and a
native speaker catches phrasing that reads as keyword stuffing — which the
data cannot.

## Phase 5 — Spot-check (optional)

Validate only the finalists against real Apple Search Ads popularity, if you
have access. Worth it when two candidates are genuinely tied.

## Phase 6 — Ship

```bash
asokit metadata status                  # is a version editable?
asokit metadata push de.json            # dry run
asokit metadata push de.json --apply
```

Dry run is the default. Metadata is only writable while a version is in
Prepare for Submission or a rejected state.

## After shipping

Re-run `asokit research --market de` three to four weeks later and diff the
`our rank` column. That's the measurement, and the cache makes it cheap.
