"""pplog: who started and for how long, recorded so football backtests can keep only starters."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pplog  # noqa: E402


def lineups(players):
    return {"home": {"players": players}, "away": {"players": []}}


class BackfillStarted(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "cache").mkdir()
        (self.tmp / "pplog").mkdir()
        self._root, self._dir = pplog.ROOT, pplog.DIR
        pplog.ROOT, pplog.DIR = self.tmp, self.tmp / "pplog"

    def tearDown(self):
        pplog.ROOT, pplog.DIR = self._root, self._dir

    def test_starter_bench_and_unsettled(self):
        (self.tmp / "cache" / "event_7_lineups.json").write_text(json.dumps(lineups([
            {"player": {"name": "Starter"}, "substitute": False, "statistics": {"minutesPlayed": 90}},
            {"player": {"name": "Bench"}, "substitute": True, "statistics": {"minutesPlayed": 22}},
        ])))
        rows = [{"event_id": 7, "player": "Starter", "sport": "football", "result": "win"},
                {"event_id": 7, "player": "Bench", "sport": "football", "result": "lose"},
                {"event_id": 7, "player": "Later", "sport": "football", "result": None}]
        f = pplog.DIR / "2026-10.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertEqual(pplog.backfill_started(), 2)
        got = {r["player"]: r for r in (json.loads(l) for l in f.read_text().splitlines())}
        self.assertEqual((got["Starter"]["started"], got["Starter"]["minutes"]), (True, 90))
        self.assertEqual((got["Bench"]["started"], got["Bench"]["minutes"]), (False, 22))
        self.assertNotIn("started", got["Later"])

    def test_no_cached_lineups_changes_nothing(self):
        f = pplog.DIR / "2026-10.jsonl"
        f.write_text(json.dumps({"event_id": 8, "player": "X", "sport": "football", "result": "win"}) + "\n")
        self.assertEqual(pplog.backfill_started(), 0)


if __name__ == "__main__":
    unittest.main()
