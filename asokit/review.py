# asokit/review.py
"""Review submissions that can only ever contain what asokit put in them.

An app has one open review submission per platform. If the user already has a
draft holding the app version, adding a custom product page to it and
submitting would ship the version too — so a draft is reused only when every
item in it is one asokit is submitting now; otherwise we stop.
"""
from . import asc

OPEN = ("READY_FOR_REVIEW", "WAITING_FOR_REVIEW", "IN_REVIEW", "UNRESOLVED_ISSUES")
IN_FLIGHT = frozenset({"WAITING_FOR_REVIEW", "IN_REVIEW", "UNRESOLVED_ISSUES"})
ITEM_RELATIONSHIPS = ("appStoreVersion", "appCustomProductPageVersion", "appAssetLibraryImage", "appAssetLibraryVideo",
                      "appEvent", "appStoreVersionExperiment", "appStoreVersionExperimentV2", "inAppPurchaseVersion",
                      "subscriptionVersion", "subscriptionGroupVersion", "backgroundAssetVersion")


class SubmissionBlocked(asc.ASCError):
    pass


def _items(submission_id, bearer):
    include = ",".join(ITEM_RELATIONSHIPS)
    rows = asc.call_all("GET", f"/reviewSubmissions/{submission_id}/items?include={include}&limit=200", bearer)
    found = []
    for row in rows:
        key = ("unknown", "unknown", row["id"])
        for name in ITEM_RELATIONSHIPS:
            data = ((row.get("relationships") or {}).get(name) or {}).get("data")
            if data:
                key = (name, data["type"], data["id"])
                break
        found.append(key)
    return found


def _open_drafts(app_id, bearer):
    """READY_FOR_REVIEW drafts; raises SubmissionBlocked if a submission is in flight."""
    states = ",".join(OPEN)
    open_rows = asc.call_all("GET", f"/reviewSubmissions?filter[app]={app_id}&filter[platform]=IOS&filter[state]={states}&limit=200", bearer)
    flying = [r for r in open_rows if (r.get("attributes") or {}).get("state") in IN_FLIGHT]
    if flying:
        raise SubmissionBlocked(f"a review submission is in flight ({flying[0]['id']}, {flying[0]['attributes']['state']}) — "
                                "wait for it to finish, then re-run")
    return [r for r in open_rows if (r.get("attributes") or {}).get("state") == "READY_FOR_REVIEW"]


def preflight(app_id, bearer, allowed_relationships):
    """Read-only early guard, run before any upload.

    Raises SubmissionBlocked when a submission is in flight or the open draft
    holds an item whose relationship the caller could never plan (e.g. the app
    version). Returns the draft id, or None. submit() still runs the exact
    item-by-item check.
    """
    drafts = _open_drafts(app_id, bearer)
    if not drafts:
        return None
    submission = drafts[0]["id"]
    allowed = set(allowed_relationships)
    foreign = [i for i in _items(submission, bearer) if i[0] not in allowed]
    if foreign:
        listed = ", ".join(f"{rel} {rid}" for rel, _, rid in foreign)
        raise SubmissionBlocked(f"draft submission {submission} already holds other items ({listed}). "
                                "Submit or clear it in App Store Connect first — asokit will not submit them for you.")
    return submission


def submit(app_id, items, bearer, apply, ledger=None, command=""):
    planned = list(dict.fromkeys(tuple(i) for i in items))
    if not planned:
        raise SubmissionBlocked("nothing to submit")
    drafts = _open_drafts(app_id, bearer)
    submission, existing = None, []
    if drafts:
        submission = drafts[0]["id"]
        existing = _items(submission, bearer)
        foreign = [i for i in existing if i not in planned]
        if foreign:
            listed = ", ".join(f"{rel} {rid}" for rel, _, rid in foreign)
            raise SubmissionBlocked(f"draft submission {submission} already holds other items ({listed}). "
                                    "Submit or clear it in App Store Connect first — asokit will not submit them for you.")
    add = [i for i in planned if i not in existing]
    result = {"submission": submission or "(new)", "add": add, "existing": existing, "submitted": False}
    if not apply:
        return result
    if submission is None:
        submission = asc.call("POST", "/reviewSubmissions", bearer, {"data": {
            "type": "reviewSubmissions", "attributes": {"platform": "IOS"},
            "relationships": {"app": {"data": {"type": "apps", "id": str(app_id)}}},
        }})["data"]["id"]
        result["submission"] = submission
    for relationship, resource_type, resource_id in add:
        asc.call("POST", "/reviewSubmissionItems", bearer, {"data": {
            "type": "reviewSubmissionItems",
            "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission}},
                relationship: {"data": {"type": resource_type, "id": resource_id}},
            },
        }})
    final = _items(submission, bearer)
    if sorted(final) != sorted(planned):
        raise SubmissionBlocked(f"submission {submission} holds {final}, expected {planned} — NOT submitted")
    asc.call("PATCH", f"/reviewSubmissions/{submission}", bearer, {"data": {
        "type": "reviewSubmissions", "id": submission, "attributes": {"submitted": True},
    }})
    result["submitted"] = True
    if ledger:
        ledger.record(command, "submit", submission_id=submission, items=[f"{rel}:{rid}" for rel, _, rid in planned])
    return result
