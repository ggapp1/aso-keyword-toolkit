"""Append-only record of every App Store Connect write asokit applied.

One JSON object per line in `asokit-ledger.jsonl`, next to `asokit.json`.
Commit it with the app: it is how you line up App Analytics (per custom
product page, per creative) with the date a change actually went live.
Dry runs never write to it.
"""
import json
import time
from pathlib import Path

DEFAULT_NAME = "asokit-ledger.jsonl"


class Ledger:
    def __init__(self, path, enabled=True):
        self.path = Path(path) if path else None
        self.enabled = bool(enabled and self.path is not None)

    def record(self, command, action, **fields):
        if not self.enabled:
            return
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "command": command, "action": action}
        entry.update({key: value for key, value in fields.items() if value is not None})
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def entries(self):
        if not self.path or not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def last(self, action, **match):
        hits = [e for e in self.entries() if e.get("action") == action and all(e.get(k) == v for k, v in match.items())]
        return hits[-1]["ts"] if hits else None


def for_config(config_path, apply):
    return Ledger(Path(config_path).resolve().parent / DEFAULT_NAME, enabled=apply)


NULL = Ledger(None, enabled=False)
