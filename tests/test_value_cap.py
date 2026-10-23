"""Tests for value_cap.py and the per-player cap in pplog.py.

    python -B -m unittest tests.test_value_cap
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import value_cap as V  # noqa: E402


class TestCap(unittest.TestCase):
    def test_one_per_player_in_order(self):
        legs = [{"player": "A", "i": 0}, {"player": "B", "i": 1}, {"player": "A", "i": 2},
                {"player": None, "team": "X", "i": 3}, {"player": None, "team": "X", "i": 4}, {"player": "B", "i": 5}]
        self.assertEqual([l["i"] for l in V.cap_per_player(legs)], [0, 1, 3, 4])

    def test_cap_two_and_no_cap(self):
        legs = [{"player": "A", "i": i} for i in range(4)]
        self.assertEqual([l["i"] for l in V.cap_per_player(legs, 2)], [0, 1])
        self.assertEqual(len(V.cap_per_player(legs, None)), 4)

    def test_default_is_the_backtested_cap(self):
        self.assertEqual(V.MAX_PER_PLAYER, 1)

    def test_residual_corr(self):
        a = {"p": 0.5, "win": True}
        b = {"p": 0.5, "win": False}
        n, m, _ = V.residual_corr([(a, a), (b, b)])
        self.assertEqual(n, 2)
        self.assertAlmostEqual(m, 1.0)
        n, m, _ = V.residual_corr([(a, b), (b, a)])
        self.assertAlmostEqual(m, -1.0)

    def test_ranks_by_score(self):
        legs = [{"event": 1, "player": "A", "p": 0.6, "win": True, "team": "X"},
                {"event": 1, "player": "A", "p": 0.8, "win": False, "team": "X"},
                {"event": 1, "player": None, "p": 0.7, "win": True, "team": "X"}]
        r = V.ranks(legs)
        self.assertEqual(sorted((l["p"], l["rank"]) for l in r), [(0.6, 2), (0.8, 1)])

    def test_cap_table_keeps_the_biggest_edge(self):
        bets = [{"event": 1, "player": "A", "p": 0.6, "price": 2.0, "edge": 0.2, "win": True},
                {"event": 1, "player": "A", "p": 0.6, "price": 2.0, "edge": 0.1, "win": False},
                {"event": 2, "player": "B", "p": 0.6, "price": 3.0, "edge": 0.3, "win": False}]
        rows = {r[0]: r for r in V.cap_table(bets, caps=(1, None), n_boot=50)}
        self.assertEqual(rows["1"][1:3], (2, 1))          # A's 0.2 edge (won) and B
        self.assertAlmostEqual(rows["1"][5], 0.0)          # +1 -1
        self.assertEqual(rows["none"][1], 3)
        self.assertAlmostEqual(rows["none"][5], -1.0)


class TestPplogCap(unittest.TestCase):
    def test_cap_value_keeps_each_players_biggest_edge_per_game(self):
        import pplog
        rows = [{"event_id": 1, "player": "A", "first": {"edge": 0.1}},
                {"event_id": 1, "player": "A", "first": {"edge": 0.3}},
                {"event_id": 2, "player": "A", "first": {"edge": 0.05}},
                {"event_id": 1, "player": "B", "first": {"edge": 0.2}}]
        got = pplog.cap_value(rows)
        self.assertEqual(sorted((r["event_id"], r["player"], r["first"]["edge"]) for r in got),
                         [(1, "A", 0.3), (1, "B", 0.2), (2, "A", 0.05)])

    def test_cap_value_on_the_last_sighting(self):
        import pplog
        rows = [{"event_id": 1, "player": "A", "first": {"edge": 0.3}, "last": {"edge": 0.1}},
                {"event_id": 1, "player": "A", "first": {"edge": 0.1}, "last": {"edge": 0.4}}]
        self.assertEqual(pplog.cap_value(rows, "last")[0]["last"]["edge"], 0.4)


if __name__ == "__main__":
    unittest.main()
