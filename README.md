# ASO Keyword Toolkit — free App Store keyword research from the command line

[![PyPI](https://img.shields.io/pypi/v/aso-keyword-toolkit.svg)](https://pypi.org/project/aso-keyword-toolkit/)
[![tests](https://github.com/ggapp1/aso-keyword-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/ggapp1/aso-keyword-toolkit/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](pyproject.toml)

**App Store Optimization keyword research, competitor analysis, and App Store
Connect metadata automation — for 60 countries, from your terminal, for free.**

Find the keywords real users type in any App Store storefront. See who ranks for
them and how beatable they are. Discover where your app is already winning and
where it's invisible. Then write, validate, and publish localized metadata
without touching the App Store Connect web UI.

```bash
pip install aso-keyword-toolkit
asokit init --app-id 1234567890 --markets de,fr,jp
asokit research --all
```

That's it. No account, no API key, no subscription, no trial. The research path
uses two public Apple endpoints and has **zero dependencies**.

---

## Why this exists

ASO tools start around $19/month and climb into the hundreds. A large part of
what they sell is packaging of two Apple endpoints that are open to anyone: the
App Store's autocomplete and the iTunes Search API. This gives you direct
access to both, adds the analysis layer on top, and connects the result
straight to the App Store Connect API so the whole loop runs from one command.

It is genuinely useful on its own, and it is also an honest floor: it will
never invent a search-volume number that Apple does not publish. More on that
in [What the numbers mean](#what-the-numbers-mean).

---

## Installation

```bash
pip install aso-keyword-toolkit
```

**pipx or uv** — if you want it as an isolated global tool:

```bash
pipx install aso-keyword-toolkit
uv tool install aso-keyword-toolkit
```

**For development**, or if you want to read the code first:

```bash
git clone https://github.com/ggapp1/aso-keyword-toolkit
cd aso-keyword-toolkit && pip install -e .
```

**App Store Connect sync** needs two extra libraries for JWT signing. Keyword
research does not:

```bash
pip install "aso-keyword-toolkit[connect]"
```

**Rendering App Store creatives** (`asokit assets render`) also needs Pillow:

```bash
pip install "aso-keyword-toolkit[connect,render]"
```

### Claude Code plugin

The repo doubles as a [Claude Code](https://claude.com/claude-code) plugin
marketplace. Installing it gives your agent a six-phase ASO playbook with
review gates, wired to this CLI:

```
/plugin marketplace add ggapp1/aso-keyword-toolkit
/plugin install aso-keyword-toolkit@aso-toolkit
```

The skill calls the `asokit` CLI, so install that too (above). Then ask
Claude to research a market, or invoke the skill directly with
`/aso-keyword-toolkit:aso-localize`. It runs the research, reads the report,
drafts metadata that respects Apple's character and duplication rules, and
stops for your review before anything is published.

---

## Getting started in one command

If your app is already on the App Store, let the toolkit write your config:

```bash
asokit init --app-id 1234567890 --markets de,fr,jp
```

It reads your live listing, looks at the apps ranking alongside you, and
derives starter seed keywords from what those apps actually call themselves:

```
reading your listing in the US store...
  Budget Expense Tracker — Finance
looking at apps that rank alongside it (this takes a moment)...
  read 68 competitor listings

wrote asokit.json with 16 seeds and 3 market(s)

Suggested seeds:
  expense tracker
  budget planner
  money manager
  spending
  receipts
  savings
  ...
```

Your app ID is the number in your App Store URL
(`apps.apple.com/app/id1234567890`). Starting from scratch instead?
`asokit init` writes a template you can fill in by hand.

Check everything is ready before a long run:

```bash
asokit doctor
```

```
config      asokit.json — 3 market(s)
apple api   reachable — 10 suggestions for a test query
connect     not configured (only needed to push metadata)

ready
```

---

## App Store keyword research

```bash
asokit research --market de
```

Every seed goes through the App Store's autocomplete **for that specific
storefront**, harvesting what Apple suggests to users in that country. Every
candidate is then scored against the top 50 ranked apps there.

Real output from the German App Store, tracking a budgeting app:

```
| # | keyword                    | pop | ac-rank | seeds | comp | median top-5 ratings | exact-title | our rank | opp |
|---|----------------------------|-----|---------|-------|------|----------------------|-------------|----------|-----|
| 1 | kostenkontrolle            |  10 |       1 |     1 |    1 |                   23 |           1 |        — |  18 |
| 2 | savings goals              |  10 |       1 |     1 |    2 |                  240 |           1 |        — |  16 |
| 3 | ausgaben tracker           |  11 |       1 |     2 |    3 |                2,697 |           1 |        1 |  15 |
| 4 | geld sparen                |  11 |       1 |     2 |    3 |                1,899 |           1 |       13 |  15 |
| 5 | haushaltsbuch              |   9 |       2 |     1 |    3 |                8,592 |           8 |        1 |  13 |
```

| column | what it tells you |
|--------|-------------------|
| `pop` | autocomplete-derived ranking proxy — higher means Apple surfaces it sooner |
| `ac-rank` | best position across every seed that surfaced it |
| `seeds` | how many different seeds led to it (breadth of relevance) |
| `comp` | competition tier 1–5, from median rating count of the top 5 apps |
| `exact-title` | how many of the top 10 put this exact term in their title |
| `our rank` | where your app currently sits, if it's in the top 50 |
| `opp` | `pop + (5 - comp) * 2` — a sort key, not a verdict |

A term at `comp` 1 whose top-5 apps have two dozen ratings is a real opening. A
term at `comp` 5 belongs to someone with a marketing budget.

Each run also prints the headline takeaways so you don't have to read the whole
table:

```
aso/de/report.md
  least contested:  kostenkontrolle, savings goals
  you already rank: ausgaben tracker (#1), haushaltsbuch kostenlos (#1), budget planner (#2)
  winnable gaps:    kostenkontrolle, savings goals
```

Responses are cached on disk, so re-running the same market weeks later to
measure whether your changes worked costs almost nothing.

### Competitor analysis

Every report ends with the apps that kept appearing across your queries. A
rival's title *is* their keyword strategy, stated publicly:

```
| app                            | ratings | top-5 appearances | best rank |
|--------------------------------|---------|-------------------|-----------|
| Ausgaben Budget Planner Fleur  |   1,899 |                20 |         1 |
| Monefy: Ausgaben manager       |   4,710 |                18 |         2 |
| Haushaltsbuch MoneyStats       |  22,435 |                18 |         2 |
```

Autocomplete mixes competitor **app names** in with genuine queries, which
quietly corrupts keyword research. Those are detected and listed separately
rather than scored as opportunities — including in Japanese and Chinese
listings, which join name and tagline with `・` and `：` instead of `:`.

### Off-category detection

Some terms score beautifully and belong to somebody else entirely. Searching
`moodle` in the US store looks like a strong lead for a mood app; it returns
Education software. `tracker detect` returns AirTag finders. `self-help credit
union` returns a bank.

When your config has an `appId`, the toolkit reads your App Store category and
compares it against the apps actually ranking for each term. Anything answered
by a different category is moved to its own section:

```
| term                   | pop | comp | who actually ranks |
|------------------------|-----|------|--------------------|
| moodle                 |  10 |    1 | Education          |
| self-help credit union |   9 |    5 | Finance            |
```

Real output — both scored well enough to top the list for a health app, and
neither is worth a character.

---

## 60 storefronts, every language

```bash
asokit storefronts              # list all of them
asokit storefronts --check jp   # verify one against the live endpoint
```

```
Japan (jp) header=143462-4,29
  suggestions for '家計簿': 家計簿, 家計簿アプリ, 家計簿 無料 人気, 家計簿 レシート, 家計簿 共有
```

Country selection uses the `X-Apple-Store-Front` header. **The `cc=` query
parameter you'll find in older blog posts does not work** — Apple accepts it
and silently returns US results, which is an excellent way to ship a German
keyword set built entirely from American data. This toolkit gets it right and
gives you `--check` to prove it.

Non-Latin scripts, accents, and compound-word languages are first-class.
Diacritics matter more than people expect: in the Spanish App Store,
`credito` and `crédito` return different suggestion sets.

---

## ASO metadata validation

The most expensive mistake in App Store metadata is repetition. Apple indexes
your **app name, subtitle, and keyword field as a single pool** and combines
words across them. Repeating a term you already used buys nothing and burns
part of a 100-character budget you can't extend.

```bash
asokit metadata check de.json
```

```
--- name (26/30) ---
Budgeteer: Expense Tracker

--- subtitle (24/30) ---
Haushaltsbuch & Finanzen

--- keywords (71/100) ---
budgetplaner,ausgaben,sparen,kostenkontrolle,quittungen,einnahmen,konto

All fields within limits. No repetition across name, subtitle and keywords.
```

It catches what actually goes wrong:

- fields over the 30 / 30 / 100 character limits
- a keyword that already appears in your name or subtitle
- a keyword that *shares a stem* with one — `track` versus `tracker`
- a word duplicated between name and subtitle
- the same keyword listed twice
- `a, b, c` spacing in the keyword field, which silently costs you characters
- **a localization with no description**, which blocks submission outright

That last one is the trap in a research-driven workflow: you localize name,
subtitle and keywords from research data and leave the long-form copy alone.
App Store Connect does *not* fall back to your primary locale for the fields
you skip — it stores them empty, and an empty description means the version
cannot be submitted. Nothing surfaces that until submission fails. Use
`--allow-partial` when you are deliberately updating a subset of fields on a
locale whose description is already live, and `--strict` to also require
release notes.

This command needs no credentials, so it doubles as clean copy-paste output if
you'd rather paste into the web UI.

**Stemming is per-language.** Apple matches on stems, but morphology is not
universal, and English suffix rules applied everywhere are worse than no
stemming at all: they truncate German `Zucker` to `zuck` and `Wasser` to
`wass`, inventing collisions between unrelated words while still missing the
real German plurals, which are formed in `-en` and with umlaut. Rules exist
for English, Spanish, Portuguese, Catalan, Galician, French and Dutch, plus
the languages that mark no plural suffix at all (Japanese, Korean, Chinese,
Thai, Vietnamese, Indonesian, Malay). Every other locale is compared as exact
words, and `metadata check` prints a note naming them rather than letting a
clean run read as a verdict on locales it never really checked.

### Metadata rules worth knowing

- Limits: **name 30, subtitle 30, keywords 100**, promotional text 170.
- Never repeat a term across those three fields.
- **Watch stems, not just words.** Apple matches `Track` and `Tracker` as the
  same term, so a title saying "Tracker" makes a subtitle saying "Track" dead
  weight. `metadata check` catches these; exact-string comparison does not.
- No spaces after commas in the keyword field.
- Use singular forms — Apple handles plurals.
- Apple combines words across fields, so prefer distinct single words in the
  keyword field over repeating a phrase from your title.
- Compound-word languages (German, Dutch, Finnish) can't have compounds
  assembled from parts across fields, so each compound must appear whole.
  Budget for it: `Haushaltsbuch` costs 13 of your 30 subtitle characters.

---

## Drafting the keyword field

Between a research report and a validated metadata file sits the step that is
actually hard: packing terms into 100 characters without wasting budget.

```bash
asokit metadata pull > baseline.json          # capture what is live first
asokit metadata suggest --market de --baseline baseline.json
```

```
de -> de-DE  (38/100 characters)
  blutzucker,wasser,tracker,fodmap,hba1c
  dropped: competitor app-name fragments (balloon, uab, zuckerheld); stopwords (app, der, und)
```

It shows its work rather than presenting a field as magic. What it handles:

- **Phrases become words.** Apple combines words across fields, so listing
  `stool tracker` and `poop tracker` buys `tracker` twice.
- **Stopwords.** `with`, `and`, `free` eat characters and target nothing.
- **Competitor brand fragments.** `looksLikeAppName` filters whole terms, but
  splitting phrases into words leaks `balloon`, `uab` and `inc` out of rival
  app names — which is where trademark trouble starts.
- **Scripts with combining marks.** Tokenizing splits on separators rather
  than matching `\w`, because Python's `\w` excludes nonspacing marks and
  shreds Thai and Devanagari at every tone mark and matra. Scripts written
  without spaces deliberately stay one token; segmenting them properly needs a
  dictionary this tool does not have.
- **Terms you already rank for.** Live keywords from `--baseline` rejoin the
  pool at the lowest priority, so a hand-picked term that is already working
  is not discarded just because autocomplete never proposed it.

`--block word,word` is the escape hatch for junk no rule reaches — a beverage
brand surfacing in health autocomplete is neither off-category by Apple's
genre data nor an app name, but it is still not a keyword you want.

Draft every market at once and validate the result:

```bash
asokit metadata suggest --all --baseline baseline.json --json --out draft.json
asokit metadata check draft.json
asokit metadata push draft.json          # dry run first
```

With `--baseline`, the draft carries the rest of each localization through
unchanged and swaps only the keyword field, so what comes out is a complete,
pushable file rather than a fragment. Without one you get keywords alone, which
`check` will flag as unsubmittable — correctly, since a locale carrying
keywords and no description is exactly the shape that cannot be submitted.

The output is a starting point, not an answer. Read it before you push it.

---

## App Store Connect automation

Localized metadata is split across two different API resources and is only
writable while a version sits in an editable state — the kind of detail that
makes hand-rolling this annoying. The toolkit handles both, creates locales
that don't exist yet, and dry-runs by default.

Create a key at **App Store Connect → Users and Access → Integrations → App
Store Connect API** with the App Manager role:

```bash
export ASC_KEY_ID=XXXXXXXXXX
export ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export ASC_PRIVATE_KEY_PATH=~/.appstoreconnect/AuthKey_XXXXXXXXXX.p8
```

```bash
asokit metadata status                  # is a version editable right now?
asokit metadata pull > baseline.json    # capture the current listing FIRST
asokit metadata push de.json            # dry run — shows exactly what would change
asokit metadata push de.json --apply    # write it
```

**Pull before you push.** `metadata pull` emits the same
`{locale: {field: value}}` shape that `check` and `push` consume, so
`push baseline.json` is your undo. It is the cheapest safety step available
and the only rollback path there is.

Validation runs before anything is sent, so a bad file fails locally rather
than halfway through a batch. Credentials are read from the environment only;
`.p8` keys are gitignored by default.

A multi-locale push is re-runnable. Creating an `appInfoLocalization` makes
App Store Connect auto-create the paired `appStoreVersionLocalization`, so the
follow-up create collides with a resource that now exists; `push` adopts it
and patches instead of aborting, and reports `adopted` rather than claiming it
created something. Each locale is printed as it lands, flushed, so a redirected
log is a live record — and if a run does fail partway, the output tells you
exactly which locales were already written. Re-running converges.

`asokit doctor` also checks that your app is actually on sale in every market
you configured. Researching a storefront nobody can buy in is an hour of
wasted scoring, and assuming the opposite quietly drops markets you already
sell in.

### Subscriptions from one declarative file

Creating a subscription group, its subscriptions and their prices by hand is
the part of setup that does not scale — and pricing is the worst of it. There
is no endpoint that applies one price to every storefront: the documented path
is one `POST` per territory, roughly **175 writes per subscription**. `products
apply` reads a file that describes the finished state and makes App Store
Connect match it.

```json
{
  "groups": [{
    "referenceName": "Pro",
    "localizations": {
      "en-US": {"name": "Pro"},
      "pt-BR": {"name": "Pro"}
    },
    "subscriptions": [{
      "productId": "com.example.pro.annual",
      "name": "Pro Annual",
      "subscriptionPeriod": "ONE_YEAR",
      "groupLevel": 1,
      "familySharable": false,
      "reviewNote": "Pro unlocks unlimited logging…",
      "availability": {"allTerritories": true},
      "price": {"baseTerritory": "USA", "customerPrice": "24.99"},
      "localizations": {
        "en-US": {
          "name": "Pro Annual",
          "description": "Unlimited logging, all year."
        }
      }
    }]
  }]
}
```

```bash
asokit products status                  # what exists in App Store Connect now
asokit products check products.json     # limits and structure, offline
asokit products apply products.json     # dry run — every action it would take
asokit products apply products.json --apply
```

**It is a diff, not a script.** Each run reads live state first and writes only
what differs, so a second run against an unchanged file writes nothing —
including the 175 price rows. That is the property that makes it safe to re-run
after a partial failure.

Three things it will not do, each on purpose:

- **Change what cannot be changed.** `productId` and `subscriptionPeriod` are
  fixed at creation. If the file disagrees with a live product, the run stops
  and tells you, before anything is sent.
- **Narrow where you sell.** `availability` is required on every subscription,
  and must be `{"allTerritories": true}`. `false` is rejected rather than
  obeyed, because the file cannot express a smaller set — restrict territories
  by hand in App Store Connect instead. It is required rather than optional
  because a subscription provisioned without it comes out priced in every
  territory and on sale in none, and no later run repairs that.
- **Finish the submission.** Every new subscription lands in
  `MISSING_METADATA` until it has a review screenshot. Add those in App Store
  Connect, then submit the subscriptions alongside your next app version.

Text-only changes to products that already exist stay with `products push`,
which keeps taking the flat `{productId: {locale: {field: value}}}` format.

---

## App Store creatives, custom product pages and nominations

Everything below goes through Apple's App Store Asset Library: images are
uploaded once to the app's library, then *placed* on a surface — the default
product page's editable version, or a custom product page. Rendering creatives
needs Pillow; everything that talks to App Store Connect needs the `connect`
extra:

```bash
pip install 'aso-keyword-toolkit[connect,render]'
```

Every write command follows the same shape as `metadata push`: a dry run
unless `--apply`, validation before anything is sent, and uploads finished
before any surface is touched. Concretely:

- **Uploads first, writes second.** Every file in scope is uploaded (or
  reused) and processed before the first placement changes. A failure there
  leaves every live surface as it was.
- **Identical bytes upload once.** Files are matched by content hash. A copy
  App Review **rejected** blocks reuse of those exact bytes — change the
  image — unless an accepted or approved twin of the same bytes exists.
  `FAILED` placements are replaced, not kept.
- **Group limits are checked before writing**, so a run never stops halfway
  through a group because it ran out of slots.
- **Nothing is ever deleted from the library, and no page is ever deleted.**
  Only placements are removed, and page localizations only with `--prune`.

### Rendering creatives from `assets.json`

The header and search-results asset is one universal image, exactly
**5244 × 2950**, cropped by Apple to 21:9 for the product-page header and to
3:2 for search results. `assets render` draws a headline and one or two device
captures inside the intersection of both crops, so nothing important is ever
cut off. `assets.json` lives next to `asokit.json` by default:

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
  "type": {"verb": {"size": 360, "min": 220, "step": 10, "lines": 2, "leading": 1.02},
           "descriptor": {"size": 220, "min": 150, "step": 6, "lines": 2, "leading": 1.12},
           "tight": {"verb": 260, "descriptor": 170}},
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

`type` is optional; the values shown are the defaults. Overrides merge per
key, so `{"verb": {"size": 400}}` changes the size and keeps the rest. Fonts are keyed by locale with `default` covering the rest.

Headlines come either inline (`[verb, descriptor]` or `{"same": locale}`) or
from a headlines file via `from`, where `slot` is an index or a named slot and
`fallbackSlot` covers locales that lack it. A slot name the file doesn't
define is an error, not a silent fallback.

```bash
asokit assets render                          # every variant, every locale it can resolve
asokit assets render --variant bpd --locales en-US,en-GB
```

Output goes to `assets-out/<variant>/<locale>.png` (change it with `--out`),
plus a contact sheet per variant at `assets-out/_contact/<variant>.png` —
review that before uploading anything. The report flags `TIGHT` locales whose
type had to shrink below the tight thresholds and locales that used the
fallback headline.

**A locale that can't be rendered properly fails on its own.** If its text
won't fit the safe box at the minimum size and line count, or its headline
fails the lint, that locale is reported, its old output file is deleted (so a
stale image can't be uploaded by mistake), and the other locales still render.
The lint catches what App Review rejects on creatives: prices and offers,
URLs, rank and award claims, other platforms, medical claims. Languages
without a word list get a warning, which `--strict-lint` turns into an error;
`--no-lint` skips it. Right-to-left locales need Pillow built with libraqm.

The files must be **8-bit RGB PNGs** (colour type 2) with no alpha channel and
no `tRNS` chunk, at exactly 5244 × 2950. Rendered output already is; files you
export from a design tool are checked the same way before upload.

### Placing creatives

```bash
asokit assets status                          # library, asset states, header/search placements
asokit assets status --catalog                # Apple's placement and spec catalog
asokit assets push assets-out/default --target default           # dry run
asokit assets push assets-out/default --target default --apply   # header + search asset
asokit assets push assets-out/bpd --target "cpp:BPD tracker" --apply
asokit assets submit assets-out/default --apply                  # review them on their own
```

`push` reads `DIR/<locale>.png` and places each file as both the product-page
header asset and the search-results asset for that locale. `--target default`
writes to the editable App Store version — the asset ships with your next
release; `--target cpp:<name>` writes to a custom product page that already
has an editable version (run `cpp push` first — `assets push` never creates
page versions). Pushes to the default page refuse while a product page
optimization test is running.

`assets submit` sends the uploaded creatives to App Review by themselves,
placing nothing, so they can be approved ahead of the version they will ride
with. It runs a read-only preflight before uploading anything and skips assets
already in or past review.

### Custom product pages from `cpp.json`

Custom product pages can now be assigned keywords, which makes them show up in
organic search as well as in Apple Ads. `cpp.json` describes the pages you
want; `cpp push` makes App Store Connect match it.

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

- `name` is the join key with live pages: unique and at most 30 characters.
- `template: "appStoreVersion"` starts the page from your current version, so
  every device family inherits the default screenshots and `screenshots` only
  replaces the families it lists. Without a template, every family the live
  version has must be listed.
- `screenshots[].order` picks and orders files by name prefix; `creative`
  names a rendered variant, read from `<creative-root>/<variant>/<locale>.png`
  (`--creative-root`, default `assets-out`).
- `same` copies `promotionalText`, `screenshots`, `creative` and the deep
  link — **never keywords**. Keyword pools differ by locale, so keywords are
  always explicit.
- There is no `visible` field on purpose. Visibility changes only through
  `cpp publish`.

**Keyword rules.** `cpp check` enforces two rules that are stricter than
Apple's:

- **Ownership:** within a locale, a keyword belongs to at most one page —
  counting live pages that aren't in your file. Pages with no keywords are
  fine. Every keyword must also be in that locale's keyword field on the
  latest approved version; one missing from the *editable* version is a
  warning, because the page stops ranking for it when that version ships.
- **Protected keywords:** anything in `protectedKeywords["*"]` or
  `protectedKeywords["<locale>"]` is an error unless named with
  `--allow-protected kw1,kw2`. Use it for the terms your default page has to
  keep winning.

**The lifecycle is four explicit steps**, and organic routing changes only at
the last one:

```bash
asokit cpp check                                   # offline + online validation
asokit cpp push --apply                            # pages created HIDDEN
asokit cpp submit --pages "BPD tracker" --apply    # send to App Review
asokit cpp publish --pages "BPD tracker" --apply   # after approval: visible, routing goes live
asokit cpp publish --pages "BPD tracker" --hide --apply
```

What `cpp push` does to a page depends on its state:

- **Missing** — created hidden, with its localizations, keywords, screenshots
  and creative.
- **Live** — promotional text and keyword changes are edited in place on the
  live version, with no new version and no review. Screenshot, creative or
  deep-link changes open a new version for review.
- **In review** — skipped until review finishes.
- **Unchanged** — nothing is written; a second push is a no-op.

Across all pages in a run, keyword removals happen before additions, so moving
a keyword from one page to another never trips ownership. `--pages` and
`--locales` scope a push; `--locales` never deletes anything. `--prune`
deletes page localizations missing from the file, but never a page's last
localization.

`cpp submit` and `cpp publish` require `--pages` and validate every named
page before doing anything. `submit` refuses if a locale or device family
declared in the file isn't actually placed on the page, and won't add pages to
a draft submission that already holds something else, such as your app
version. `publish` refuses pages that aren't approved.

`--ads-export ads-groups.csv` on `cpp status` or `cpp push` writes one row per
page and locale — page id, URL, visibility, state, keywords, deep link — for
building matching Apple Ads ad groups. After `--apply` it re-reads the live
pages, so the CSV has the ids of pages the run just created.

### Featuring nominations from `nominations.json`

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

```bash
asokit nominations check                              # offline validation
asokit nominations push --apply                       # create or update DRAFTS
asokit nominations push --submit --name "MoodSync — new product page & localizations" --apply
```

`type` is `APP_LAUNCH`, `APP_ENHANCEMENTS` or `NEW_CONTENT`. Dates are
`YYYY-MM-DD` and must be at least 14 days out — Apple's recommended notice —
unless `--force`. `relatedApps` defaults to the app in `asokit.json`; if you
set it, it must include that app.

`push` matches nominations by name: missing ones are created as drafts,
drafts that differ are updated, submitted ones are left alone. If two
nominations in App Store Connect already share a name, `push` refuses rather
than guess which one you meant. `--submit --name N` submits exactly that one,
after every draft in the file has been written.

### Screenshots through the Asset Library

`screenshots push` keeps using the older screenshot-set API by default. The
Asset Library engine is opt-in:

```bash
asokit screenshots status --engine library
asokit screenshots push out/ --engine library                      # dry run
asokit screenshots push out/ --engine library --mirror APP_IPAD_PRO_3GEN_129 --mirror-from en-US --apply
```

Same flags and the same validation, with two differences: it diffs, so an
unchanged group isn't rewritten, and `--mirror` re-places the source locale's
assets by id instead of downloading and re-uploading them. A mirrored display
wins over local files for the same display.

The default switches to `library` in a later release, once two things hold:
`screenshots status` prints identical output under both engines, and one
full-locale `--engine library` push has been verified in App Store Connect.

### The ledger

Every applied write appends one JSON line to `asokit-ledger.jsonl`, next to
`asokit.json` — creates, placements, keyword changes, submissions, publishes,
nominations. Dry runs write nothing.

```json
{"action": "publish", "command": "cpp publish", "page_id": "…", "page_name": "BPD tracker", "ts": "2026-11-02T09:14:00Z", …}
```

Commit it with your app. App Analytics reports each custom product page
separately (Acquisition, by product page), but it doesn't tell you when a page
went live or when its keywords changed. The ledger does: filter Analytics from
the `publish` timestamp for a page, and compare before and after an
`add_keywords` or `place` line for that page or locale. `cpp status` prints
each page's last publish date from the ledger alongside its live state.

---

## A worked example: budgeting apps in the German App Store

A real run — 16 seeds, 40 candidates scored — tracking one of the established
German budgeting apps. Every number below came out of the tool.

**It already owns the German expense vocabulary.** Rank **#1** for
`haushaltsbuch`, `ausgaben tracker`, `ausgaben tracker kostenlos`, and
`haushaltsbuch kostenlos`; **#2** for `expense tracker`, `budget planner`, and
`budgetplaner`. That's a defended position, and the first job of any metadata
change is not to break it.

**But it's invisible where the competition is weakest.** `kostenkontrolle`
scored competition tier 1 — the median top-5 app there has **23 ratings** — and
this app doesn't rank for it at all. Compare `haushaltsbuch`, where the median
top-5 app has **8,592 ratings** and eight of the top ten put the word directly
in their title. Same category, wildly different economics.

The read: the contested compound is already won and should be protected. The
cheap opening is the term nobody is fighting for.

**The competitor table shows the strategy behind the rankings:**

```
| Ausgaben Budget Planner Fleur  |   1,899 |                20 |         1 |
| Monefy: Ausgaben manager       |   4,710 |                18 |         2 |
| Haushaltsbuch MoneyStats       |  22,435 |                18 |         2 |
```

Three of the strongest apps put `Ausgaben` in their title. That isn't something
you have to guess at — it's their keyword bet, published.

**One thing the numbers alone would get wrong.** In the US store, `mint` looks
like an obvious budgeting keyword. The top result is **Mint Mobile, a wireless
carrier**. Ranking there buys traffic from people shopping for a phone plan.
**A popularity score rates the query, not who answers it** — which is exactly
why every report shows you who currently ranks.

---

## What the numbers mean

`pop` is a **ranking proxy derived from Apple's own autocomplete ordering**,
not a search-volume estimate. Apple does not publish search volume through any
free endpoint. Tools that show you "volume: 4,400/mo" from these sources are
modelling, not measuring.

This matters practically. Autocomplete ordering is real signal — it is Apple
telling you what people in that country type — and it is excellent for *ranking
candidates against each other*. It cannot tell you a term's absolute traffic.
Use it to narrow hundreds of candidates down to a handful, then validate those
few against Apple Search Ads if you need absolute numbers.

Relevance stays a human judgment. The toolkit filters competitor app names out
of your results, but no heuristic can tell you that a term in your category
serves a different audience. That's what the competitor table is for — read it.

---

## Command reference

| command | what it does |
|---------|--------------|
| `asokit init --app-id ID` | write a config with seeds derived from your live listing |
| `asokit init --add --markets fr` | add markets to an existing config, keeping your seeds |
| `asokit doctor` | check config, Apple connectivity, and credentials |
| `asokit storefronts` | list all 60 storefronts |
| `asokit storefronts --check de` | verify one storefront against the live endpoint |
| `asokit research --market de` | expand and score keywords for one market |
| `asokit research --all` | run every market in your config |
| `asokit research --all --resume` | continue an interrupted run, skipping scored markets |
| `asokit metadata suggest --market de` | pack researched candidates into a keyword field |
| `asokit metadata suggest --all --json` | draft every market's keyword field at once |
| `asokit metadata pull` | write the live listing to JSON — your rollback baseline |
| `asokit metadata check FILE` | validate limits, duplication and submission-readiness |
| `asokit metadata status` | show which version and locales are editable |
| `asokit metadata push FILE` | dry-run the sync |
| `asokit metadata push FILE --apply` | write metadata to App Store Connect |
| `asokit products status` | list subscriptions, IAPs and their localizations |
| `asokit products check FILE` | validate product text and structure, offline |
| `asokit products push FILE` | dry-run a product text sync |
| `asokit products apply FILE` | dry-run the full provisioning diff |
| `asokit products apply FILE --apply` | provision groups, subscriptions, prices, availability |
| `asokit screenshots status` | screenshot sets per locale on the editable version |
| `asokit screenshots push DIR --engine library` | dry-run a screenshot replace through the Asset Library |
| `asokit assets render` | render header/search creatives from `assets.json` |
| `asokit assets status` | library, asset states, header and search placements |
| `asokit assets push DIR --target default\|cpp:NAME` | dry-run placing creatives (`--apply` to write) |
| `asokit assets submit DIR --apply` | send creatives to App Review on their own |
| `asokit cpp check` | validate `cpp.json`, keyword ownership and pools |
| `asokit cpp status` | live pages, versions, visibility, keywords |
| `asokit cpp push --apply` | converge custom product pages to `cpp.json` (new pages hidden) |
| `asokit cpp submit --pages NAME --apply` | send page versions to App Review |
| `asokit cpp publish --pages NAME --apply` | make approved pages visible |
| `asokit nominations check` | validate `nominations.json` |
| `asokit nominations push --apply` | create or update nomination drafts |
| `asokit nominations push --submit --name N --apply` | submit one nomination |

Each research run writes `report.md` plus the raw `scores.json` and
`expansion.json`, so you can build your own analysis on the data.

---

## FAQ

**Is this really free?**
Yes. Keyword research uses public Apple endpoints that need no account.
Publishing metadata uses your own App Store Connect API key, which Apple issues
free to developers. There is no hosted service and nothing to sign up for.

**Do I need an Apple Search Ads account?**
No. Apple Search Ads is one way to get official popularity scores, but this
toolkit doesn't require it and doesn't use it.

**How is this different from paid ASO tools?**
Paid tools add Apple Search Ads popularity scores, historical rank tracking,
and dashboards. This gives you the per-storefront keyword discovery, competitor
analysis, and metadata publishing that most of the workflow actually consists
of — scriptable, inspectable, and free. Many people need the second thing far
more often than the first.

**Does it work for Google Play?**
Not currently. Everything here is App Store specific: Apple's endpoints, the
30/30/100 character model, and the App Store Connect API.

**Will Apple block this?**
These endpoints are public and used by the App Store itself. The toolkit sets a
descriptive user agent, spaces requests to respect the iTunes Search API's
roughly 20-requests-per-minute limit, and caches everything so repeat runs make
almost no requests. Be reasonable and you'll be fine.

**Can I use it in CI?**
Yes. Everything is non-interactive with meaningful exit codes —
`asokit metadata check` fails the build on a validation error, which makes a
good pre-submission gate.

**What Python version do I need?**
3.9 or newer, tested on 3.9, 3.11 and 3.13. Research has no dependencies at
all; only App Store Connect sync adds `pyjwt` and `cryptography`, and
rendering creatives adds Pillow.

---

## How it works

| source | what it provides | cost |
|--------|------------------|------|
| App Store autocomplete (`MZSearchHints`) | Apple's per-storefront suggestion ranking | free, no auth |
| iTunes Search API | ranked apps per query per country, with rating counts | free, official |
| App Store Connect API | reading and writing localized metadata | free, your own key |

Nothing is proxied through a third party. Every request goes from your machine
to Apple.

---

## Development

```bash
git clone https://github.com/ggapp1/aso-keyword-toolkit
cd aso-keyword-toolkit
pip install -e .
python3 -m unittest discover -s tests -t .
```

The codebase is small and deliberately boring: `storefronts` (the country
table), `sources` (HTTP and caching), `research` (expansion and scoring),
`metadata` (pure validation, no I/O), `packing` (keyword-field selection, also
pure), `asc` (App Store Connect), `report` (rendering), `suggest` (seed
derivation). The App Store Connect write paths follow the same split — pure
modules plan, executors write: `library` (Asset Library uploads and
placements), `creative` (creative file checks and lint, pure), `render`
(creative rendering, optional Pillow), `cpp` (custom product page validation
and planning, pure), `cpp_apply` (custom product page executor), `review`
(review submissions), `nominations` (featuring nominations), `ledger` (the
append-only write log).

Contributions welcome, and two tables in particular are built to be extended
by people who know a language better than I do:

- **`metadata._RULES`** — stemming suffixes per language. Locales absent from
  it are compared as exact words, which under-reports repetition but never
  invents it. Adding a language is a few `(suffix, replacement)` pairs; the
  bar is that the rule must not truncate ordinary stems, which is what the
  old English-everywhere behaviour did to German.
- **`packing._LANGUAGE_FILLER`** — stopwords per language, applied only to
  Latin-script words. Under-filtering wastes a few characters; over-filtering
  deletes the keyword you were trying to rank for, so err toward leaving words
  in.

Storefront verifications and app-name punctuation conventions from stores you
know better than I do are just as welcome.

## License

MIT. See [LICENSE](LICENSE).

Not affiliated with, endorsed by, or connected to Apple Inc. "App Store" and
"App Store Connect" are trademarks of Apple Inc.
