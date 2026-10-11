import json
import tempfile
import unittest
from pathlib import Path

from asokit import ledger


class LedgerTests(unittest.TestCase):
    def test_records_one_line_per_write_and_drops_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = ledger.Ledger(Path(tmp) / "asokit-ledger.jsonl")
            book.record("cpp push", "add_keywords", page_name="BPD", locale="en-US", keywords_added=["bpd"], asset_sha=None)
            book.record("cpp publish", "publish", page_id="p1")
            lines = (Path(tmp) / "asokit-ledger.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            self.assertEqual(first["action"], "add_keywords")
            self.assertNotIn("asset_sha", first)
            self.assertIn("ts", first)

    def test_disabled_ledger_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "asokit.json"
            config.write_text("{}")
            book = ledger.for_config(config, apply=False)
            book.record("cpp push", "create_page", page_name="X")
            self.assertFalse((Path(tmp) / "asokit-ledger.jsonl").exists())
            ledger.NULL.record("x", "y")

    def test_last_returns_latest_matching_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = ledger.Ledger(Path(tmp) / "l.jsonl")
            book.record("cpp publish", "publish", page_id="p1")
            book.record("cpp publish", "publish", page_id="p2")
            self.assertIsNotNone(book.last("publish", page_id="p1"))
            self.assertIsNone(book.last("submit", page_id="p1"))


if __name__ == "__main__":
    unittest.main()
