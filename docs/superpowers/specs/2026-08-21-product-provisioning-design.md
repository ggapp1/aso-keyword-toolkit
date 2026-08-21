# Declarative in-app purchase provisioning

**Date:** 2026-08-21
**Status:** Approved, not yet implemented
**Driving app:** Poty (`com.potylabs.poty`, ASC app id `6761436106`)

## Problem

asokit automates *half* of product setup. `products status` reads the
inventory, `products check` validates text against Apple's limits, and
`products push` writes localizations. All three assume the products already
exist — `push_products` raises on any product id it cannot resolve.

So the current workflow is: create the subscription group, the subscriptions,
and every territory's price by hand in the web UI, then let asokit handle the
text. The hand-work is the part that does not scale across a portfolio of apps,
and it is the part with no review trail.

The pricing work in particular is worse than it looks. There is no App Store
Connect endpoint that applies one price to every territory. The documented
path is: fetch the base-territory price point, fetch its `equalizations`, then
issue one `POST /v1/subscriptionPrices` per territory. For two subscriptions
across roughly 175 territories that is about **350 write calls** — not
something to do by hand, and not something to redo by accident.

## Goals

- Describe a subscription group, its subscriptions, prices, availability and
  localizations in one declarative file.
- `apply` that file idempotently: a second run against an unchanged file writes
  nothing.
- Dry-run by default, matching the existing `push` idiom.
- Keep the existing flat localization file format working.

## Non-goals

Deliberately excluded, each for a reason:

- **Review screenshots.** One-time visual asset per product; the three-step
  reserve/upload/commit asset flow is the most brittle corner of the API for
  the least payoff.
- **Submission.** Subscriptions ride along with the app version submission.
- **Non-subscription IAPs (consumables, non-consumables).** Different resource
  family (`inAppPurchasesV2`, addressed under `/v2`). The file format leaves
  room; this spec does not implement it.
- **Introductory offers and promotional offers.** Poty ships without a trial.
  Revisit when an offer is actually being tested.
- **Price changes to already-live products.** Different semantics —
  `preserveCurrentPrice` decides whether existing subscribers are grandfathered.
  That deserves its own design rather than being smuggled into `apply`.

## Poty product configuration

The concrete instance this is built to provision.

**Group:** `referenceName: "Poty Pro"`, display name "Poty Pro" in all locales.

| productId | `name` (internal) | period | groupLevel | familySharable |
|---|---|---|---|---|
| `com.potylabs.poty.monthly` | Poty Pro Monthly | `ONE_MONTH` | 2 | false |
| `com.potylabs.poty.annual` | Poty Pro Annual | `ONE_YEAR` | 1 | false |

**Prices:** USA base $4.99 / $24.99, equalized to all territories.
**Availability:** all territories.
**Trial:** none at launch.

Two configuration choices carry reasoning that must not be lost:

**`groupLevel` 1 (annual) above 2 (monthly), not both at 1.** Level ranking
decides whether a plan switch is an upgrade, a downgrade, or a crossgrade. At
equal levels, monthly→annual is a crossgrade and only takes effect at the next
renewal, deferring the annual revenue by up to a month. Ranking annual higher
makes that switch an immediate prorated upgrade, while annual→monthly correctly
defers. The two plans have identical features, so the ranking costs the user
nothing.

**`familySharable: false` is required by Poty's entitlement architecture, not a
preference.** `supabase/functions/_shared/appstore.ts` grants Pro only when the
verified transaction's `appAccountToken` equals the authenticated caller's
Supabase user id, and `SubscriptionService` stamps that token at purchase time.
A family member's transaction carries the *purchaser's* `appAccountToken`, so
the server would refuse them Pro. Enabling Family Sharing would advertise a
benefit the backend is guaranteed to deny. Family Sharing also cannot be
disabled once enabled.

**Locales:** `en-US`, `pt-BR`, `pt-PT`, `es-ES`, `es-MX`. The app ships four
locales, but ASC splits Spanish and `es-MX` is what LatAm storefronts display.
Five locales across three resources (group + two subscriptions) = 15
localizations. Limits: `name` 30 chars, `description` 45 chars.

| locale | monthly | annual |
|---|---|---|
| en-US | Poty Pro Monthly / Unlimited AI food logging, every month. | Poty Pro Annual / Unlimited AI food logging, all year. |
| pt-BR | Poty Pro Mensal / Registros ilimitados com IA, todo mês. | Poty Pro Anual / Registros ilimitados com IA, o ano todo. |
| pt-PT | Poty Pro Mensal / Registos ilimitados com IA, todos os meses. | Poty Pro Anual / Registos ilimitados com IA, todo o ano. |
| es-ES, es-MX | Poty Pro Mensual / Registros ilimitados con IA, cada mes. | Poty Pro Anual / Registros ilimitados con IA, todo el año. |

