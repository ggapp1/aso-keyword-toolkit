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
import time
import urllib.error
import urllib.request
from pathlib import Path

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


def call(method, path, bearer, body=None):
    url = path if path.startswith("http") else f"{API}{path}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode() if body else None, method=method
    )
    request.add_header("Authorization", f"Bearer {bearer}")
    if body:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode()
        try:
            errors = json.loads(detail).get("errors", [])
            detail = "\n".join(
                f"  {item.get('title')}: {item.get('detail')}" for item in errors
            )
        except json.JSONDecodeError:
            pass
        raise ASCError(f"App Store Connect returned {error.code} for {method} {url}\n{detail}")


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
        localizations = call(
            "GET", f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations", bearer
        )
        report["versionLocales"] = sorted(
            item["attributes"]["locale"] for item in localizations["data"]
        )
    else:
        recent = call("GET", f"/apps/{app_id}/appStoreVersions?limit=3", bearer)
        report["recentStates"] = [
            f"{v['attributes']['versionString']}={v['attributes']['appStoreState']}"
            for v in recent.get("data", [])
        ]

    infos = call("GET", f"/apps/{app_id}/appInfos", bearer)
    info = _editable_info(infos)
    localizations = call("GET", f"/appInfos/{info['id']}/appInfoLocalizations", bearer)
    report["infoLocales"] = sorted(item["attributes"]["locale"] for item in localizations["data"])
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


def push(app_id, metadata, bearer, apply=False):
    """Write metadata per locale. Returns the list of planned or applied actions.

    With apply=False (the default) nothing is sent — the actions describe what
    a real run would do.
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
        for item in call("GET", f"/appInfos/{info['id']}/appInfoLocalizations", bearer)["data"]
    }
    version_locales = {
        item["attributes"]["locale"]: item["id"]
        for item in call(
            "GET", f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations", bearer
        )["data"]
    }

    actions = []
    for locale, fields in sorted(metadata.items()):
        info_attrs = {k: v for k, v in fields.items() if k in APP_INFO_FIELDS}
        version_attrs = {k: v for k, v in fields.items() if k in VERSION_FIELDS}

        if info_attrs:
            existing = info_locales.get(locale)
            actions.append(
                {
                    "locale": locale,
                    "resource": "appInfoLocalizations",
                    "operation": "update" if existing else "create",
                    "fields": sorted(info_attrs),
                }
            )
            if apply:
                _write(
                    bearer,
                    "appInfoLocalizations",
                    existing,
                    info_attrs,
                    locale,
                    ("appInfo", "appInfos", info["id"]),
                )

        if version_attrs:
            existing = version_locales.get(locale)
            actions.append(
                {
                    "locale": locale,
                    "resource": "appStoreVersionLocalizations",
                    "operation": "update" if existing else "create",
                    "fields": sorted(version_attrs),
                }
            )
            if apply:
                _write(
                    bearer,
                    "appStoreVersionLocalizations",
                    existing,
                    version_attrs,
                    locale,
                    ("appStoreVersion", "appStoreVersions", version["id"]),
                )

    return actions


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
    resource_type, _, parent_type = _PRODUCT_RESOURCES[kind]
    listing = call("GET", f"{_parent_url(parent_type, parent_id)}/{resource_type}", bearer)
    return {
        item["attributes"]["locale"]: {
            "id": item["id"],
            "name": item["attributes"].get("name"),
            "description": item["attributes"].get("description"),
            "state": item["attributes"].get("state"),
        }
        for item in listing["data"]
    }


def products_status(app_id, bearer):
    """Every product and the localizations each already has.

    Returns {"subscriptionGroups": [...], "inAppPurchases": [...]} where each
    product carries its ASC id, product id, state, and locale map — the same
    inventory `push_products` resolves against, so a dry run needs no writes.
    """
    result = {"subscriptionGroups": [], "inAppPurchases": []}

    groups = call("GET", f"/apps/{app_id}/subscriptionGroups", bearer)
    for group in groups.get("data", []):
        entry = {
            "id": group["id"],
            "referenceName": group["attributes"]["referenceName"],
            "localizations": _product_localizations(bearer, "group", group["id"]),
            "subscriptions": [],
        }
        subscriptions = call(
            "GET", f"/subscriptionGroups/{group['id']}/subscriptions", bearer
        )
        for subscription in subscriptions.get("data", []):
            entry["subscriptions"].append(
                {
                    "id": subscription["id"],
                    "productId": subscription["attributes"]["productId"],
                    "state": subscription["attributes"].get("state"),
                    "localizations": _product_localizations(
                        bearer, "subscription", subscription["id"]
                    ),
                }
            )
        result["subscriptionGroups"].append(entry)

    iaps = call("GET", f"/apps/{app_id}/inAppPurchasesV2", bearer)
    for iap in iaps.get("data", []):
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
    if existing_id:
        call(
            "PATCH",
            f"/{resource_type}/{existing_id}",
            bearer,
            {"data": {"type": resource_type, "id": existing_id, "attributes": attributes}},
        )
        return
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
    except ASCError as error:
        # Creating an appInfoLocalization makes App Store Connect auto-create
        # the matching appStoreVersionLocalization, so our own create can find
        # the locale already there. Adopt it and patch instead of aborting.
        if "already exists" not in str(error):
            raise
        listing = call("GET", f"{_parent_url(parent_type, parent_id)}/{resource_type}", bearer)
        adopted = next(
            (
                item["id"]
                for item in listing["data"]
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
