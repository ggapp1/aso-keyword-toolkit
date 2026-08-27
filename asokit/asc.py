"""App Store Connect metadata sync.

Localized metadata lives in two different resources, which is the detail that
makes hand-rolling this annoying:

  appInfoLocalizations          name, subtitle, privacyPolicyUrl
  appStoreVersionLocalizations  keywords, description, promotionalText, whatsNew

Both are per-locale and both are only writable while a version sits in an
editable state. `status()` reports whether that's true before you try.

Product text (in-app purchases, subscriptions, subscription groups) is a
separate family of per-locale resources with no editable-version requirement —
see `products.py` for the format and `products_status()`/`push_products()`
here for the sync.

Credentials come from the environment, never from a file in the repo:
  ASC_KEY_ID, ASC_ISSUER_ID, ASC_PRIVATE_KEY_PATH

Create the key at App Store Connect -> Users and Access -> Integrations, with
the App Manager role. Requires `pyjwt` and `cryptography`; everything else in
this toolkit is standard library only.
"""

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import products as prod
from .metadata import APP_INFO_FIELDS, VERSION_FIELDS

API = "https://api.appstoreconnect.apple.com/v1"
# In-app purchases are Apple's one v2-only resource family: the app lists them
# via /v1/apps/{id}/inAppPurchasesV2, but the resources themselves (type
# "inAppPurchases") are addressed under /v2.
API_V2 = "https://api.appstoreconnect.apple.com/v2"

EDITABLE_STATES = frozenset(
    {
        "PREPARE_FOR_SUBMISSION",
        "DEVELOPER_REJECTED",
        "REJECTED",
        "METADATA_REJECTED",
        "INVALID_BINARY",
        "WAITING_FOR_REVIEW",
    }
)


class ASCError(Exception):
    pass


class MissingCredentials(ASCError):
    pass


def token():
    key_id = os.environ.get("ASC_KEY_ID")
    issuer_id = os.environ.get("ASC_ISSUER_ID")
    key_path = os.environ.get("ASC_PRIVATE_KEY_PATH")
    if not all([key_id, issuer_id, key_path]):
        raise MissingCredentials(
            "Set ASC_KEY_ID, ASC_ISSUER_ID and ASC_PRIVATE_KEY_PATH to sync.\n"
            "No key yet? `asokit metadata check` prints copy-paste output that needs none."
        )
    try:
        import jwt
    except ImportError as error:
        raise ASCError("App Store Connect sync needs: pip install pyjwt cryptography") from error

    private_key = Path(key_path).expanduser().read_text()
    issued = int(time.time())
    return jwt.encode(
        {
            "iss": issuer_id,
            "iat": issued,
            "exp": issued + 20 * 60,
            "aud": "appstoreconnect-v1",
        },
        private_key,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )


RATE_LIMITED = 429
TRANSIENT_SERVER_ERRORS = frozenset({500, 502, 503, 504})
MAX_ATTEMPTS = 4


def _retryable(method, code):
    """Whether repeating this exact request is safe.

    The asymmetry is deliberate. A 429 means App Store Connect turned the
    request away *without processing it*, so repeating it cannot duplicate
    anything — and rate limits are the whole reason retry exists here, at a few
    hundred writes per run. A 5xx is ambiguous: the write may well have landed
    and only the response was lost, so repeating it is only safe when the
    request changes nothing, i.e. a GET.

    Not retrying a failed write costs little, because a run is re-runnable:
    `plan()` and `price_diff()` re-diff against live state and skip whatever
    already applied.
    """
    if code == RATE_LIMITED:
        return True
    return code in TRANSIENT_SERVER_ERRORS and method.upper() == "GET"


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
    """One request, retrying rate limits (any method) and 5xx (GET only)."""
    url = path if path.startswith("http") else f"{API}{path}"
    for attempt in range(MAX_ATTEMPTS):
        try:
            return _request(method, path, bearer, body)
        except urllib.error.HTTPError as error:
            if _retryable(method, error.code) and attempt < MAX_ATTEMPTS - 1:
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
        except (urllib.error.URLError, socket.timeout) as error:
            # Ordering matters: HTTPError subclasses URLError, so this clause
            # only ever sees a genuine transport failure — DNS, refused
            # connection, TLS, or a socket timeout. Deliberately NOT retried:
            # unlike a 429 (definitively unprocessed), a lost connection leaves
            # a write ambiguous, exactly like the 5xx case above. Wrapping it in
            # ASCError is what buys the operator the CLI's recovery guidance
            # instead of a traceback mid-apply.
            reason = getattr(error, "reason", error) or error
            raise ASCError(
                f"could not reach App Store Connect for {method} {url}: {reason}\n"
                "  This is a network/transport failure, not a rejection by "
                "Apple. The request may or may not have been processed — "
                "re-run to re-diff against live state."
            )


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
        # `links` can be present-but-null, not just missing: `.get("links", {})`
        # alone raises AttributeError on None, which is not an ASCError and so
        # escapes the CLI's handler as a traceback.
        url = (page.get("links") or {}).get("next")
    return items


