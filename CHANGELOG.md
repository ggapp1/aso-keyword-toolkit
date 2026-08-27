# Changelog

## 0.4.0

Everything here comes from a field report on taking a live app from 9 App
Store locales to 37 in one sitting ([#1]).

- **`asokit metadata suggest`** — the step that was missing between the
  research report and `metadata check`: packing scored candidates into a
  100-character keyword field. Splits phrases into words because Apple
  combines across fields, drops stopwords and terms the name or subtitle
  already cover, and filters competitor brand fragments that `looksLikeAppName`
  cannot catch once phrases are split into words. Tokenizing splits on
  separators rather than matching `\w`, which excludes nonspacing combining
  marks and shreds Thai and Devanagari; scripts written without spaces stay one
  token by design. Live keywords rejoin the pool at the lowest priority so a
  term that is already ranking is not discarded for want of an autocomplete
  suggestion. `--block` is the escape hatch for junk no rule reaches.
- **`asokit metadata pull`** — writes the live listing in the same
  `{locale: {field: value}}` shape `check` and `push` consume, so
  `push baseline.json` is the rollback path. Previously everyone hand-rolled
  this, and without it a bad push has no undo.
- **Stemming is per-language.** `stem()` applied the English suffixes to every
  locale, truncating German `zucker` to `zuck` and `wasser` to `wass` —
  inventing collisions between unrelated words while still missing the real
  German plurals. Suffix rules are now keyed by language subtag, Romance `-es`
  and Portuguese `-ões/-ão` included. Locales with no rules fall back to exact
  matching and `metadata check` names them, rather than presenting an English
  verdict on Greek.
- **`metadata check` catches the error that blocks submission.** A locale
  carrying name/subtitle/keywords with an empty or absent description passed
  validation. App Store Connect does not fall back to the primary locale for
  unfilled fields — it stores them empty, and an empty description makes the
  version unsubmittable. `--allow-partial` skips the rule when you are
  deliberately updating a subset of fields; `--strict` also wants release notes.
- **`metadata push` reports what it actually did.** It reported the
  create-vs-update predicted by a snapshot taken before the run, so a create
  that became an adopt-and-patch mid-run was still reported as created. Each
  locale is now streamed as it lands, flushed so a redirected log is a live
  record, and an abort says which locales were already written instead of
  leaving the account half-updated with no report.
- **`asokit doctor` checks territory availability.** Researching a storefront
  the app is not sold in is pure waste; assuming the opposite drops markets you
  already sell in. Advisory, not a failure.
- `research --all --resume` skips markets that already have scores, so a
  failure at market 30 of 37 no longer loses the loop.
- `research --out` with `--all` is read as the parent of the per-market
  directories instead of being rejected.
- Progress lines flush, so a long run redirected to a log is no longer silent
  until it exits.
- `push` and `status` follow pagination when reading existing localizations.

[#1]: https://github.com/ggapp1/aso-keyword-toolkit/issues/1

## 0.3.0

- `asokit products apply` — declaratively provision subscription groups,
  subscriptions, prices across every territory, and availability from one file.
  Idempotent: a re-run against unchanged state writes nothing. Dry run unless
  `--apply`.
- `products check` now validates the declarative format alongside the existing
  flat localization format.
- `apply` provisions all-territory availability only. `allTerritories: false`
  is rejected: the file cannot express a smaller set, so `false` would still
  put the product on sale everywhere — it only turns off auto-enrolment in
  territories Apple adds later.
- App Store Connect calls follow pagination and retry rate limits.
- Review screenshots and submission remain manual by design.
- **`asokit products`** — validate and sync in-app purchase, subscription, and
  subscription-group localizations (`status` / `check` / `push`, dry run by
  default). File format maps product id → locale → name/description; a
  `group:` prefix addresses a subscription group by reference name. Unchanged
  locales are skipped so re-running an applied file is a no-op — that matters
  because any real write to an approved product sends it back into review.
- `metadata push` survives App Store Connect auto-creating the paired
  appStoreVersionLocalization: on a 409 it adopts the existing resource and
  patches it instead of aborting.
- `metadata check` accepts `supportUrl` and `marketingUrl`.

## 0.2.0

- **Off-category detection.** Terms answered by apps in a different App Store
  category are now separated out of the targetable list. In the US store this
  correctly demotes `moodle` (Education), `tracker detect` (Utilities) and
  `self-help credit union` (Finance) from a mood-tracking app's results —
  keywords that scored well but belong to another audience entirely. Requires
  `app.appId` so the category can be read.
- **Stem-aware metadata validation.** Apple matches on stems, so `Track` in a
  subtitle already covers `Tracker` in the title. `metadata check` now flags
  these collisions, which exact-string comparison silently allowed.
- **`asokit init --add`** adds markets to an existing config instead of
  refusing to run or overwriting curated seeds.
- Report gains an "Off-category" section; run summaries exclude those terms.

## 0.1.0

First release.

- Per-storefront keyword expansion from App Store autocomplete, across 60
  countries.
- Candidate scoring against the top 50 ranked apps: competition tier, exact
  title matches, and your app's current rank.
- Competitor app-name detection, including CJK naming conventions (`・`, `：`),
  so brand queries don't get scored as keyword opportunities.
- `asokit init --app-id` derives starter seeds from your live listing and the
  apps ranking alongside it.
- `asokit doctor` checks config, Apple connectivity, and App Store Connect
  credentials before a long run.
- Metadata validation for the 30/30/100 character limits and cross-field
  repetition, which is the mistake that quietly wastes keyword budget.
- App Store Connect sync covering both `appInfoLocalizations` and
  `appStoreVersionLocalizations`, dry-run by default.
- Ships as a Claude Code plugin with a six-phase ASO playbook skill.
