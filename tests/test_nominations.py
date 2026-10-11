import contextlib
import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from asokit import cli, nominations
from tests.fakes import FakeNominationConnect, install

TODAY = datetime.date(2026, 10, 11)


def doc(**overrides):
    entry = {"name": "MoodSync — new product page", "type": "APP_ENHANCEMENTS", "description": "New header and search art.",
             "publishStartDate": "2026-11-16", "deviceFamilies": ["IPHONE", "IPAD"], "locales": ["en-US"]}
    entry.update(overrides)
    return {"nominations": [entry]}


class CheckTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(nominations.check(doc(), today=TODAY)[0], [])

    def test_limits_type_and_notice(self):
        problems, _ = nominations.check(doc(name="N" * 61, description="d" * 1001, type="APP_ENHANCEMENT",
                                            publishStartDate="2026-10-20"), today=TODAY)
        text = "\n".join(problems)
        for needle in ("60", "1000", "APP_ENHANCEMENT", "14 days"):
            self.assertIn(needle, text)

    def test_force_downgrades_notice_to_warning(self):
        problems, warnings = nominations.check(doc(publishStartDate="2026-10-20"), today=TODAY, force=True)
        self.assertEqual(problems, [])
        self.assertTrue(warnings)

    def test_malformed_date_is_a_problem_not_a_traceback(self):
        problems, _ = nominations.check(doc(publishStartDate="16/11/2026"), today=TODAY)
        self.assertTrue(any("publishStartDate" in p and "YYYY-MM-DD" in p for p in problems))

    def test_dates_become_datetimes(self):
        self.assertEqual(nominations.to_datetime("2026-11-16"), "2026-11-16T00:00:00Z")
        self.assertIsNone(nominations.to_datetime(None))


class PushTests(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeNominationConnect())

    def test_create_as_draft_then_no_change(self):
        nominations.push("6757342494", doc(), "t", apply=True, out=lambda line: None)
        (attrs,) = self.fake.nominations.values()
        self.assertEqual(attrs["state"], "DRAFT")
        self.assertEqual(attrs["publishStartDate"], "2026-11-16T00:00:00Z")
        before = len(self.fake.writes())
        actions = nominations.push("6757342494", doc(), "t", apply=True, out=lambda line: None)
        self.assertEqual([a["op"] for a in actions], ["unchanged"])
        self.assertEqual(len(self.fake.writes()), before)

    def test_list_carries_state_and_app_filters(self):
        nominations.push("1", doc(), "t", apply=False, out=lambda line: None)
        (get,) = [entry for entry in self.fake.log if entry[0] == "GET"]
        self.assertIn("filter[state]=DRAFT,SUBMITTED", get[1])
        self.assertIn("filter[relatedApps]=1", get[1])

    def test_draft_is_patched_and_submitted_one_is_skipped(self):
        nominations.push("1", doc(), "t", apply=True, out=lambda line: None)
        actions = nominations.push("1", doc(description="Changed."), "t", apply=True, out=lambda line: None)
        self.assertEqual(actions[0]["op"], "update")
        nid = next(iter(self.fake.nominations))
        self.fake.nominations[nid]["state"] = "SUBMITTED"
        actions = nominations.push("1", doc(description="Again."), "t", apply=True, out=lambda line: None)
        self.assertEqual(actions[0]["op"], "skip")

    def test_submit_only_the_named_nomination(self):
        two = doc()
        two["nominations"].append(dict(two["nominations"][0], name="Other"))
        nominations.push("1", two, "t", apply=True, submit_name="Other", out=lambda line: None)
        states = {a["name"]: a["state"] for a in self.fake.nominations.values()}
        self.assertEqual(states, {"MoodSync — new product page": "DRAFT", "Other": "SUBMITTED"})

    def test_dry_run_writes_nothing(self):
        nominations.push("1", doc(), "t", apply=False, out=lambda line: None)
        self.assertEqual(self.fake.writes(), [])


class NominationCommands(unittest.TestCase):
    def setUp(self):
        self.fake = install(self, FakeNominationConnect())
        self.root = Path(tempfile.mkdtemp())
        (self.root / "asokit.json").write_text(json.dumps({"app": {"appId": 1}}))
        start = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        (self.root / "nominations.json").write_text(json.dumps(doc(publishStartDate=start)), encoding="utf-8")
        patcher = mock.patch.object(cli, "_bearer", return_value="t")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.main(["--config", str(self.root / "asokit.json"), *argv])
        return buffer.getvalue()

    def test_check_ok(self):
        self.assertIn("ok", self.run_cli("nominations", "check"))

    def test_submit_requires_name_and_apply(self):
        for argv in (["--submit", "--apply"], ["--submit", "--name", "MoodSync — new product page"]):
            with self.assertRaises(SystemExit) as caught:
                self.run_cli("nominations", "push", *argv)
            self.assertIn("--submit needs --name", str(caught.exception))
        self.assertEqual(self.fake.log, [])

    def test_push_dry_run(self):
        self.assertIn("DRY RUN", self.run_cli("nominations", "push"))
        self.assertEqual(self.fake.writes(), [])


if __name__ == "__main__":
    unittest.main()