def editable_version(app_id, bearer):
    versions = call("GET", f"/apps/{app_id}/appStoreVersions?limit=10", bearer)
    for version in versions.get("data", []):
        if version["attributes"]["appStoreState"] in EDITABLE_STATES:
            return version
    return None


def status(app_id, bearer):
    """What's editable and which locales already exist."""
    app = call("GET", f"/apps/{app_id}", bearer)["data"]
    version = editable_version(app_id, bearer)
    report = {
        "app": app["attributes"]["name"],
        "bundleId": app["attributes"]["bundleId"],
        "editableVersion": None,
        "versionLocales": [],
        "infoLocales": [],
    }
    if version:
        report["editableVersion"] = {
            "version": version["attributes"]["versionString"],
            "state": version["attributes"]["appStoreState"],
            "id": version["id"],
        }
        localizations = call_all(
            "GET",
            f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations?limit=200",
            bearer,
        )
        report["versionLocales"] = sorted(
            item["attributes"]["locale"] for item in localizations
        )
    else:
        recent = call("GET", f"/apps/{app_id}/appStoreVersions?limit=3", bearer)
        report["recentStates"] = [
            f"{v['attributes']['versionString']}={v['attributes']['appStoreState']}"
            for v in recent.get("data", [])
        ]

    infos = call("GET", f"/apps/{app_id}/appInfos", bearer)
    info = _editable_info(infos)
    localizations = call_all(
        "GET", f"/appInfos/{info['id']}/appInfoLocalizations?limit=200", bearer
    )
    report["infoLocales"] = sorted(item["attributes"]["locale"] for item in localizations)
    return report


def _editable_info(infos):
    return next(
        (
            info
            for info in infos["data"]
            if info["attributes"].get("appStoreState") in EDITABLE_STATES
        ),
        infos["data"][0],
    )


