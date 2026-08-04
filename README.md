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
- a word duplicated between name and subtitle
- the same keyword listed twice
- `a, b, c` spacing in the keyword field, which silently costs you characters

This command needs no credentials, so it doubles as clean copy-paste output if
you'd rather paste into the web UI.

### Metadata rules worth knowing

- Limits: **name 30, subtitle 30, keywords 100**, promotional text 170.
- Never repeat a term across those three fields.
- No spaces after commas in the keyword field.
- Use singular forms — Apple handles plurals.
- Apple combines words across fields, so prefer distinct single words in the
  keyword field over repeating a phrase from your title.
- Compound-word languages (German, Dutch, Finnish) can't have compounds
  assembled from parts across fields, so each compound must appear whole.
  Budget for it: `Haushaltsbuch` costs 13 of your 30 subtitle characters.

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
asokit metadata push de.json            # dry run — shows exactly what would change
asokit metadata push de.json --apply    # write it
```

Validation runs before anything is sent, so a bad file fails locally rather
than halfway through a batch. Credentials are read from the environment only;
`.p8` keys are gitignored by default.

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
| `asokit doctor` | check config, Apple connectivity, and credentials |
| `asokit storefronts` | list all 60 storefronts |
| `asokit storefronts --check de` | verify one storefront against the live endpoint |
| `asokit research --market de` | expand and score keywords for one market |
| `asokit research --all` | run every market in your config |
| `asokit metadata check FILE` | validate limits and duplication |
| `asokit metadata status` | show which version and locales are editable |
| `asokit metadata push FILE` | dry-run the sync |
| `asokit metadata push FILE --apply` | write metadata to App Store Connect |

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
all; only App Store Connect sync adds `pyjwt` and `cryptography`.

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
`metadata` (pure validation, no I/O), `asc` (App Store Connect), `report`
(rendering), `suggest` (seed derivation).

Contributions welcome — especially additional storefront verifications,
stopwords for languages not yet covered, and app-name punctuation conventions
from stores you know better than I do.

## License

MIT. See [LICENSE](LICENSE).

Not affiliated with, endorsed by, or connected to Apple Inc. "App Store" and
"App Store Connect" are trademarks of Apple Inc.
