"""slipkit.py staking and pinnacle_props.game_lines (2 Nov 2026)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pinnacle_props as PR  # noqa: E402
import slipkit  # noqa: E402


def leg(eid, price, p, player="P"):
    sh = {"p": p, "same": True, "price": 1.9, "line": 9.5}
    snap = {"price": price, "sharp": sh}
    return {"event_id": eid, "player": player, "stat": "Points", "line": 9.5, "over": True, "label": "Over 9.5",
            "fixture": "A v B", "kickoff": 0, "first": snap, "last": snap}


class Staking(unittest.TestCase):
    def test_kelly(self):
        self.assertAlmostEqual(slipkit.kelly(0.55, 2.0), 0.10)
        self.assertEqual(slipkit.kelly(0.45, 2.0), 0.0)

    def test_edge_and_plan(self):
        rows = [leg(1, 2.1, 0.52, "A"), leg(2, 2.05, 0.53, "B"), leg(2, 1.9, 0.50, "C"), leg(3, 1.8, 0.5, "D")]
        edged = [dict(r, _p=slipkit.edge_of(r)[0], _edge=slipkit.edge_of(r)[1], _price=r["last"]["price"])
                 for r in rows if slipkit.edge_of(r)[1] >= slipkit.MIN_EDGE]
        self.assertEqual([r["player"] for r in edged], ["A", "B"])
        p = slipkit.plan(edged, [], 100)
        self.assertEqual(len(p["singles"]), 2)
        self.assertTrue(all(0 < s <= 2.0 for _, s in p["singles"]))
        self.assertEqual(len(p["doubles"]), 1)
        a, b, price, e, s = p["doubles"][0]
        self.assertAlmostEqual(e, (1 + 2.1 * .52 - 1) * (1 + 2.05 * .53 - 1) - 1 + 0, places=6)
        self.assertLessEqual(p["total"], 8.0)

    def test_no_same_game_doubles(self):
        rows = [leg(1, 2.1, 0.52, "A"), leg(1, 2.05, 0.53, "B")]
        edged = [dict(r, _p=.52, _edge=.09, _price=r["last"]["price"]) for r in rows]
        self.assertEqual(slipkit.plan(edged, [], 100)["doubles"], [])


class GameLines(unittest.TestCase):
    def test_main_lines_picked_nearest_evens(self):
        mk = [{"period": 0, "type": "spread", "prices": [{"designation": "home", "points": -5.5, "price": -110},
                                                          {"designation": "away", "points": 5.5, "price": -110}]},
              {"period": 0, "type": "spread", "prices": [{"designation": "home", "points": -9.5, "price": 180},
                                                          {"designation": "away", "points": 9.5, "price": -220}]},
              {"period": 0, "type": "total", "prices": [{"designation": "over", "points": 228.5, "price": -105},
                                                         {"designation": "under", "points": 228.5, "price": -115}]},
              {"period": 0, "type": "moneyline", "prices": [{"designation": "home", "price": -220},
                                                             {"designation": "away", "price": 180}]}]
        g = PR.game_lines(mk)
        self.assertEqual(g["spread"], -5.5)
        self.assertEqual(g["total"], 228.5)
        self.assertGreater(g["p_home"], 0.6)


if __name__ == "__main__":
    unittest.main()
