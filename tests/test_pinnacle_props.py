"""pinnacle_props.py parsing, the pplog lookup, and ruletrack's props_beat_pinnacle (2 Nov 2026)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pinnacle_props as PR  # noqa: E402
import ruletrack  # noqa: E402

SPECIAL = {"id": 11, "type": "special", "parent": {"id": 5, "startTime": "2026-11-03T00:30:00Z",
           "participants": [{"name": "Indiana Pacers", "alignment": "home"},
                            {"name": "Atlanta Hawks", "alignment": "away"}]},
           "special": {"category": "Player Props", "description": "Pascal Siakam (Points)"},
           "participants": [{"id": 101, "name": "Over"}, {"id": 102, "name": "Under"}]}
MARKET = {"matchupId": 11, "period": 0, "status": "open", "type": "total",
          "prices": [{"participantId": 101, "points": 20.5, "price": -120},
                     {"participantId": 102, "points": 20.5, "price": 100}]}


class Parse(unittest.TestCase):
    def test_special_and_market(self):
        player, stat, sides, parent = PR.parse_special(SPECIAL, "basketball")
        self.assertEqual((player, stat, parent), ("Pascal Siakam", "Points", 5))
        rows = PR.props_of(MARKET, sides, player, stat)
        over = next(r for r in rows if r["over"])
        self.assertAlmostEqual(over["price"], 1.833, places=3)
        self.assertAlmostEqual(sum(r["p"] for r in rows), 1.0, places=3)
        self.assertGreater(over["p"], 0.5)

    def test_combo_and_unknown_stats(self):
        self.assertEqual(PR.stat_of("basketball", "Pts+Rebs+Asts"), "Points rebounds and assists")
        self.assertEqual(PR.stat_of("basketball", "3 Point FG"), "Three pointers made")
        self.assertIsNone(PR.stat_of("basketball", "Double Double"))
        self.assertEqual(PR.stat_of("american-football", "Receptions"), "Receiving receptions")


class Lookup(unittest.TestCase):
    def test_sharp_for_same_and_nearest_line(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "p.json"
            out.write_text(json.dumps({"events": {"5": {"sport": "basketball", "kickoff": 1000.0, "fid": 77,
                                       "props": [{"player": "Pascal Siakam", "stat": "Points", "line": 20.5,
                                                  "over": True, "price": 1.83, "p": 0.53}]}}}))
            was, PR.OUT = PR.OUT, out
            PR._IDX.clear()
            try:
                got = PR.sharp_for("basketball", "Pascal Siakam", "Points", 20.5, True, 1000.0, 77)
                self.assertTrue(got["same"])
                near = PR.sharp_for("basketball", "Pascal Siakam", "Points", 19.5, True, 1000.0)
                self.assertFalse(near["same"])
                self.assertIsNone(PR.sharp_for("basketball", "Pascal Siakam", "Points", 20.5, False, 1000.0))
            finally:
                PR.OUT = was
                PR._IDX.clear()


class Rule(unittest.TestCase):
    def setUp(self):
        ruletrack._hist_model = lambda: {}

    def r(self, price, p):
        snap = {"price": price, "chance": 0.5, "t": 0, "sharp": {"p": p, "price": 1.9, "line": 20.5, "same": True}}
        return {"event_id": 1, "fixture": "A v B", "kickoff": 0, "sport": "basketball", "team": "A",
                "player": "P", "stat": "Points", "line": 20.5, "over": True, "label": "",
                "first": dict(snap), "last": dict(snap), "k10": 5, "n10": 10, "result": None}

    def test_beats_and_control(self):
        q = ruletrack.qualifying([self.r(2.0, 0.53)])
        self.assertEqual(len(q.get("props_beat_pinnacle", [])), 1)
        q = ruletrack.qualifying([self.r(1.7, 0.53)])
        self.assertEqual(len(q.get("control_props_under_pinnacle", [])), 1)
        self.assertFalse(q.get("props_beat_pinnacle"))


if __name__ == "__main__":
    unittest.main()
