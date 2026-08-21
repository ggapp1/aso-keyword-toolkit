"""In-app purchase and subscription localization limits and validation.

Product-facing text lives in three different resources, one per product kind:

  subscriptionLocalizations       name, description       (each subscription)
  subscriptionGroupLocalizations  name, customAppName     (the group itself)
  inAppPurchaseLocalizations      name, description       (one-time purchases)

All three are per-locale. Unlike app metadata, they do not need an editable
app version — but changing text on an already-approved product puts it back
into review, riding along with the next app submission. Adding a brand-new
locale is the purely additive case.

The file format `check()` validates maps product id -> locale -> fields:

  {
    "com.example.pro.lifetime": {
      "en-US": {"name": "Pro Lifetime", "description": "One-time purchase."},
      "pt-BR": {"name": "Pro Vitalício"}
    },
    "group:Pro": {
      "pt-BR": {"name": "Pro"}
    }
  }

Keys are App Store product ids; a `group:` prefix addresses a subscription
group by its reference name. Everything here is pure: no network, no
credentials. `check()` is the gate to run before any upload.
"""

GROUP_PREFIX = "group:"

LIMITS = {
    "name": 30,
    "description": 45,
    "customAppName": 30,
}

PRODUCT_FIELDS = frozenset({"name", "description"})
GROUP_FIELDS = frozenset({"name", "customAppName"})

PERIODS = frozenset(
    {"ONE_WEEK", "ONE_MONTH", "TWO_MONTHS", "THREE_MONTHS", "SIX_MONTHS", "ONE_YEAR"}
)

SUBSCRIPTION_LOCALIZATION_FIELDS = PRODUCT_FIELDS
REVIEW_NOTE_LIMIT = 4000


def is_declarative(data):
    """True for the `{"groups": [...]}` shape, false for the flat locale map."""
    return isinstance(data, dict) and "groups" in data


def check(products):
    """Validate either file format. Returns problem strings."""
    if is_declarative(products):
        return _check_declarative(products)
    return _check_flat(products)


def _check_flat(products):
    """Validate {productId: {locale: {field: value}}}. Returns problem strings."""
    problems = []
    for product_id, locales in sorted(products.items()):
        known = GROUP_FIELDS if product_id.startswith(GROUP_PREFIX) else PRODUCT_FIELDS
        _check_localizations(product_id, locales, known, problems)
    return problems


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
    if level is not None and (
        not isinstance(level, int) or isinstance(level, bool) or level < 1
    ):
        problems.append(
            f"{prefix}.groupLevel: expected a positive integer, got {level!r}"
        )
    sharable = subscription.get("familySharable")
    if sharable is not None and not isinstance(sharable, bool):
        problems.append(
            f"{prefix}.familySharable: expected true or false, got {sharable!r}"
        )
    note = subscription.get("reviewNote")
    if note is not None:
        if not isinstance(note, str):
            problems.append(f"{prefix}.reviewNote: expected text")
        elif len(note) > REVIEW_NOTE_LIMIT:
            problems.append(
                f"{prefix}.reviewNote: {len(note)} characters, "
                f"limit is {REVIEW_NOTE_LIMIT}"
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
        label = (
            reference if isinstance(reference, str) and reference else f"groups[{index}]"
        )
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
            key = (
                subscription.get("productId")
                if isinstance(subscription, dict)
                else None
            )
            _check_subscription(
                key or f"group:{label}.subscriptions[{position}]",
                subscription,
                problems,
            )
    return problems


def usage(products):
    """Character usage per product per locale, for display."""
    report = {}
    for product_id, locales in products.items():
        report[product_id] = {
            locale: {
                field: (len(value), LIMITS.get(field))
                for field, value in fields.items()
                if isinstance(value, str)
            }
            for locale, fields in locales.items()
        }
    return report