`products check` enforces the character limits before anything uploads. All
sixteen strings verified against the limits: longest name is 16/30, longest
description is the pt-PT monthly at 43/45.

**Review note** (both subscriptions, `reviewNote` attribute):

> Poty Pro unlocks unlimited AI-powered food logging by photo, voice and text.
> The free tier includes 30 AI logs per month plus unlimited manual entry and
> food-database search, so no test account is required. The paywall appears at
> the end of onboarding and in Settings.

## File format

```json
{
  "groups": [{
    "referenceName": "Poty Pro",
    "localizations": {
      "en-US": {"name": "Poty Pro"},
      "pt-BR": {"name": "Poty Pro"}
    },
    "subscriptions": [{
      "productId": "com.potylabs.poty.annual",
      "name": "Poty Pro Annual",
      "subscriptionPeriod": "ONE_YEAR",
      "groupLevel": 1,
      "familySharable": false,
      "reviewNote": "Poty Pro unlocks unlimited AI food logging…",
      "availability": {"allTerritories": true},
      "price": {"baseTerritory": "USA", "customerPrice": "24.99"},
      "localizations": {
        "en-US": {
          "name": "Poty Pro Annual",
          "description": "Unlimited AI food logging, all year."
        }
      }
    }]
  }]
}
```

The existing flat `{productId: {locale: {field: value}}}` format stays valid
for `check` and `push`. asokit is published on PyPI (0.2.0); breaking that
format would break users. `check` dispatches on the presence of a top-level
`groups` key.

## Module design

asokit's existing split is load-bearing and this follows it: pure modules are
unit-tested (`products.py`, `metadata.py`), the network module is not
(`asc.py`, which has no test file by design).

`push_products` currently computes its diff *inside* the network function —
the skip-if-unchanged comparison sits interleaved with the POSTs. That is
acceptable for twelve localizations. It is not acceptable for 350 price writes,
where "has this already run?" is the entire correctness question and a wrong
answer means 350 duplicate price changes against live products.

**Therefore: extract the diff into a pure function.**

```
products.plan(desired, inventory) -> [action]     # pure, unit-tested
products.price_diff(current, desired) -> [territory]  # pure, unit-tested
asc.apply_products(app_id, desired, bearer, apply=False)
    # fetch inventory -> products.plan(...) -> execute actions
```

Two pure functions rather than one, because the territory-level price diff
cannot be computed from the inventory alone — the desired
`{territory: pricePoint}` map comes from Apple's `equalizations` response, which
is network. So `plan()` emits a `setPrices` *intent*, and the executor fetches
both maps and calls `price_diff(current, desired)` to decide which territories
to write. `price_diff` is where the "350 writes, then zero" claim actually
lives, and it takes two plain dicts — trivially testable, no fixtures needed.

`plan()` takes the desired state and an inventory dict shaped exactly like
`asc.products_status()` output, and returns an ordered action list. It performs
no I/O. This makes the idempotence logic testable with fixture dicts, which is
the only basis on which this should be pointed at a real account.

`products.check()` gains validation for the new shape: `subscriptionPeriod`
against the enum, `groupLevel` as a positive integer, `productId` non-empty,
`customerPrice` a decimal string, locale codes well-formed — alongside the
existing character limits.

## Diff rules

Every rule is a no-op when the desired state already holds.

| Resource | Matched by | Action |
|---|---|---|
| Subscription group | `referenceName` | create if absent |
| Subscription | `productId` | create if absent; PATCH mutable attribute drift; **error** on immutable drift |
| Localizations | `(parent, locale)` | existing `push_products` logic — already skips unchanged |
| Prices | `territory` | read current prices, POST only territories whose price point differs |
| Availability | present / absent | create if absent |

Ordering matters: group before subscriptions, subscriptions before their
prices, availability and localizations. `plan()` returns actions already
ordered so the executor stays trivial.

**Mutable vs immutable subscription attributes.** `productId` and
`subscriptionPeriod` are fixed at creation — App Store Connect will not change
either afterwards. `name`, `reviewNote`, `groupLevel` and `familySharable` are
patchable (`familySharable` only false→true, never back). So drift handling
splits: a mutable difference emits a PATCH, while a file whose
`subscriptionPeriod` disagrees with the live product is a **planning error**
that aborts before any write, naming the conflict. Silently ignoring it would
leave the file lying about production; silently recreating would orphan a live
product. `plan()` raises; nothing is sent.

The price rule is the one that earns the pure-function treatment. Current
prices come from `GET /v1/subscriptions/{id}/prices?include=territory,subscriptionPricePoint`,
which yields a `{territory: pricePointId}` map. The desired map comes from the
base price point's `equalizations`. Only the symmetric difference is written.

