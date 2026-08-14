# Changelog

## Unreleased

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
