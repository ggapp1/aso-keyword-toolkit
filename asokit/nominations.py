"""Featuring nominations from `nominations.json`, created as drafts.

  {"nominations": [{"name", "type", "description", "publishStartDate": "YYYY-MM-DD",
                    "publishEndDate"?, "deviceFamilies"?, "locales"?, "notes"?,
                    "relatedApps"? (default: the config's appId), "supplementalMaterialsUris"?,
                    "hasInAppEvents"?, "launchInSelectMarketsFirst"?, "preOrderEnabled"?}]}

Nothing is submitted unless `push(..., submit_name=NAME)` names it.
"""
import datetime
import json
import re
from pathlib import Path

from . import asc
from .ledger import NULL

TYPES = frozenset({"APP_LAUNCH", "APP_ENHANCEMENTS", "NEW_CONTENT"})
FAMILIES = frozenset({"IPHONE", "IPAD", "APPLE_TV", "APPLE_WATCH", "MAC", "VISION"})
NAME_MAX, DESCRIPTION_MAX, NOTICE_DAYS = 60, 1000, 14
ATTRIBUTES = ("description", "type", "publishStartDate", "publishEndDate", "deviceFamilies", "locales", "notes",
              "hasInAppEvents", "launchInSelectMarketsFirst", "preOrderEnabled", "supplementalMaterialsUris")
DATES = ("publishStartDate", "publishEndDate")
LISTS = ("deviceFamilies", "locales", "supplementalMaterialsUris")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def to_datetime(value):
    if not value:
        return None
    return f"{value}T00:00:00Z" if len(value) == 10 else value


def _date(value):
    return value[:10] if value else None


def _parse_date(value):
    """A `YYYY-MM-DD` string as a date; anything else (incl. datetimes) is None."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def related_apps_problem(entry, app_id):
    """Why `relatedApps` (when present) is unusable, or None. It must be a list of ids that includes `app_id`."""
    if "relatedApps" not in entry:
        return None
    related = entry["relatedApps"]
    if not isinstance(related, list) or not related or not all(isinstance(a, (str, int)) and not isinstance(a, bool) for a in related):
        return "relatedApps must be a non-empty list of app ids"
    if app_id is not None and str(app_id) not in {str(a) for a in related}:
        return f"relatedApps must include this app ({app_id})"
    return None


def check(doc, today=None, force=False, app_id=None):
    today = today or datetime.date.today()
    problems, warnings = [], []
    names = [n.get("name", "") for n in doc.get("nominations", [])]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"nomination name '{name}' appears more than once")
    for entry in doc.get("nominations", []):
        name = entry.get("name", "")
        for field in ("name", "type", "description", "publishStartDate"):
            if not entry.get(field):
                problems.append(f"'{name}': {field} is required")
        if len(name) > NAME_MAX:
            problems.append(f"'{name}': name is {len(name)} characters, limit {NAME_MAX}")
        if len(entry.get("description", "")) > DESCRIPTION_MAX:
            problems.append(f"'{name}': description exceeds {DESCRIPTION_MAX} characters")
        if entry.get("type") and entry["type"] not in TYPES:
            problems.append(f"'{name}': type {entry['type']} is not one of {', '.join(sorted(TYPES))}")
        bad = set(entry.get("deviceFamilies", [])) - FAMILIES
        if bad:
            problems.append(f"'{name}': unknown device families {sorted(bad)}")
        related = related_apps_problem(entry, app_id)
        if related:
            problems.append(f"'{name}': {related}")
        for field in DATES:
            if entry.get(field) and _parse_date(entry[field]) is None:
                problems.append(f"'{name}': {field} '{entry[field]}' is not a YYYY-MM-DD date")
        start = _parse_date(entry["publishStartDate"]) if entry.get("publishStartDate") else None
        if start:
            days = (start - today).days
            if days < NOTICE_DAYS:
                message = f"'{name}': publishStartDate is {days} days away — Apple needs at least {NOTICE_DAYS} days' notice"
                (warnings if force else problems).append(message + (" (--force)" if force else ""))
    return problems, warnings


def _attributes(entry):
    attrs = {key: entry[key] for key in ATTRIBUTES if entry.get(key) is not None}
    for key in DATES:
        if key in attrs:
            attrs[key] = to_datetime(attrs[key])
    return attrs


def _normalised(key, value):
    """Comparable form: empty ([] / "" / None) is absent, lists are unordered, dates compare by day."""
    if value in (None, "", []):
        return None
    if key in DATES:
        return _date(value)
    if key in LISTS and isinstance(value, list):
        return sorted(value, key=str)
    return value


def _changes(entry, live):
    wanted = _attributes(entry)
    changed = {}
    for key, value in wanted.items():
        if _normalised(key, value) != _normalised(key, live.get(key)):
            changed[key] = value
    return changed


def push(app_id, doc, bearer, apply, submit_name=None, ledger=NULL, out=print):
    """Converge drafts to the file, then (last) submit the one named nomination."""
    rows = asc.call_all("GET", f"/nominations?filter[state]=DRAFT,SUBMITTED&filter[relatedApps]={app_id}&limit=200", bearer)
    live = {}
    for row in rows:
        name = row["attributes"].get("name")
        if name in live:
            raise asc.ASCError(f"two live nominations are named '{name}' — rename or remove one in App Store Connect first")
        live[name] = row
    entries = doc.get("nominations", [])
    names = [entry["name"] for entry in entries]
    if submit_name and submit_name not in names:
        raise asc.ASCError(f"--name '{submit_name}' is not in the nominations file")
    for entry in entries:
        problem = related_apps_problem(entry, app_id)
        if problem:
            raise asc.ASCError(f"'{entry['name']}': {problem}")
    actions = []
    ids, submittable = {}, set()
    for entry in entries:
        name = entry["name"]
        row = live.get(name)
        related = [str(a) for a in entry.get("relatedApps", [app_id])]
        if row is None:
            actions.append({"name": name, "op": "create"})
            out(f"  create   {name} (draft)")
            submittable.add(name)
            if apply:
                created = asc.call("POST", "/nominations", bearer, {"data": {
                    "type": "nominations",
                    "attributes": {"name": name, "submitted": False, **_attributes(entry)},
                    "relationships": {"relatedApps": {"data": [{"type": "apps", "id": a} for a in related]}},
                }})["data"]
                ledger.record("nominations push", "create", nomination_id=created["id"], name=name)
                ids[name] = created["id"]
        elif row["attributes"].get("state") == "SUBMITTED":
            actions.append({"name": name, "op": "skip"})
            out(f"  skip     {name} (already submitted)")
        else:
            ids[name] = row["id"]
            submittable.add(name)
            changes = _changes(entry, row["attributes"])
            actions.append({"name": name, "op": "update" if changes else "unchanged", "changes": sorted(changes)})
            out(f"  {'update' if changes else 'ok':<8} {name}" + (f": {', '.join(sorted(changes))}" if changes else ""))
            if apply and changes:
                asc.call("PATCH", f"/nominations/{row['id']}", bearer, {"data": {"type": "nominations", "id": row["id"], "attributes": changes}})
                ledger.record("nominations push", "update", nomination_id=row["id"], name=name, changed=sorted(changes))
    if submit_name in submittable:
        actions.append({"name": submit_name, "op": "submit"})
        out(f"  submit   {submit_name}")
        if apply:
            nid = ids[submit_name]
            asc.call("PATCH", f"/nominations/{nid}", bearer, {"data": {"type": "nominations", "id": nid, "attributes": {"submitted": True}}})
            ledger.record("nominations push", "submit", nomination_id=nid, name=submit_name)
    return actions
