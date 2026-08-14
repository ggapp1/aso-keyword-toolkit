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


def check(products):
    """Validate {productId: {locale: {field: value}}}. Returns problem strings."""
    problems = []
    for product_id, locales in sorted(products.items()):
        known = GROUP_FIELDS if product_id.startswith(GROUP_PREFIX) else PRODUCT_FIELDS
        if not isinstance(locales, dict):
            problems.append(f"{product_id}: expected {{locale: fields}}")
            continue
        for locale, fields in sorted(locales.items()):
            if not isinstance(fields, dict):
                problems.append(f"{product_id}.{locale}: expected {{field: value}}")
                continue
            for field, value in fields.items():
                if field not in known:
                    problems.append(
                        f"{product_id}.{locale}: unknown field '{field}' "
                        f"(allowed: {', '.join(sorted(known))})"
                    )
                    continue
                if not isinstance(value, str):
                    problems.append(
                        f"{product_id}.{locale}.{field}: expected text, "
                        f"got {type(value).__name__}"
                    )
                    continue
                limit = LIMITS[field]
                if len(value) > limit:
                    problems.append(
                        f"{product_id}.{locale}.{field}: {len(value)} characters, "
                        f"limit is {limit}"
                    )
            if "name" not in fields:
                problems.append(
                    f"{product_id}.{locale}: 'name' is required — creating a "
                    "localization without one is rejected by App Store Connect"
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