def push(app_id, metadata, bearer, apply=False, progress=None):
    """Write metadata per locale. Returns the list of planned or applied actions.

    With apply=False (the default) nothing is sent — the actions describe what
    a real run would do.

    `progress` is called with each action as it completes. A multi-locale push
    is a long sequence of live writes that can fail partway through, and an
    abort that reports nothing leaves the account half-updated with no record
    of which locales landed. Streaming each one out as it happens means the
    log is the record, whether the run finishes or not.
    """
    version = editable_version(app_id, bearer)
    if not version:
        raise ASCError(
            "No editable App Store version. Metadata is only writable while a version is in "
            "Prepare for Submission (or a rejected state). Create one in App Store Connect first."
        )

    infos = call("GET", f"/apps/{app_id}/appInfos", bearer)
    info = _editable_info(infos)
    info_locales = {
        item["attributes"]["locale"]: item["id"]
        for item in call_all(
            "GET", f"/appInfos/{info['id']}/appInfoLocalizations?limit=200", bearer
        )
    }
    version_locales = {
        item["attributes"]["locale"]: item["id"]
        for item in call_all(
            "GET",
            f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations?limit=200",
            bearer,
        )
    }

    actions = []

    def record(locale, resource, existing, attrs, parent):
        action = {
            "locale": locale,
            "resource": resource,
            "operation": "update" if existing else "create",
            "fields": sorted(attrs),
        }
        if apply:
            # Report what the write actually did, not what the pre-run snapshot
            # predicted: creating an appInfoLocalization makes App Store Connect
            # auto-create the paired appStoreVersionLocalization, so a planned
            # create becomes an adopt-and-patch mid-run.
            action["operation"] = _write(bearer, resource, existing, attrs, locale, parent)
        actions.append(action)
        if progress:
            progress(action)

    for locale, fields in sorted(metadata.items()):
        info_attrs = {k: v for k, v in fields.items() if k in APP_INFO_FIELDS}
        version_attrs = {k: v for k, v in fields.items() if k in VERSION_FIELDS}

        if info_attrs:
            record(
                locale,
                "appInfoLocalizations",
                info_locales.get(locale),
                info_attrs,
                ("appInfo", "appInfos", info["id"]),
            )

        if version_attrs:
            record(
                locale,
                "appStoreVersionLocalizations",
                version_locales.get(locale),
                version_attrs,
                ("appStoreVersion", "appStoreVersions", version["id"]),
            )

    return actions


PULL_FIELDS = (
    "name",
    "subtitle",
    "keywords",
    "description",
    "promotionalText",
    "whatsNew",
    "supportUrl",
    "marketingUrl",
    "privacyPolicyUrl",
)


def pull(app_id, bearer):
    """The live listing as {locale: {field: value}} — the shape check and push read.

    Capturing the current listing before overwriting it is the one step that
    gives a bad push somewhere to roll back to: `pull > baseline.json` and
    `push baseline.json` is the undo. Fields App Store Connect has never had a
    value for are omitted rather than emitted as empty, so `check` reports them
    as missing instead of the file asserting a blank.
    """
    version = editable_version(app_id, bearer)
    infos = call("GET", f"/apps/{app_id}/appInfos", bearer)
    info = _editable_info(infos)

    listing = {}

    def absorb(items):
        for item in items:
            attributes = item.get("attributes") or {}
            locale = attributes.get("locale")
            if not locale:
                continue
            fields = listing.setdefault(locale, {})
            for field in PULL_FIELDS:
                value = attributes.get(field)
                if value is not None:
                    fields[field] = value

    absorb(call_all("GET", f"/appInfos/{info['id']}/appInfoLocalizations?limit=200", bearer))
    if version:
        absorb(
            call_all(
                "GET",
                f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations?limit=200",
                bearer,
            )
        )

    # Stable field order so a re-pull diffs cleanly against the last baseline.
    return {
        locale: {field: fields[field] for field in PULL_FIELDS if field in fields}
        for locale, fields in sorted(listing.items())
    }


# Per-kind resource wiring: (localization type, relationship name, parent type).
_PRODUCT_RESOURCES = {
    "subscription": ("subscriptionLocalizations", "subscription", "subscriptions"),
    "iap": ("inAppPurchaseLocalizations", "inAppPurchaseV2", "inAppPurchases"),
    "group": ("subscriptionGroupLocalizations", "subscriptionGroup", "subscriptionGroups"),
}


def _parent_url(parent_type, parent_id):
    base = API_V2 if parent_type == "inAppPurchases" else API
    return f"{base}/{parent_type}/{parent_id}"


def _product_localizations(bearer, kind, parent_id):
    """Every locale on one product. Paged: a 21-locale app overruns page one.

    `call_all`, not `call`, is load-bearing. A locale past the first page reads
    as absent, so `plan()` emits createLocalization; the create fails with
    "already exists"; `_write` adopts and PATCHes — rewriting text on an
    APPROVED product and sending it back into review, silently.
    """
    resource_type, _, parent_type = _PRODUCT_RESOURCES[kind]
    listing = call_all(
        "GET", f"{_parent_url(parent_type, parent_id)}/{resource_type}", bearer
    )
    return {
        item["attributes"]["locale"]: {
            "id": item["id"],
            "name": item["attributes"].get("name"),
            "description": item["attributes"].get("description"),
            "customAppName": item["attributes"].get("customAppName"),
            "state": item["attributes"].get("state"),
        }
        for item in listing
    }


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


