"""pairs.py: correlated same-game legs (2 Nov 2026)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pairs  # noqa: E402


def row(player, stat, line, over, price, team="A", eid=1, sport="basketball"):
    s = {"price": price}
    return {"event_id": eid, "fixture": "A v B", "sport": sport, "team": team, "player": player, "stat": stat,
            "line": line, "over": over, "label": "", "first": s, "last": s}


class Joint(unittest.TestCase):
    def test_joint_identities(self):
        pa, pb, L = 0.5, 0.4, 1.2
        oo = pairs.joint(pa, pb, True, True, L)
        self.assertAlmostEqual(oo, 0.24)
        self.assertAlmostEqual(oo + pairs.joint(pa, pb, True, False, L), pa)
        total = sum(pairs.joint(pa, pb, x, y, L) for x in (True, False) for y in (True, False))
        self.assertAlmostEqual(total, 1.0)

    def test_lifts(self):
        a, b = row("P", "Points", 19.5, True, 1.9), row("P", "Three pointers made", 1.5, True, 1.9)
        self.assertEqual(pairs.lift("basketball", a, b), 1.27)
        c = row("Q", "Points", 19.5, True, 1.9, team="B")
        self.assertEqual(pairs.lift("basketball", a, c), 1.0)


class Scan(unittest.TestCase):
    def test_finds_linked_pair_and_prices_it(self):
        rows = [row("P", "Points", 19.5, True, 1.9), row("P", "Points", 19.5, False, 1.9),
                row("P", "Three pointers made", 1.5, True, 1.9), row("P", "Three pointers made", 1.5, False, 1.9),
                row("Q", "Rebounds", 7.5, True, 1.9, team="B"), row("Q", "Rebounds", 7.5, False, 1.9, team="B")]
        got = pairs.scan(rows)
        top = got[0]
        self.assertEqual({top["a"]["stat"], top["b"]["stat"]}, {"Points", "Three pointers made"})
        self.assertAlmostEqual(top["p"], 0.25 * 1.27, places=3)
        self.assertLess(top["fair"], top["multiplied"])
        self.assertFalse(any(x["a"]["player"] != x["b"]["player"] and x["a"]["team"] != x["b"]["team"] for x in got))


if __name__ == "__main__":
    unittest.main()
