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

REVIEW_NOTE_LIMIT = 4000

IMMUTABLE_SUBSCRIPTION_ATTRS = ("subscriptionPeriod",)
MUTABLE_SUBSCRIPTION_ATTRS = ("name", "groupLevel", "familySharable", "reviewNote")


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
        problems.append(
            f"{prefix}.price: required — App Store Connect cannot create a "
            "subscription without a price"
        )
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


def _check_availability(prefix, availability, problems):
    """Shape-only: the key itself stays optional."""
    if availability is None:
        return
    if not isinstance(availability, dict):
        problems.append(f"{prefix}.availability: expected an object")
        return
    everywhere = availability.get("allTerritories")
    if everywhere is not None and not isinstance(everywhere, bool):
        problems.append(
            f"{prefix}.availability.allTerritories: expected true or false, "
            f"got {everywhere!r}"
        )


def _check_required_localizations(prefix, locales, known, subject, problems):
    """Like `_check_localizations`, but at least one locale must be present."""
    if locales is None or (isinstance(locales, dict) and not locales):
        problems.append(
            f"{prefix}.localizations: at least one locale is required — App "
            f"Store Connect rejects {subject} created without one"
        )
        return
    _check_localizations(prefix, locales, known, problems)


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
    _check_availability(prefix, subscription.get("availability"), problems)
    _check_required_localizations(
        prefix,
        subscription.get("localizations"),
        PRODUCT_FIELDS,
        "a subscription",
        problems,
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
        _check_required_localizations(
            f"group:{label}",
            group.get("localizations"),
            GROUP_FIELDS,
            "a subscription group",
            problems,
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
        subscription["productId"]: (group["referenceName"], subscription)
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
            live_group_name, live = subscriptions.get(product_id, (None, None))
            if live is not None and live_group_name != reference:
                raise PlanError(
                    f"{product_id}: lives in subscription group "
                    f"{live_group_name!r} in App Store Connect but is declared "
                    f"under {reference!r} in the file. This tool does not move "
                    "subscriptions between groups — fix the file, or move the "
                    "product by hand in App Store Connect. Nothing was sent."
                )
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
            # The inventory normalizes availability to exactly
            # {"allTerritories": bool}, so whole-dict equality is safe here.
            if availability and (live or {}).get("availability") != availability:
                actions.append(
                    {
                        "kind": "setAvailability",
                        "productId": product_id,
                        "allTerritories": availability.get("allTerritories", True),
                    }
                )

    return actions


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