# Every App Store territory, read once per process. The list changes a few
# times a decade, and it is needed once per subscription both to judge
# availability and to write it — re-reading a 175-row page per product would
# add a request to every product in the catalogue for no new information.
_TERRITORY_CACHE = {}


def _all_territory_ids(bearer):
    """Sorted ids of every territory App Store Connect sells in."""
    if not _TERRITORY_CACHE.get("ids"):
        _TERRITORY_CACHE["ids"] = sorted(
            row["id"] for row in call_all("GET", "/territories?limit=200", bearer)
        )
    return _TERRITORY_CACHE["ids"]


def _subscription_availability(bearer, subscription_id):
    """{'allTerritories': bool} or None when availability has never been set.

    `availableInNewTerritories` is NOT "on sale everywhere". It means only
    "auto-enrol in territories Apple adds in FUTURE", and says nothing about
    the storefronts that exist today — those live in the `availableTerritories`
    relationship, which is separate, required, and 175 rows long. Echoing the
    attribute would report a subscription sold in twelve storefronts as fully
    available, and `plan()` would then call it converged forever.

    So the bool is computed honestly: true only when the product sells in every
    territory AND auto-enrols new ones.

    Returns {"allTerritories": bool}. `plan()` reads that one field rather than
    comparing the whole dict, so extra keys here would not break convergence —
    but nothing else wants them either, so the shape stays narrow.
    """
    try:
        response = call(
            "GET", f"/subscriptions/{subscription_id}/subscriptionAvailability", bearer
        )
    except ASCError:
        return None
    data = response.get("data")
    if not data:
        return None
    everywhere = bool(data.get("attributes", {}).get("availableInNewTerritories"))
    if everywhere:
        # Only worth the extra page when the answer could still be true.
        # `relationships/...` returns bare {type, id} linkage — cheaper than the
        # related resource, and paginated, so call_all is required: reading one
        # default-sized page would undercount and report False forever.
        covered = {
            row["id"]
            for row in call_all(
                "GET",
                f"/subscriptionAvailabilities/{data['id']}"
                "/relationships/availableTerritories?limit=200",
                bearer,
            )
            if row.get("id")
        }
        every = set(_all_territory_ids(bearer))
        everywhere = bool(every) and every.issubset(covered)
    return {"allTerritories": everywhere}


def available_territories(app_id, bearer):
    """Territory ids the app is actually on sale in.

    Researching a storefront the app is not sold in is pure waste — an hour of
    scoring for a market nobody can buy in — and the answer is one call away
    from credentials `doctor` already holds.

    Returns None when App Store Connect has no availability record to read,
    which is different from "available nowhere" and must not be reported as it.
    """
    response = call("GET", f"/apps/{app_id}/appAvailabilityV2", bearer)
    data = response.get("data")
    if not data:
        return None
    rows = call_all(
        "GET",
        f"{API_V2}/appAvailabilities/{data['id']}/territoryAvailabilities"
        # `include=territory` is load-bearing here too: without it the territory
        # relationship comes back as links only and every row is unidentifiable.
        "?include=territory&limit=200",
        bearer,
    )
    available = set()
    for row in rows:
        if not (row.get("attributes") or {}).get("available"):
            continue
        territory = ((row.get("relationships") or {}).get("territory") or {}).get("data") or {}
        if territory.get("id"):
            available.add(territory["id"])
    return available


