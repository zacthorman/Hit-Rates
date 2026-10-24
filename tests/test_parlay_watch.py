"""parlay_watch.py: which tickets count, split against one side, the fixed decision.

    python -B -m unittest tests.test_parlay_watch

Synthetic records only; the watch file is written to a temporary folder.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import parlay_watch as W  # noqa: E402

DAY = 86400


def leg(team, player, result="win", ts=None, hits=14, total=20):
    return {"event_id": 7, "kickoff": ts or W.START + DAY, "team": team, "player": player, "stat": "Shots",
            "threshold": 1.0, "line": 0.5, "hits": hits, "total": total, "result": result}


def ticket(teams, result="win", snap=None, fair=4.0, results=None, ts=None):
    results = results or [result] * len(teams)
    return {"category": "Pick: parlay", "sport": "football", "snapshot_at": snap or W.START + 3600,
            "fair": fair, "result": result,
            "legs": [leg(t, f"p{i}{t}", r, ts) for i, (t, r) in enumerate(zip(teams, results))]}


class Tickets(unittest.TestCase):

    def test_shape(self):
        self.assertEqual(W.shape([{"team": "A"}, {"team": "A"}]), "one side")
        self.assertEqual(W.shape([{"team": "A"}, {"team": "B"}]), "split")

    def test_only_from_start_and_first_sighting_decides(self):
        early = ticket(["A", "A", "A", "A"], snap=W.START - 3600)
        again = dict(early, snapshot_at=W.START + 3600)          # the same ticket seen again later
        new = ticket(["A", "A", "B", "B"])
        rows, left = W.tickets([early, again, new])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["shape"], "split")
        self.assertEqual(left["before start"], 1)

    def test_void_and_open_left_out(self):
        void = ticket(["A", "A", "B", "B"], result="win", results=["win", "void", "win", "win"])
        void["legs"][0]["player"] = "v"
        open_ = ticket(["A", "B", "B", "B"], result=None, results=["win", None, "win", "win"])
        rows, left = W.tickets([void, open_])
        self.assertEqual(rows, [])
        self.assertEqual(left["void leg"], 1)
        self.assertEqual(left["open"], 1)

    def test_said_and_multiplied(self):
        rows, _ = W.tickets([ticket(["A", "A", "B", "B"], fair=5.0)])
        self.assertAlmostEqual(rows[0]["said"], 0.2)
        self.assertAlmostEqual(rows[0]["multiplied"], 0.7 ** 4)


class Decision(unittest.TestCase):

    def items(self, n, won_every):
        out = []
        for i in range(n):
            t = ticket(["A", "A", "B", "B"], result="win" if i % won_every == 0 else "lose",
                       fair=1 / 0.3, ts=W.START + (i % 60 + 1) * DAY)
            for j, l in enumerate(t["legs"]):
                l["player"] = f"p{i}-{j}"
                # legs whose product is well below the stated 30%
                l["hits"], l["total"] = 12, 20
            out.append(t)
        return out

    def test_waits_until_enough(self):
        s = W.summary(self.items(50, 10))
        self.assertTrue(s["decision"].startswith("waiting: 50 of 300"))

    def test_holds_when_split_lands_well_below(self):
        s = W.summary(self.items(400, 10))      # 10% landed against 30% said
        self.assertEqual(s["split"]["tickets"], 400)
        self.assertLess(s["split"]["landed_over_said_95"][1], 1)
        self.assertTrue(s["decision"].startswith("holds"))

    def test_does_not_hold_when_on_price(self):
        items = self.items(400, 3)               # about a third landed against 30% said
        s = W.summary(items)
        self.assertTrue(s["decision"].startswith("does not hold"))

    def test_update_writes_where_told(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.json"
            s = W.update(self.items(5, 2), path=p)
            self.assertEqual(json.loads(p.read_text())["split"]["tickets"], s["split"]["tickets"])
        self.assertIn("waiting", W.text(s))


class SettleHook(unittest.TestCase):

    def test_settle_writes_the_watch_beside_its_store(self):
        """besttrack.settle with STORE in a temporary folder writes the
        watch there and leaves the tracked parlay_watch.json alone, with or
        without tests/conftest.py (test_tracked_files runs without it)."""
        import contextlib
        import io
        import besttrack
        real = W.HERE / W.OUT_NAME
        before = real.read_bytes() if real.exists() else None
        saved = besttrack.STORE, besttrack.LEAD_LOG
        with tempfile.TemporaryDirectory() as d:
            try:
                besttrack.STORE = Path(d) / "best_bets.json"
                besttrack.LEAD_LOG = Path(d) / "lead_log.json"
                besttrack.save([])
                with contextlib.redirect_stdout(io.StringIO()):
                    besttrack.settle()          # nothing due, so nothing is fetched
                self.assertTrue((Path(d) / W.OUT_NAME).exists())
            finally:
                besttrack.STORE, besttrack.LEAD_LOG = saved
        self.assertEqual(real.read_bytes() if real.exists() else None, before)


if __name__ == "__main__":
    unittest.main()