**Price points must be asserted, not assumed.** `pricePoints` is nested under a
subscription — there is no global list — so the exact tier for $4.99 / $24.99
cannot be verified until the subscription exists. The plan step must look up
the base territory's price points, select by exact `customerPrice` match, and
fail loudly if no exact match exists rather than silently taking the nearest
tier.

## Plumbing additions

**Pagination.** `asc.call()` returns a single page and ignores `links.next`.
Price points for a subscription filtered to one territory run to thousands of
rows, so a naive lookup reads the first 200 and may select the wrong base
price — a silent, expensive wrong answer. Add `call_all()` that follows
`links.next` and concatenates `data`. Useful well beyond this feature.

**429 backoff.** ASC allows roughly 3600 requests/hour; 350 POSTs sits well
under, but a single retry-with-backoff on 429 converts a partial failure into a
resumable one. The diff model already makes resume safe — re-running skips
whatever landed.

## CLI surface

```
asokit products apply <file>            # dry run: prints the plan, writes nothing
asokit products apply <file> --apply    # executes
asokit products apply <file> --verbose  # full per-territory price listing
```

Plan output is summarized by default. 350 price lines would bury the three
lines that matter, so prices collapse to one row per subscription
(`prices: 175 territories to set (USA $24.99 → equalized)`) unless `--verbose`.

**Closing message.** After a successful `--apply`, both subscriptions will sit
in `MISSING_METADATA`, not `READY_TO_SUBMIT`, because the review screenshot is
still missing. The CLI must say so explicitly instead of printing "done".
Discovering it at submission time is the failure this line prevents.

## Testing

New tests live in `tests/test_products.py` against `plan()`, using fixture
inventory dicts. The cases that matter:

- empty inventory → creates group, both subscriptions, all localizations, both price sets
- fully-provisioned inventory matching the file → **zero actions** (the core idempotence claim)
- group exists, subscriptions absent → creates only subscriptions
- subscription exists with drifted `groupLevel` → emits a PATCH
- prices set for some territories only → writes only the missing ones
- localization text changed in the file → update, not create
- action ordering: group precedes subscriptions precedes prices
- `check()` rejects a bad `subscriptionPeriod`, an over-limit description, a non-integer `groupLevel`
- flat legacy format still validates

`asc.py` stays untested, consistent with the existing repo convention.

## Verified API reference

Confirmed against Apple's documentation on 2026-08-21, not from memory:

**`POST /v1/subscriptionGroups`** — attributes: `referenceName` (required).
Relationship: `app` (required).

**`POST /v1/subscriptions`** — attributes: `name` (required), `productId`
(required), `subscriptionPeriod` (optional; `ONE_WEEK` | `ONE_MONTH` |
`TWO_MONTHS` | `THREE_MONTHS` | `SIX_MONTHS` | `ONE_YEAR`), `familySharable`
(optional), `groupLevel` (optional integer), `reviewNote` (optional).
Relationship: `group` (required, and the only one).

**Pricing** — `GET /v1/subscriptions/{id}/pricePoints?filter[territory]=USA`,
then `GET /v1/subscriptionPricePoints/{id}/equalizations?include=territory` for
the equivalent point in every other territory, then one
`POST /v1/subscriptionPrices` per territory. There is no bulk endpoint.

`include=territory` is load-bearing, not decorative. Without it App Store
Connect returns the equalized rows but omits `relationships.territory.data`, so
every row is unattributable and only the base territory resolves — pricing the
product in one storefront and silently leaving the other ~174 unset. This was
found against the live API on 2026-08-21, after the parameter-free form had
already been written into the spec and the plan.

Shapes not yet verified and to be confirmed at implementation time:
`subscriptionAvailabilities`, the `subscriptionPrices` create body's exact
relationship set, and pagination limits on `pricePoints`.

## Manual steps this does not remove

1. Add a review screenshot to each subscription in the web UI.
2. Submit the subscriptions alongside the app version.
3. Create a sandbox tester account and verify a real purchase end to end —
   this is what unblocks the open TestFlight sandbox purchase item.

## Risks

**Writes against a live commercial account.** Mitigated by dry-run default, the
pure testable `plan()`, and the fact that Poty currently has zero products, so
the first run cannot damage existing configuration.

**Price tier mismatch.** If $4.99 or $24.99 does not correspond to an exact
Apple price point, the plan fails loudly rather than silently pricing near-miss.

**Partial application.** A failure mid-way through 350 price POSTs leaves a
subset applied. The diff model makes re-running the correct and safe recovery.

## Deliverables

**asokit**
- `products.py`: `plan()`, extended `check()`, new tests
- `asc.py`: `apply_products()`, `call_all()`, 429 retry
- `cli.py`: `products apply` subcommand
- README section, CHANGELOG entry, version → 0.3.0

**poty**
- `asokit.json` carrying `app.appId: 6761436106`
- the product definition file
- a short note on running it
