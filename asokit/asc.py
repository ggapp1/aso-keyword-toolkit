"""App Store Connect metadata sync.

Localized metadata lives in two different resources, which is the detail that
makes hand-rolling this annoying:

  appInfoLocalizations          name, subtitle, privacyPolicyUrl
  appStoreVersionLocalizations  keywords, description, promotionalText, whatsNew

Both are per-locale and both are only writable while a version sits in an
editable state. `status()` reports whether that's true before you try.

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
