# Declarative IAP Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `asokit products apply <file>` create a subscription group, its subscriptions, prices across every territory, availability and localizations from one declarative file — idempotently, dry-run by default.

**Architecture:** All diff logic lives in the pure, unit-tested `products.py`; `asc.py` fetches inventory, hands it to `products.plan()`, and executes the returned ordered action list. The territory-level price diff — the part with 350 writes riding on it — is isolated in its own pure function so idempotence is testable without network.

**Tech Stack:** Python 3.9+, stdlib only (`unittest`, `urllib`). `pyjwt` + `cryptography` only under the `[connect]` extra. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-21-product-provisioning-design.md`

## Global Constraints

- **Python 3.9 floor.** No `match`, no `X | Y` type unions, no `dict |` merge. CI runs 3.9, 3.11, 3.13.
- **Zero runtime dependencies** in core modules. `products.py` must not import `jwt`, `cryptography`, or anything outside stdlib.
- **`products.py` is pure.** No network, no filesystem, no clock. This is what makes it testable.
- **`asc.py` has no test file** — repo convention, it is all I/O. Do not add `tests/test_asc.py`.
- **Test runner:** `python -m unittest discover -s tests -t . -v` from the repo root. Tests use `unittest.TestCase`, not pytest.
- **The suite is offline by design.** Every Apple call is stubbed; CI never touches a live endpoint.
- **Backward compatibility is mandatory.** asokit is on PyPI at 0.2.0. The flat `{productId: {locale: {field: value}}}` format must keep working in `check` and `push`.
- **Character limits** (already in `products.LIMITS`): `name` 30, `description` 45, `customAppName` 30.
- **`subscriptionPeriod` enum:** `ONE_WEEK`, `ONE_MONTH`, `TWO_MONTHS`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR`.
- **Dry-run is the default** for every writing command. `--apply` is opt-in.

---

### Task 1: Validate the declarative file format

**Files:**
- Modify: `asokit/products.py`
- Test: `tests/test_products.py`

**Interfaces:**
- Consumes: existing `products.LIMITS`, `products.check()`
- Produces: `products.PERIODS` (frozenset), `products.is_declarative(data) -> bool`, `products.check(data) -> [str]` now accepting both formats

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_products.py`:

```python
def declarative(**overrides):
    subscription = {
        "productId": "com.example.pro.annual",
        "name": "Pro Annual",
        "subscriptionPeriod": "ONE_YEAR",
        "groupLevel": 1,
        "familySharable": False,
        "price": {"baseTerritory": "USA", "customerPrice": "24.99"},
        "availability": {"allTerritories": True},
        "localizations": {"en-US": {"name": "Pro Annual", "description": "All year."}},
    }
    subscription.update(overrides)
    return {
        "groups": [
            {
                "referenceName": "Pro",
                "localizations": {"en-US": {"name": "Pro"}},
                "subscriptions": [subscription],
            }
        ]
    }