def products_status(app_id, bearer):
    """Every product and the localizations each already has.

    Returns {"subscriptionGroups": [...], "inAppPurchases": [...]} where each
    product carries its ASC id, product id, state, and locale map — the same
    inventory `push_products` resolves against, so a dry run needs no writes.
    Subscriptions additionally carry `attributes`, `prices` and `availability`,
    which is everything `products.plan()` diffs against.
    """
    result = {"subscriptionGroups": [], "inAppPurchases": []}

    # Every listing here is paged, and this inventory now feeds a writer: a row
    # missing from a truncated page reads as "does not exist", which turns into
    # a create POST against something that is already live.
    groups = call_all("GET", f"/apps/{app_id}/subscriptionGroups", bearer)
    for group in groups:
        entry = {
            "id": group["id"],
            "referenceName": group["attributes"]["referenceName"],
            "localizations": _product_localizations(bearer, "group", group["id"]),
            "subscriptions": [],
        }
        subscriptions = call_all(
            "GET", f"/subscriptionGroups/{group['id']}/subscriptions", bearer
        )
        for subscription in subscriptions:
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
        result["subscriptionGroups"].append(entry)

    iaps = call_all("GET", f"/apps/{app_id}/inAppPurchasesV2", bearer)
    for iap in iaps:
        result["inAppPurchases"].append(
            {
                "id": iap["id"],
                "productId": iap["attributes"]["productId"],
                "state": iap["attributes"].get("state"),
                "localizations": _product_localizations(bearer, "iap", iap["id"]),
            }
        )
    return result


def _product_index(inventory):
    """Map file keys (product ids, `group:` names) to (kind, ASC id, locales)."""
    index = {}
    for group in inventory["subscriptionGroups"]:
        index[f"group:{group['referenceName']}"] = (
            "group",
            group["id"],
            group["localizations"],
        )
        for subscription in group["subscriptions"]:
            index[subscription["productId"]] = (
                "subscription",
                subscription["id"],
                subscription["localizations"],
            )
    for iap in inventory["inAppPurchases"]:
        index[iap["productId"]] = ("iap", iap["id"], iap["localizations"])
    return index


def push_products(app_id, products, bearer, apply=False):
    """Write product localizations per locale. Returns planned/applied actions.

    `products` maps product id (or `group:<referenceName>`) -> locale -> fields,
    the format `products.check()` validates. With apply=False nothing is sent.
    Unchanged locales are skipped, so a re-run of an applied file is a no-op —
    that matters here because any real write to an approved product sends it
    back into review.
    """
    index = _product_index(products_status(app_id, bearer))
    unknown = sorted(set(products) - set(index))
    if unknown:
        raise ASCError(
            "Product id(s) not found in App Store Connect: "
            + ", ".join(unknown)
            + "\nKnown: "
            + ", ".join(sorted(index))
        )

    actions = []
    for product_key, locales in sorted(products.items()):
        kind, parent_id, existing_locales = index[product_key]
        resource_type, relationship, parent_type = _PRODUCT_RESOURCES[kind]
        for locale, fields in sorted(locales.items()):
            existing = existing_locales.get(locale)
            if existing and all(existing.get(k) == v for k, v in fields.items()):
                actions.append(
                    {
                        "product": product_key,
                        "locale": locale,
                        "resource": resource_type,
                        "operation": "skip (unchanged)",
                        "fields": sorted(fields),
                    }
                )
                continue
            actions.append(
                {
                    "product": product_key,
                    "locale": locale,
                    "resource": resource_type,
                    "operation": "update" if existing else "create",
                    "fields": sorted(fields),
                }
            )
            if apply:
                _write(
                    bearer,
                    resource_type,
                    existing["id"] if existing else None,
                    fields,
                    locale,
                    (relationship, parent_type, parent_id),
                )
    return actions


