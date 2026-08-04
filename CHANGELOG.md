# Changelog

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