class DeclarativeFormat(unittest.TestCase):
    def test_detects_declarative_shape(self):
        self.assertTrue(products.is_declarative(declarative()))
        self.assertFalse(products.is_declarative({"com.example.pro": {}}))

    def test_valid_file_has_no_problems(self):
        self.assertEqual(products.check(declarative()), [])

    def test_flags_unknown_period(self):
        problems = products.check(declarative(subscriptionPeriod="FORTNIGHTLY"))
        self.assertTrue(any("subscriptionPeriod" in p for p in problems))

    def test_flags_missing_product_id(self):
        data = declarative()
        del data["groups"][0]["subscriptions"][0]["productId"]
        problems = products.check(data)
        self.assertTrue(any("productId" in p for p in problems))

    def test_flags_non_integer_group_level(self):
        problems = products.check(declarative(groupLevel="1"))
        self.assertTrue(any("groupLevel" in p for p in problems))

    def test_flags_non_decimal_price(self):
        problems = products.check(
            declarative(price={"baseTerritory": "USA", "customerPrice": "free"})
        )
        self.assertTrue(any("customerPrice" in p for p in problems))

    def test_enforces_description_limit_in_declarative_form(self):
        problems = products.check(
            declarative(
                localizations={"en-US": {"name": "Pro", "description": "x" * 46}}
            )
        )
        self.assertTrue(any("46 characters, limit is 45" in p for p in problems))

    def test_flat_format_still_validates(self):
        self.assertEqual(products.check(entry(name="Pro", description="ok")), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_products -v`
Expected: FAIL — `AttributeError: module 'asokit.products' has no attribute 'is_declarative'`

- [ ] **Step 3: Implement**

In `asokit/products.py`, add below `GROUP_FIELDS`:

```python
PERIODS = frozenset(
    {"ONE_WEEK", "ONE_MONTH", "TWO_MONTHS", "THREE_MONTHS", "SIX_MONTHS", "ONE_YEAR"}
)

SUBSCRIPTION_LOCALIZATION_FIELDS = PRODUCT_FIELDS
REVIEW_NOTE_LIMIT = 4000


def is_declarative(data):
    """True for the `{"groups": [...]}` shape, false for the flat locale map."""
    return isinstance(data, dict) and "groups" in data
```

Rename the current `check` body to `_check_flat` (unchanged logic), then add the dispatcher and the declarative validator:

```python
def check(products):
    """Validate either file format. Returns problem strings."""
    if is_declarative(products):
        return _check_declarative(products)
    return _check_flat(products)


def _check_localizations(prefix, locales, known, problems):
    """Shared field/limit validation for any {locale: {field: value}} map."""
    if not isinstance(locales, dict):
        problems.append(f"{prefix}: expected {{locale: fields}}")
        return
    for locale, fields in sorted(locales.items()):
        if not isinstance(fields, dict):
            problems.append(f"{prefix}.{locale}: expected {{field: value}}")
            continue
        for field, value in fields.items():
            if field not in known:
                problems.append(
                    f"{prefix}.{locale}: unknown field '{field}' "
                    f"(allowed: {', '.join(sorted(known))})"
                )
                continue
            if not isinstance(value, str):
                problems.append(
                    f"{prefix}.{locale}.{field}: expected text, "
                    f"got {type(value).__name__}"
                )
                continue
            limit = LIMITS[field]
            if len(value) > limit:
                problems.append(
                    f"{prefix}.{locale}.{field}: {len(value)} characters, "
                    f"limit is {limit}"
                )
        if "name" not in fields:
            problems.append(
                f"{prefix}.{locale}: 'name' is required — creating a "
                "localization without one is rejected by App Store Connect"
            )


def _is_decimal(value):
    if not isinstance(value, str) or not value:
        return False
    whole, _, fraction = value.partition(".")
    return whole.isdigit() and (fraction == "" or fraction.isdigit())


def _check_price(prefix, price, problems):
    if price is None:
        return
    if not isinstance(price, dict):
        problems.append(f"{prefix}.price: expected an object")
        return
    if not isinstance(price.get("baseTerritory"), str) or not price.get("baseTerritory"):
        problems.append(f"{prefix}.price.baseTerritory: required, e.g. 'USA'")
    if not _is_decimal(price.get("customerPrice")):
        problems.append(
            f"{prefix}.price.customerPrice: expected a decimal string like '24.99', "
            f"got {price.get('customerPrice')!r}"
        )


def _check_subscription(prefix, subscription, problems):
    if not isinstance(subscription, dict):
        problems.append(f"{prefix}: expected an object")
        return
    product_id = subscription.get("productId")
    if not isinstance(product_id, str) or not product_id:
        problems.append(f"{prefix}.productId: required, non-empty text")
    name = subscription.get("name")
    if not isinstance(name, str) or not name:
        problems.append(f"{prefix}.name: required, non-empty text")
    elif len(name) > LIMITS["name"]:
        problems.append(
            f"{prefix}.name: {len(name)} characters, limit is {LIMITS['name']}"
        )
    period = subscription.get("subscriptionPeriod")
    if period not in PERIODS:
        problems.append(
            f"{prefix}.subscriptionPeriod: {period!r} is not one of "
            f"{', '.join(sorted(PERIODS))}"
        )
    level = subscription.get("groupLevel")
    if level is not None and (not isinstance(level, int) or isinstance(level, bool) or level < 1):
        problems.append(f"{prefix}.groupLevel: expected a positive integer, got {level!r}")
    sharable = subscription.get("familySharable")
    if sharable is not None and not isinstance(sharable, bool):
        problems.append(f"{prefix}.familySharable: expected true or false, got {sharable!r}")
    note = subscription.get("reviewNote")
    if note is not None:
        if not isinstance(note, str):
            problems.append(f"{prefix}.reviewNote: expected text")
        elif len(note) > REVIEW_NOTE_LIMIT:
            problems.append(
                f"{prefix}.reviewNote: {len(note)} characters, limit is {REVIEW_NOTE_LIMIT}"
            )
    _check_price(prefix, subscription.get("price"), problems)
    _check_localizations(
        prefix, subscription.get("localizations", {}), PRODUCT_FIELDS, problems
    )


def _check_declarative(data):
    problems = []
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        return ["groups: expected a non-empty list"]
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            problems.append(f"groups[{index}]: expected an object")
            continue
        reference = group.get("referenceName")
        label = reference if isinstance(reference, str) and reference else f"groups[{index}]"
        if not isinstance(reference, str) or not reference:
            problems.append(f"groups[{index}].referenceName: required, non-empty text")
        _check_localizations(
            f"group:{label}", group.get("localizations", {}), GROUP_FIELDS, problems
        )
        subscriptions = group.get("subscriptions")
        if not isinstance(subscriptions, list) or not subscriptions:
            problems.append(f"group:{label}.subscriptions: expected a non-empty list")
            continue
        for position, subscription in enumerate(subscriptions):
            key = subscription.get("productId") if isinstance(subscription, dict) else None
            _check_subscription(key or f"group:{label}.subscriptions[{position}]", subscription, problems)
    return problems
```

Then rewrite `_check_flat` to delegate its inner loop to `_check_localizations`:

```python
def _check_flat(products):
    """Validate {productId: {locale: {field: value}}}. Returns problem strings."""
    problems = []
    for product_id, locales in sorted(products.items()):
        known = GROUP_FIELDS if product_id.startswith(GROUP_PREFIX) else PRODUCT_FIELDS
        _check_localizations(product_id, locales, known, problems)
    return problems
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_products -v`
Expected: PASS, including the pre-existing `CharacterLimits`, `Structure` and `Usage` classes — the `_check_flat` refactor must not change their messages.

- [ ] **Step 5: Commit**

```bash
git add asokit/products.py tests/test_products.py
git commit -m "feat(products): validate the declarative provisioning format"
```

---

### Task 2: Plan group, subscription and localization actions

**Files:**
- Modify: `asokit/products.py`
- Test: `tests/test_products.py`

**Interfaces:**
- Consumes: `products.PERIODS` from Task 1
- Produces: `products.PlanError`, `products.plan(desired, inventory) -> [dict]`. Actions are dicts with a `kind` key, one of `createGroup`, `createSubscription`, `patchSubscription`, `createLocalization`, `updateLocalization`, `setPrices`, `setAvailability`, `skip`. Resources are referenced by stable keys (`referenceName`, `productId`), never by ASC id, so the executor can resolve ids it creates mid-run.

**Inventory shape** (what `asc.products_status()` returns after Task 5):

```python
{
  "subscriptionGroups": [
    {
      "id": "123",
      "referenceName": "Pro",
      "localizations": {"en-US": {"id": "l1", "name": "Pro", "customAppName": None}},
      "subscriptions": [
        {
          "id": "456",
          "productId": "com.example.pro.annual",
          "state": "MISSING_METADATA",
          "attributes": {
            "name": "Pro Annual",
            "subscriptionPeriod": "ONE_YEAR",
            "groupLevel": 1,
            "familySharable": False,
            "reviewNote": None,
          },
          "localizations": {},
          "prices": {},
          "availability": None,
        }
      ],
    }
  ],
  "inAppPurchases": [],
}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_products.py`:

```python
EMPTY_INVENTORY = {"subscriptionGroups": [], "inAppPurchases": []}


def provisioned_inventory():
    """Inventory that exactly satisfies `declarative()`."""
    return {
        "subscriptionGroups": [
            {
                "id": "g1",
                "referenceName": "Pro",
                "localizations": {"en-US": {"id": "gl1", "name": "Pro", "customAppName": None}},
                "subscriptions": [
                    {
                        "id": "s1",
                        "productId": "com.example.pro.annual",
                        "state": "READY_TO_SUBMIT",
                        "attributes": {
                            "name": "Pro Annual",
                            "subscriptionPeriod": "ONE_YEAR",
                            "groupLevel": 1,
                            "familySharable": False,
                            "reviewNote": None,
                        },
                        "localizations": {
                            "en-US": {
                                "id": "sl1",
                                "name": "Pro Annual",
                                "description": "All year.",
                            }
                        },
                        "prices": {"USA": "pp1"},
                        "availability": {"allTerritories": True},
                    }
                ],
            }
        ],
        "inAppPurchases": [],
    }


def kinds(actions):
    return [action["kind"] for action in actions]


class PlanFromEmpty(unittest.TestCase):
    def test_creates_group_then_subscription(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        self.assertEqual(kinds(actions)[0], "createGroup")
        self.assertIn("createSubscription", kinds(actions))
        self.assertLess(
            kinds(actions).index("createGroup"),
            kinds(actions).index("createSubscription"),
        )

    def test_creates_localizations_and_price_and_availability(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        self.assertIn("createLocalization", kinds(actions))
        self.assertIn("setPrices", kinds(actions))
        self.assertIn("setAvailability", kinds(actions))

    def test_subscription_carries_creatable_attributes(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        create = next(a for a in actions if a["kind"] == "createSubscription")
        self.assertEqual(create["group"], "Pro")
        self.assertEqual(create["productId"], "com.example.pro.annual")
        self.assertEqual(create["attributes"]["subscriptionPeriod"], "ONE_YEAR")
        self.assertEqual(create["attributes"]["groupLevel"], 1)

    def test_prices_precede_nothing_but_follow_creation(self):
        actions = products.plan(declarative(), EMPTY_INVENTORY)
        self.assertLess(
            kinds(actions).index("createSubscription"),
            kinds(actions).index("setPrices"),
        )


class PlanIdempotence(unittest.TestCase):
    def test_fully_provisioned_inventory_writes_nothing(self):
        actions = products.plan(declarative(), provisioned_inventory())
        self.assertEqual(
            [a for a in actions if a["kind"] not in ("skip", "setPrices")],
            [],
            "a re-run against unchanged state must write nothing structural",
        )

    def test_existing_group_is_not_recreated(self):
        inventory = provisioned_inventory()
        inventory["subscriptionGroups"][0]["subscriptions"] = []
        actions = products.plan(declarative(), inventory)
        self.assertNotIn("createGroup", kinds(actions))
        self.assertIn("createSubscription", kinds(actions))


class PlanDrift(unittest.TestCase):
    def test_mutable_drift_emits_patch(self):
        inventory = provisioned_inventory()
        inventory["subscriptionGroups"][0]["subscriptions"][0]["attributes"]["groupLevel"] = 2
        actions = products.plan(declarative(), inventory)
        patch = next(a for a in actions if a["kind"] == "patchSubscription")
        self.assertEqual(patch["attributes"], {"groupLevel": 1})

    def test_immutable_drift_raises_before_any_write(self):
        inventory = provisioned_inventory()
        subscription = inventory["subscriptionGroups"][0]["subscriptions"][0]
        subscription["attributes"]["subscriptionPeriod"] = "ONE_MONTH"
        with self.assertRaises(products.PlanError) as caught:
            products.plan(declarative(), inventory)
        self.assertIn("subscriptionPeriod", str(caught.exception))

    def test_changed_localization_text_updates_rather_than_creates(self):
        inventory = provisioned_inventory()
        localization = inventory["subscriptionGroups"][0]["subscriptions"][0]["localizations"]
        localization["en-US"]["description"] = "Something else."
        actions = products.plan(declarative(), inventory)
        update = next(a for a in actions if a["kind"] == "updateLocalization")
        self.assertEqual(update["id"], "sl1")
        self.assertEqual(update["fields"]["description"], "All year.")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_products -v`
Expected: FAIL — `AttributeError: module 'asokit.products' has no attribute 'plan'`

- [ ] **Step 3: Implement**

Add to `asokit/products.py`:

```python
IMMUTABLE_SUBSCRIPTION_ATTRS = ("subscriptionPeriod",)
MUTABLE_SUBSCRIPTION_ATTRS = ("name", "groupLevel", "familySharable", "reviewNote")


class PlanError(Exception):
    """The file cannot be reconciled with live state without destroying something."""


def _localization_actions(parent_kind, parent_key, desired, existing):
    """create/update/skip per locale for one parent resource."""
    actions = []
    for locale, fields in sorted(desired.items()):
        current = existing.get(locale)
        if current and all(current.get(k) == v for k, v in fields.items()):
            actions.append(
                {
                    "kind": "skip",
                    "what": f"{parent_key} {locale} localization",
                }
            )
            continue
        actions.append(
            {
                "kind": "updateLocalization" if current else "createLocalization",
                "parentKind": parent_kind,
                "parentKey": parent_key,
                "locale": locale,
                "fields": dict(fields),
                "id": current["id"] if current else None,
            }
        )
    return actions


def plan(desired, inventory):
    """Diff the desired file against live inventory. Pure — no I/O.

    Returns an ordered action list. Raises PlanError when the file disagrees
    with live state on an attribute App Store Connect will not change.
    """
    groups = {g["referenceName"]: g for g in inventory.get("subscriptionGroups", [])}
    subscriptions = {
        subscription["productId"]: subscription
        for group in inventory.get("subscriptionGroups", [])
        for subscription in group.get("subscriptions", [])
    }

    actions = []
    for group in desired.get("groups", []):
        reference = group["referenceName"]
        live_group = groups.get(reference)
        if live_group is None:
            actions.append({"kind": "createGroup", "referenceName": reference})
        else:
            actions.append({"kind": "skip", "what": f"group '{reference}'"})
        actions.extend(
            _localization_actions(
                "group",
                reference,
                group.get("localizations", {}),
                (live_group or {}).get("localizations", {}),
            )
        )

        for subscription in group.get("subscriptions", []):
            product_id = subscription["productId"]
            live = subscriptions.get(product_id)
            attributes = {
                "name": subscription["name"],
                "productId": product_id,
                "subscriptionPeriod": subscription["subscriptionPeriod"],
            }
            for key in ("groupLevel", "familySharable", "reviewNote"):
                if subscription.get(key) is not None:
                    attributes[key] = subscription[key]

            if live is None:
                actions.append(
                    {
                        "kind": "createSubscription",
                        "group": reference,
                        "productId": product_id,
                        "attributes": attributes,
                    }
                )
            else:
                for key in IMMUTABLE_SUBSCRIPTION_ATTRS:
                    if live["attributes"].get(key) != subscription[key]:
                        raise PlanError(
                            f"{product_id}: {key} is {live['attributes'].get(key)!r} in "
                            f"App Store Connect but {subscription[key]!r} in the file. "
                            "This attribute cannot be changed after creation — fix the "
                            "file, or create a new product id. Nothing was sent."
                        )
                drifted = {
                    key: subscription[key]
                    for key in MUTABLE_SUBSCRIPTION_ATTRS
                    if subscription.get(key) is not None
                    and live["attributes"].get(key) != subscription[key]
                }
                if drifted:
                    actions.append(
                        {
                            "kind": "patchSubscription",
                            "productId": product_id,
                            "attributes": drifted,
                        }
                    )
                else:
                    actions.append({"kind": "skip", "what": product_id})

            actions.extend(
                _localization_actions(
                    "subscription",
                    product_id,
                    subscription.get("localizations", {}),
                    (live or {}).get("localizations", {}),
                )
            )

            price = subscription.get("price")
            if price:
                actions.append(
                    {
                        "kind": "setPrices",
                        "productId": product_id,
                        "baseTerritory": price["baseTerritory"],
                        "customerPrice": price["customerPrice"],
                    }
                )

            availability = subscription.get("availability")
            if availability and (live or {}).get("availability") != availability:
                actions.append(
                    {
                        "kind": "setAvailability",
                        "productId": product_id,
                        "allTerritories": availability.get("allTerritories", True),
                    }
                )

    return actions
```

Note on `setPrices`: it is always emitted when the file declares a price. Whether any territory actually needs writing is decided by `price_diff` in Task 3, which needs the live equalization map the executor fetches. The `skip` for a fully-priced subscription is produced at execution time, not here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_products -v`
Expected: PASS, all classes.

Note on `test_fully_provisioned_inventory_writes_nothing`: it excludes `setPrices` as well as `skip` deliberately. `plan()` always emits the `setPrices` intent when the file declares a price; whether any territory actually needs writing is `price_diff`'s job in Task 3, and that needs the live equalization map. So "structural" is the right scope for this assertion.

- [ ] **Step 5: Commit**

```bash
git add asokit/products.py tests/test_products.py
git commit -m "feat(products): pure plan() for groups, subscriptions and localizations"
```

---

### Task 3: The pure price diff

**Files:**
- Modify: `asokit/products.py`
- Test: `tests/test_products.py`

**Interfaces:**
- Produces: `products.price_diff(current, desired) -> [str]` — returns the sorted territory ids whose price point must be written. `current` and `desired` are both `{territoryId: pricePointId}`.

This is the function the whole idempotence argument rests on: 350 writes on a first run, zero on a second.

- [ ] **Step 1: Write the failing tests**

```python
class PriceDiff(unittest.TestCase):
    def test_empty_current_writes_every_territory(self):
        desired = {"USA": "pp1", "BRA": "pp2", "PRT": "pp3"}
        self.assertEqual(products.price_diff({}, desired), ["BRA", "PRT", "USA"])

    def test_identical_maps_write_nothing(self):
        desired = {"USA": "pp1", "BRA": "pp2"}
        self.assertEqual(products.price_diff(dict(desired), desired), [])

    def test_writes_only_the_territories_that_differ(self):
        current = {"USA": "pp1", "BRA": "OLD", "PRT": "pp3"}
        desired = {"USA": "pp1", "BRA": "pp2", "PRT": "pp3"}
        self.assertEqual(products.price_diff(current, desired), ["BRA"])

    def test_writes_territories_missing_from_current(self):
        current = {"USA": "pp1"}
        desired = {"USA": "pp1", "BRA": "pp2"}
        self.assertEqual(products.price_diff(current, desired), ["BRA"])

    def test_ignores_territories_present_only_in_current(self):
        current = {"USA": "pp1", "ATA": "stale"}
        desired = {"USA": "pp1"}
        self.assertEqual(products.price_diff(current, desired), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_products.PriceDiff -v`
Expected: FAIL — `AttributeError: module 'asokit.products' has no attribute 'price_diff'`

- [ ] **Step 3: Implement**

```python
def price_diff(current, desired):
    """Territories whose price point must be written.

    `current` and `desired` map territory id -> price point id. Territories
    present only in `current` are left alone: this provisions prices, it does
    not retract them.
    """
    return sorted(
        territory
        for territory, point in desired.items()
        if current.get(territory) != point
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_products -v`
Expected: PASS, all classes.

- [ ] **Step 5: Commit**

```bash
git add asokit/products.py tests/test_products.py
git commit -m "feat(products): pure territory-level price diff"
```

---

### Task 4: Pagination and retry in the network layer

**Files:**
- Modify: `asokit/asc.py:88-118` (the `call` function)

**Interfaces:**
- Consumes: nothing new
- Produces: `asc.call_all(method, path, bearer, body=None) -> [dict]` returning every page's `data` concatenated; `asc.call` transparently retrying transient failures.

No tests — `asc.py` is I/O only and has no test file by repo convention.

- [ ] **Step 1: Split the request out of `call`**

Replace the existing `call` in `asokit/asc.py` with:

```python
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4


def _request(method, path, bearer, body=None):
    url = path if path.startswith("http") else f"{API}{path}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode() if body else None, method=method
    )
    request.add_header("Authorization", f"Bearer {bearer}")
    if body:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
        return json.loads(raw) if raw else {}


def call(method, path, bearer, body=None):
    """One request, retrying rate limits and transient server errors."""
    url = path if path.startswith("http") else f"{API}{path}"
    for attempt in range(MAX_ATTEMPTS):
        try:
            return _request(method, path, bearer, body)
        except urllib.error.HTTPError as error:
            if error.code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
                continue
            detail = error.read().decode()
            try:
                errors = json.loads(detail).get("errors", [])
                detail = "\n".join(
                    f"  {item.get('title')}: {item.get('detail')}" for item in errors
                )
            except json.JSONDecodeError:
                pass
            raise ASCError(
                f"App Store Connect returned {error.code} for {method} {url}\n{detail}"
            )
```

`time` is already imported at the top of `asc.py` for JWT timestamps — no new import.

- [ ] **Step 2: Add `call_all`**

Directly below `call`:

```python
def call_all(method, path, bearer, body=None):
    """Every page of a paged collection, concatenated.

    App Store Connect caps a page at 200 rows and puts the next page's absolute
    URL in `links.next`. `call` already accepts an absolute URL, so following
    the chain needs no extra plumbing. Price point listings run to thousands of
    rows — reading only the first page silently selects the wrong base price.
    """
    items = []
    url = path
    while url:
        page = call(method, url, bearer, body)
        items.extend(page.get("data", []))
        url = page.get("links", {}).get("next")
    return items
```

- [ ] **Step 3: Verify nothing regressed**

Run: `python -m unittest discover -s tests -t . -v`
Expected: PASS — the suite is offline and does not exercise `asc.py`, so this confirms no import-time breakage.

Then verify against the live account read-only:

```bash
set -a && source ~/.config/asokit/env && set +a
python3 -c "
from asokit import asc
b = asc.token()
print('apps:', len(asc.call_all('GET', '/apps?limit=10', b)))
"
```
Expected: a non-zero count, no traceback.

- [ ] **Step 4: Commit**

```bash
git add asokit/asc.py
git commit -m "feat(asc): follow pagination and retry rate limits"
```

---

### Task 5: Extend the inventory and execute the plan

**Files:**
- Modify: `asokit/asc.py` (`_product_localizations`, `products_status`), add `apply_products`
- Modify: `asokit/cli.py:400-419` (`cmd_products_status`, one `.get` fix)

**Interfaces:**
- Consumes: `products.plan`, `products.price_diff`, `asc.call_all`
- Produces: `asc.products_status()` returning subscriptions with `attributes`, `prices`, `availability`; `asc.apply_products(app_id, desired, bearer, apply=False) -> [dict]` returning the executed or planned action list, each annotated with `"applied": bool`.

- [ ] **Step 1: Read `customAppName` in localizations**

In `asokit/asc.py`, `_product_localizations` currently keeps only `name`, `description` and `state`. Group localizations carry `customAppName` instead of `description`, so a group whose `customAppName` matches would still be rewritten. Change the dict comprehension body to:

```python
        item["attributes"]["locale"]: {
            "id": item["id"],
            "name": item["attributes"].get("name"),
            "description": item["attributes"].get("description"),
            "customAppName": item["attributes"].get("customAppName"),
            "state": item["attributes"].get("state"),
        }
```

- [ ] **Step 2: Carry attributes, prices and availability in the inventory**

In `products_status`, replace the subscription append block with:

```python
        for subscription in subscriptions.get("data", []):
            subscription_id = subscription["id"]
            attributes = subscription["attributes"]
            entry["subscriptions"].append(
                {
                    "id": subscription_id,
                    "productId": attributes["productId"],
                    "state": attributes.get("state"),
                    "attributes": {
                        "name": attributes.get("name"),
                        "subscriptionPeriod": attributes.get("subscriptionPeriod"),
                        "groupLevel": attributes.get("groupLevel"),
                        "familySharable": attributes.get("familySharable"),
                        "reviewNote": attributes.get("reviewNote"),
                    },
                    "localizations": _product_localizations(
                        bearer, "subscription", subscription_id
                    ),
                    "prices": _subscription_prices(bearer, subscription_id),
                    "availability": _subscription_availability(bearer, subscription_id),
                }
            )
```

And add the two readers above `products_status`:

```python
def _subscription_prices(bearer, subscription_id):
    """Current {territory id: price point id} for a subscription."""
    rows = call_all(
        "GET",
        f"/subscriptions/{subscription_id}/prices"
        "?include=territory,subscriptionPricePoint&limit=200",
        bearer,
    )
    prices = {}
    for row in rows:
        relationships = row.get("relationships", {})
        territory = relationships.get("territory", {}).get("data") or {}
        point = relationships.get("subscriptionPricePoint", {}).get("data") or {}
        if territory.get("id") and point.get("id"):
            prices[territory["id"]] = point["id"]
    return prices


def _subscription_availability(bearer, subscription_id):
    """{'allTerritories': bool} or None when availability has never been set."""
    try:
        response = call(
            "GET", f"/subscriptions/{subscription_id}/subscriptionAvailability", bearer
        )
    except ASCError:
        return None
    data = response.get("data")
    if not data:
        return None
    return {
        "allTerritories": bool(
            data.get("attributes", {}).get("availableInNewTerritories")
        )
    }
```

- [ ] **Step 3: Fix the status printer for absent descriptions**

In `asokit/cli.py`, `cmd_products_status` prints `item['description']` directly. Group localizations have none. Change both localization print lines to use `.get`:

```python
                print(f"    {locale:<8} {item.get('name')!r} / {item.get('description')!r} [{item.get('state')}]")
```

- [ ] **Step 4: Write the executor**

Add to `asokit/asc.py`, importing products at the top (`from . import products as prod`):

```python
def _resolve_price_points(bearer, subscription_id, base_territory, customer_price):
    """{territory: price point id} for `customer_price` in every territory.

    Selects the base territory's point by EXACT customer price and fails loudly
    otherwise — silently taking the nearest tier would misprice the product in
    every storefront at once.
    """
    points = call_all(
        "GET",
        f"/subscriptions/{subscription_id}/pricePoints"
        f"?filter[territory]={base_territory}&limit=200",
        bearer,
    )
    match = next(
        (p for p in points if p["attributes"].get("customerPrice") == customer_price),
        None,
    )
    if match is None:
        available = sorted(
            {p["attributes"].get("customerPrice") for p in points if p.get("attributes")}
        )
        raise ASCError(
            f"no {base_territory} price point at exactly {customer_price}. "
            f"Nearby tiers: {', '.join(available[:10])}"
        )
    equalized = call_all(
        "GET", f"/subscriptionPricePoints/{match['id']}/equalizations?limit=200", bearer
    )
    resolved = {base_territory: match["id"]}
    for point in equalized:
        territory = (
            point.get("relationships", {}).get("territory", {}).get("data") or {}
        )
        if territory.get("id"):
            resolved[territory["id"]] = point["id"]
    return resolved


def apply_products(app_id, desired, bearer, apply=False):
    """Reconcile App Store Connect with `desired`. Dry run unless apply=True."""
    inventory = products_status(app_id, bearer)
    actions = prod.plan(desired, inventory)

    ids = {
        f"group:{group['referenceName']}": group["id"]
        for group in inventory["subscriptionGroups"]
    }
    ids.update(
        {
            subscription["productId"]: subscription["id"]
            for group in inventory["subscriptionGroups"]
            for subscription in group["subscriptions"]
        }
    )
    live_prices = {
        subscription["productId"]: subscription["prices"]
        for group in inventory["subscriptionGroups"]
        for subscription in group["subscriptions"]
    }

    executed = []
    for action in actions:
        kind = action["kind"]
        action = dict(action, applied=False)

        if kind == "skip":
            executed.append(action)
            continue

        if kind == "createGroup":
            if apply:
                created = call(
                    "POST",
                    "/subscriptionGroups",
                    bearer,
                    {
                        "data": {
                            "type": "subscriptionGroups",
                            "attributes": {"referenceName": action["referenceName"]},
                            "relationships": {
                                "app": {"data": {"type": "apps", "id": str(app_id)}}
                            },
                        }
                    },
                )
                ids[f"group:{action['referenceName']}"] = created["data"]["id"]
                action["applied"] = True

        elif kind == "createSubscription":
            group_id = ids.get(f"group:{action['group']}")
            if apply:
                created = call(
                    "POST",
                    "/subscriptions",
                    bearer,
                    {
                        "data": {
                            "type": "subscriptions",
                            "attributes": action["attributes"],
                            "relationships": {
                                "group": {
                                    "data": {
                                        "type": "subscriptionGroups",
                                        "id": group_id,
                                    }
                                }
                            },
                        }
                    },
                )
                ids[action["productId"]] = created["data"]["id"]
                action["applied"] = True

        elif kind == "patchSubscription":
            if apply:
                subscription_id = ids[action["productId"]]
                call(
                    "PATCH",
                    f"/subscriptions/{subscription_id}",
                    bearer,
                    {
                        "data": {
                            "type": "subscriptions",
                            "id": subscription_id,
                            "attributes": action["attributes"],
                        }
                    },
                )
                action["applied"] = True

        elif kind in ("createLocalization", "updateLocalization"):
            if apply:
                parent_kind = "group" if action["parentKind"] == "group" else "subscription"
                resource_type, relationship, parent_type = _PRODUCT_RESOURCES[parent_kind]
                key = (
                    f"group:{action['parentKey']}"
                    if parent_kind == "group"
                    else action["parentKey"]
                )
                _write(
                    bearer,
                    resource_type,
                    action["id"],
                    action["fields"],
                    action["locale"],
                    (relationship, parent_type, ids[key]),
                )
                action["applied"] = True

        elif kind == "setPrices":
            subscription_id = ids.get(action["productId"])
            if subscription_id is None:
                action["territories"] = None
                action["note"] = "subscription not created yet (dry run)"
                executed.append(action)
                continue
            resolved = _resolve_price_points(
                bearer,
                subscription_id,
                action["baseTerritory"],
                action["customerPrice"],
            )
            pending = prod.price_diff(
                live_prices.get(action["productId"], {}), resolved
            )
            action["territories"] = pending
            if apply:
                for territory in pending:
                    call(
                        "POST",
                        "/subscriptionPrices",
                        bearer,
                        {
                            "data": {
                                "type": "subscriptionPrices",
                                "attributes": {"preserveCurrentPrice": False},
                                "relationships": {
                                    "subscription": {
                                        "data": {
                                            "type": "subscriptions",
                                            "id": subscription_id,
                                        }
                                    },
                                    "subscriptionPricePoint": {
                                        "data": {
                                            "type": "subscriptionPricePoints",
                                            "id": resolved[territory],
                                        }
                                    },
                                },
                            }
                        },
                    )
                action["applied"] = bool(pending)

        elif kind == "setAvailability":
            subscription_id = ids.get(action["productId"])
            if apply and subscription_id:
                call(
                    "POST",
                    "/subscriptionAvailabilities",
                    bearer,
                    {
                        "data": {
                            "type": "subscriptionAvailabilities",
                            "attributes": {
                                "availableInNewTerritories": action["allTerritories"]
                            },
                            "relationships": {
                                "subscription": {
                                    "data": {
                                        "type": "subscriptions",
                                        "id": subscription_id,
                                    }
                                }
                            },
                        }
                    },
                )
                action["applied"] = True

        executed.append(action)

    return executed
```

- [ ] **Step 5: Verify the read path against the live account**

```bash
set -a && source ~/.config/asokit/env && set +a
python3 -c "
from asokit import asc
import json
print(json.dumps(asc.products_status('6761436106', asc.token()), indent=2))
"
```
Expected: `{"subscriptionGroups": [], "inAppPurchases": []}` — Poty has no products yet, so this confirms the extended reader does not crash on an empty account.

- [ ] **Step 6: Run the suite**

Run: `python -m unittest discover -s tests -t . -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add asokit/asc.py asokit/cli.py
git commit -m "feat(asc): apply_products executor with price and availability reconciliation"
```

---

### Task 6: The `products apply` command, docs and release

**Files:**
- Modify: `asokit/cli.py` (module docstring, `cmd_products_apply`, `build_parser`)
- Modify: `README.md`, `CHANGELOG.md`, `pyproject.toml`

**Interfaces:**
- Consumes: `asc.apply_products`, `products.check`
- Produces: `asokit products apply <file> [--app-id] [--apply] [--verbose]`

- [ ] **Step 1: Add the command**

In `asokit/cli.py`, after `cmd_products_push`:

```python
def cmd_products_apply(args):
    config = load_config(args.config) if Path(args.config).exists() else {}
    app_id = _app_id(args, config)
    if not app_id:
        sys.exit("need an appId — pass --app-id or set app.appId in the config")

    data = json.loads(Path(args.file).read_text())
    if not prod.is_declarative(data):
        sys.exit(
            "this file is the flat localization format — use `asokit products push`.\n"
            "`apply` expects a declarative file with a top-level 'groups' key."
        )
    problems = prod.check(data)
    if problems:
        print("validation failed — nothing sent:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    actions = asc.apply_products(app_id, data, asc.token(), apply=args.apply)

    for action in actions:
        kind = action["kind"]
        if kind == "skip":
            print(f"  skip               {action['what']}")
        elif kind == "setPrices":
            territories = action.get("territories")
            if territories is None:
                print(
                    f"  prices             {action['productId']} — "
                    f"{action['baseTerritory']} {action['customerPrice']} "
                    "(territories resolve after creation)"
                )
            elif not territories:
                print(f"  skip               {action['productId']} prices (unchanged)")
            else:
                print(
                    f"  prices             {action['productId']} — "
                    f"{len(territories)} territories at "
                    f"{action['baseTerritory']} {action['customerPrice']}"
                )
                if args.verbose:
                    for territory in territories:
                        print(f"      {territory}")
        elif kind in ("createLocalization", "updateLocalization"):
            operation = "create" if kind == "createLocalization" else "update"
            print(
                f"  {operation + ' localization':<18} "
                f"{action['parentKey']} {action['locale']} "
                f"({', '.join(sorted(action['fields']))})"
            )
        elif kind == "createGroup":
            print(f"  create group       {action['referenceName']}")
        elif kind == "createSubscription":
            print(f"  create             {action['productId']}")
        elif kind == "patchSubscription":
            print(
                f"  patch              {action['productId']} "
                f"({', '.join(sorted(action['attributes']))})"
            )
        elif kind == "setAvailability":
            print(f"  availability       {action['productId']}")

    if args.apply:
        print(
            "\napplied. Subscriptions will sit in MISSING_METADATA until each one has"
            "\na review screenshot — add those in App Store Connect, then submit them"
            "\nalongside your next app version."
        )
    else:
        print("\nDRY RUN — nothing written. Re-run with --apply to provision.")
```

- [ ] **Step 2: Teach `products check` to print the declarative format**

`cmd_products_check` currently does `sorted(data.items())` and then treats each
value as a `{locale: fields}` map. Handed a declarative file it iterates
`("groups", [...])` and dies with
`AttributeError: 'list' object has no attribute 'items'` — before printing
anything. `prod.check()` itself is already format-aware after Task 1; only the
printer is not. Replace the printing loop in `cmd_products_check` so it walks
either shape:

```python
def _gauge_rows(data):
    """(label, locale, field, value) rows for either file format."""
    if not prod.is_declarative(data):
        for product_id, locales in sorted(data.items()):
            for locale, fields in sorted(locales.items()):
                for field, value in fields.items():
                    yield product_id, locale, field, value
        return
    for group in data.get("groups", []):
        label = f"group:{group.get('referenceName')}"
        for locale, fields in sorted(group.get("localizations", {}).items()):
            for field, value in fields.items():
                yield label, locale, field, value
        for subscription in group.get("subscriptions", []):
            product_id = subscription.get("productId")
            for locale, fields in sorted(subscription.get("localizations", {}).items()):
                for field, value in fields.items():
                    yield product_id, locale, field, value


def cmd_products_check(args):
    data = json.loads(Path(args.file).read_text())
    problems = prod.check(data)
    current = None
    for label, locale, field, value in _gauge_rows(data):
        if label != current:
            print(f"\n{'=' * 58}\n{label}\n{'=' * 58}")
            current = label
        limit = prod.LIMITS.get(field)
        gauge = f"{len(value)}/{limit}" if isinstance(value, str) and limit else "?"
        print(f"  {locale:<8} {field:<14} ({gauge})  {value}")
    if problems:
        print(f"\n{'!' * 58}\n{len(problems)} problem(s)\n{'!' * 58}")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    print("\nAll fields within limits.")
```

Verify both formats still print:

```bash
python -m asokit products check <a flat file>        # unchanged output shape
python -m asokit products check <a declarative file> # group + per-subscription sections
```

- [ ] **Step 3: Wire the parser**

In `build_parser`, after the `products_push` block:

```python
    products_apply = products_sub.add_parser(
        "apply", help="provision groups, subscriptions, prices (dry run unless --apply)"
    )
    products_apply.add_argument("file")
    products_apply.add_argument("--app-id")
    products_apply.add_argument("--apply", action="store_true")
    products_apply.add_argument(
        "--verbose", action="store_true", help="list every territory instead of a count"
    )
    products_apply.set_defaults(func=cmd_products_apply)
```

- [ ] **Step 4: Update the module docstring**

Add one line to the `asokit/cli.py` docstring, after the `products push` line:

```
  asokit products apply <file> [--apply]  provision products, prices, availability
```

- [ ] **Step 5: Verify the command runs and dry-runs safely**

```bash
python -m asokit products apply --help
```
Expected: help text listing `--app-id`, `--apply`, `--verbose`.

- [ ] **Step 6: Update README, CHANGELOG and version**

In `README.md`, in the App Store Connect section, add a subsection documenting the declarative format (copy the JSON block from the spec's "File format" section verbatim) and the three commands, stating that `apply` is a dry run without `--apply` and that review screenshots remain manual.

In `CHANGELOG.md`, add at the top:

```markdown
## 0.3.0

- `asokit products apply` — declaratively provision subscription groups,
  subscriptions, prices across every territory, and availability from one file.
  Idempotent: a re-run against unchanged state writes nothing. Dry run unless
  `--apply`.
- `products check` now validates the declarative format alongside the existing
  flat localization format.
- App Store Connect calls follow pagination and retry rate limits.
- Review screenshots and submission remain manual by design.
```

In `pyproject.toml`, bump `version = "0.2.0"` to `version = "0.3.0"`.

- [ ] **Step 7: Run the full suite**

Run: `python -m unittest discover -s tests -t . -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add asokit/cli.py README.md CHANGELOG.md pyproject.toml
git commit -m "feat(cli): products apply, docs, release 0.3.0"
```

---

### Task 7: Provision Poty

**Files:**
- Create: `~/Projects/mobileapps/poty/asokit.json`
- Create: `~/Projects/mobileapps/poty/aso/products.json`
- Modify: `~/Projects/mobileapps/poty/CLAUDE.md` (one row in the Key Documentation table)

**Interfaces:**
- Consumes: `asokit products check` / `apply` from Tasks 1-6

This task writes to a live commercial App Store Connect account. Steps 4 and 5 are separated deliberately: the dry run must be read and approved by a human before `--apply` runs.

- [ ] **Step 1: Write the asokit config**

`~/Projects/mobileapps/poty/asokit.json`:

```json
{
  "app": {
    "name": "Poty The Calorie Tracker",
    "appId": 6761436106,
    "outputDir": "aso"
  },
  "markets": {}
}
```

- [ ] **Step 2: Write the product definition**

`~/Projects/mobileapps/poty/aso/products.json` — the full configuration from the spec. Both subscriptions carry the same `reviewNote`; `familySharable` is false on both, which the spec explains is required by the `appAccountToken` entitlement binding, not a preference.

```json
{
  "groups": [
    {
      "referenceName": "Poty Pro",
      "localizations": {
        "en-US": {"name": "Poty Pro"},
        "pt-BR": {"name": "Poty Pro"},
        "pt-PT": {"name": "Poty Pro"},
        "es-ES": {"name": "Poty Pro"},
        "es-MX": {"name": "Poty Pro"}
      },
      "subscriptions": [
        {
          "productId": "com.potylabs.poty.annual",
          "name": "Poty Pro Annual",
          "subscriptionPeriod": "ONE_YEAR",
          "groupLevel": 1,
          "familySharable": false,
          "reviewNote": "Poty Pro unlocks unlimited AI-powered food logging by photo, voice and text. The free tier includes 30 AI logs per month plus unlimited manual entry and food-database search, so no test account is required. The paywall appears at the end of onboarding and in Settings.",
          "availability": {"allTerritories": true},
          "price": {"baseTerritory": "USA", "customerPrice": "24.99"},
          "localizations": {
            "en-US": {"name": "Poty Pro Annual", "description": "Unlimited AI food logging, all year."},
            "pt-BR": {"name": "Poty Pro Anual", "description": "Registros ilimitados com IA, o ano todo."},
            "pt-PT": {"name": "Poty Pro Anual", "description": "Registos ilimitados com IA, todo o ano."},
            "es-ES": {"name": "Poty Pro Anual", "description": "Registros ilimitados con IA, todo el año."},
            "es-MX": {"name": "Poty Pro Anual", "description": "Registros ilimitados con IA, todo el año."}
          }
        },
        {
          "productId": "com.potylabs.poty.monthly",
          "name": "Poty Pro Monthly",
          "subscriptionPeriod": "ONE_MONTH",
          "groupLevel": 2,
          "familySharable": false,
          "reviewNote": "Poty Pro unlocks unlimited AI-powered food logging by photo, voice and text. The free tier includes 30 AI logs per month plus unlimited manual entry and food-database search, so no test account is required. The paywall appears at the end of onboarding and in Settings.",
          "availability": {"allTerritories": true},
          "price": {"baseTerritory": "USA", "customerPrice": "4.99"},
          "localizations": {
            "en-US": {"name": "Poty Pro Monthly", "description": "Unlimited AI food logging, every month."},
            "pt-BR": {"name": "Poty Pro Mensal", "description": "Registros ilimitados com IA, todo mês."},
            "pt-PT": {"name": "Poty Pro Mensal", "description": "Registos ilimitados com IA, todos os meses."},
            "es-ES": {"name": "Poty Pro Mensual", "description": "Registros ilimitados con IA, cada mes."},
            "es-MX": {"name": "Poty Pro Mensual", "description": "Registros ilimitados con IA, cada mes."}
          }
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Validate offline**

```bash
cd ~/Projects/mobileapps/poty
python -m asokit products check aso/products.json
```
Expected: every field listed with its `used/limit` gauge, ending in `All fields within limits.` and exit 0. The tightest is the pt-PT monthly description at 43/45.

- [ ] **Step 4: Dry run against the live account — STOP AND READ**

```bash
cd ~/Projects/mobileapps/poty
set -a && source ~/.config/asokit/env && set +a
python -m asokit products apply aso/products.json
```

Expected output shape:

```
  create group       Poty Pro
  create localization  Poty Pro en-US (name)
  ... 5 group localizations ...
  create             com.potylabs.poty.annual
  create localization  com.potylabs.poty.annual en-US (description, name)
  ... 5 subscription localizations ...
  prices             com.potylabs.poty.annual — 4.99/24.99 (territories resolve after creation)
  availability       com.potylabs.poty.annual
  ... same for monthly ...

DRY RUN — nothing written. Re-run with --apply to provision.
```

Confirm before continuing: two subscriptions, one group, 15 localizations, correct product ids, correct `groupLevel` values. **Do not proceed to Step 5 without a human approving this output.**

- [ ] **Step 5: Apply**

```bash
python -m asokit products apply aso/products.json --apply
```
Expected: the same action list, then the MISSING_METADATA closing note.

- [ ] **Step 6: Verify idempotence against the live account**

```bash
python -m asokit products apply aso/products.json
```
Expected: **every line reads `skip`**, including `skip com.potylabs.poty.annual prices (unchanged)` for both subscriptions. This is the run that proves the design — 350 price writes on the first pass, zero on the second. If any non-skip action appears, the diff is wrong; stop and fix before re-applying.

- [ ] **Step 7: Confirm prices landed**

```bash
python -m asokit products status --app-id 6761436106
```
Expected: the group, both subscriptions with their states, and all 15 localizations.

- [ ] **Step 8: Document it in Poty**

Add a row to the Key Documentation table in `~/Projects/mobileapps/poty/CLAUDE.md`:

```markdown
| `aso/products.json` | App Store Connect subscription products (ids, prices, 5-locale copy). Apply with `asokit products apply aso/products.json --apply`. Product ids must stay in sync with `SubscriptionService.swift` and `supabase/functions/_shared/appstore.ts`. |
```

- [ ] **Step 9: Commit**

```bash
cd ~/Projects/mobileapps/poty
git add asokit.json aso/products.json CLAUDE.md
git commit -m "feat(asc): declarative subscription product definition"
```

---

## Remaining manual work

Not covered by this plan, by design — carried forward from the spec:

1. Add a review screenshot to each subscription in App Store Connect. Until then both sit in `MISSING_METADATA`.
2. Submit the subscriptions alongside the next app version.
3. Create a sandbox tester and verify a real purchase end to end — this closes the open TestFlight sandbox purchase item.