def _write(bearer, resource_type, existing_id, attributes, locale, parent):
    """Create or update one localization. Returns what actually happened.

    The return value matters: the caller's create-vs-update prediction comes
    from a snapshot taken before the run, and a create can turn into an adopt
    partway through. Reporting the prediction would tell the user a locale was
    created when it was patched.
    """
    if existing_id:
        call(
            "PATCH",
            f"/{resource_type}/{existing_id}",
            bearer,
            {"data": {"type": resource_type, "id": existing_id, "attributes": attributes}},
        )
        return "updated"
    relationship, parent_type, parent_id = parent
    try:
        call(
            "POST",
            f"/{resource_type}",
            bearer,
            {
                "data": {
                    "type": resource_type,
                    "attributes": {**attributes, "locale": locale},
                    "relationships": {
                        relationship: {"data": {"type": parent_type, "id": parent_id}}
                    },
                }
            },
        )
        return "created"
    except ASCError as error:
        # Creating an appInfoLocalization makes App Store Connect auto-create
        # the matching appStoreVersionLocalization, so our own create can find
        # the locale already there. Adopt it and patch instead of aborting.
        if "already exists" not in str(error):
            raise
        listing = call_all(
            "GET", f"{_parent_url(parent_type, parent_id)}/{resource_type}", bearer
        )
        adopted = next(
            (
                item["id"]
                for item in listing
                if item["attributes"]["locale"] == locale
            ),
            None,
        )
        if adopted is None:
            raise
        call(
            "PATCH",
            f"/{resource_type}/{adopted}",
            bearer,
            {"data": {"type": resource_type, "id": adopted, "attributes": attributes}},
        )
        return "adopted"


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
        # Filter None before sorting: one price point row without a
        # customerPrice would mix None with str and raise TypeError here,
        # replacing the intended ASCError with a crash on the error path.
        available = sorted(
            {
                p["attributes"].get("customerPrice")
                for p in points
                if p.get("attributes")
            }
            - {None}
        )
        if not available:
            raise ASCError(
                f"no price points at all for territory {base_territory!r}, so "
                f"{customer_price} cannot be matched. The most likely cause is "
                "a mistyped baseTerritory — App Store Connect wants a "
                "three-letter code such as 'USA'."
            )
        raise ASCError(
            f"no {base_territory} price point at exactly {customer_price}. "
            f"Nearby tiers: {', '.join(available[:10])}"
        )
    # `include=territory` is load-bearing, not decoration: without it App Store
    # Connect returns the 170-odd equalized points but leaves
    # relationships.territory.data absent, so every row is skipped and only the
    # base territory resolves — which prices the product in one storefront and
    # silently leaves every other one unset. Verified live 2026-08-21.
    equalized = call_all(
        "GET",
        f"/subscriptionPricePoints/{match['id']}/equalizations"
        "?include=territory&limit=200",
        bearer,
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
            # `availableTerritories` is REQUIRED by App Store Connect on this
            # POST (Apple's own schema marks the relationship, and its `data`,
            # required). Sending only the attribute is rejected — which would
            # abort at the LAST write of every subscription, leaving each one
            # fully created and priced but never put on sale.
            #
            # The file cannot express a territory subset, so the list written is
            # always every territory; `allTerritories` drives the future-enrol
            # attribute. Read that as "all territories, including ones Apple
            # adds later": false still sells in all 175 today, it just stops
            # auto-enrolling new ones — which is why `products.check()` refuses
            # false outright rather than letting a run expand where a product is
            # sold. Surfaced as territoryCount so a dry run states the number
            # out loud before anyone approves it.
            territories = _all_territory_ids(bearer)
            if not territories:
                # `_all_territory_ids` deliberately does not cache an empty
                # result, so this means /v1/territories answered 200 with no
                # rows. POSTing an empty `availableTerritories` set would be a
                # delist-everywhere on a live product. Fail instead.
                #
                # This guard is reached on a dry run too, where nothing has
                # been written and nothing will be. So the message names only
                # the problem and what it would cost — recovery advice belongs
                # to the caller, which is the only side that knows whether any
                # write was attempted.
                raise ASCError(
                    "App Store Connect returned no territories, so the "
                    "availability set for "
                    f"{action['productId']} would be empty — which sells it in "
                    "no storefront at all, and on a product already on sale "
                    "would delist it everywhere."
                )
            action["territoryCount"] = len(territories)
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
                                },
                                "availableTerritories": {
                                    "data": [
                                        {"type": "territories", "id": territory}
                                        for territory in territories
                                    ]
                                },
                            },
                        }
                    },
                )
                action["applied"] = True

        executed.append(action)

    return executed
