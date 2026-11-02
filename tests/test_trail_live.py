"""trail_live.py: direct opponents, matchup multipliers and the trail history.
A made-up cache and fixture; nothing is fetched."""
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import trail_live as tl  # noqa: E402

# Two sides, four outfield starters each. Home: a right-back, a holding
# midfielder, a winger, a striker. Away: the mirror. Positions are each
# team's own frame (x towards the opponent's goal), so the away right winger
# (y 20) stands opposite the home right-back (y 80 mirrored = 20).
HOME = [(1, "Hal Back", "D", 30, 20), (2, "Hal Mid", "M", 50, 50), (3, "Hal Wing", "M", 70, 80), (4, "Hal Nine", "F", 80, 50)]
AWAY = [(11, "Ari Back", "D", 30, 50), (12, "Ari Mid", "M", 50, 50), (13, "Ari Wing", "M", 70, 80), (14, "Ari Nine", "F", 80, 50)]


def player(pid, name, pos, stats, sub=False):
    return {"player": {"id": pid, "name": name, "position": pos}, "substitute": sub,
            "statistics": dict({"minutesPlayed": 90}, **stats)}


class TrailLive(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (tl.CACHE, tl.FIT)
        tl.CACHE = self.tmp
        tl._load.cache_clear()
        tl.fit.cache_clear()
        fit = {"stats": {
            "tackles": {"driver": "dribbles", "coef": 0.07, "centre": 0.0, "quantiles": [0.2, 0.5, 1.0, 2.0, 3.2]},
            "shots": {"driver": "interc", "coef": 0.06, "centre": 0.0, "quantiles": [0.1, 0.3, 0.6, 1.0, 1.4],
                      "roles": {"player": ["D", "M"], "opponent": ["F", "M"]}},
            "fouled": {"driver": "tackles", "coef": 0.07, "centre": 0.0, "quantiles": [0.4, 0.8, 1.3, 1.9, 2.5],
                       "roles": {"player": ["D", "M"], "opponent": ["F", "M"]}},
            "fouls": {"driver": "fouled", "coef": 0.03, "centre": 0.0, "quantiles": [0.3, 0.6, 1.0, 1.5, 2.1]}}}
        (self.tmp / "fit.json").write_text(json.dumps(fit))
        tl.FIT = self.tmp / "fit.json"
        # five past matches: both teams' players at their usual spots; the
        # away winger dribbles 4 a game, the away nine 0.
        self.rows = [[], []]
        for k in range(5):
            eid = 100 + k
            lu = {"home": {"players": [player(i, n, p, {"totalContest": 1, "totalTackle": 2 + (k == 4) * 3,
                                                       "interceptionWon": 1, "wasFouled": 1, "fouls": 1})
                                       for i, n, p, _, _ in HOME]},
                  "away": {"players": [player(i, n, p, {"totalContest": 4 if i == 13 else 0, "totalTackle": 1,
                                                       "interceptionWon": 2 if i == 14 else 0, "wasFouled": 1, "fouls": 1})
                                       for i, n, p, _, _ in AWAY]}}
            ap = {"home": [{"player": {"id": i}, "averageX": x, "averageY": y} for i, _, _, x, y in HOME],
                  "away": [{"player": {"id": i}, "averageX": x, "averageY": y} for i, _, _, x, y in AWAY]}
            st = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
                {"name": "Ball possession", "homeValue": "45%", "awayValue": "55%"}]}]}]}
            (self.tmp / f"event_{eid}_lineups.json").write_text(json.dumps(lu))
            (self.tmp / f"event_{eid}_average-positions.json").write_text(json.dumps(ap))
            (self.tmp / f"event_{eid}_statistics.json").write_text(json.dumps(st))
            for t, side in ((0, HOME), (1, AWAY)):
                for i, n, p, _, _ in side:
                    self.rows[t].append({"player": n, "player_id": i, "match_id": eid, "started": True, "minutes": 90,
                                         "date": f"2026-10-{10 + k:02d}", "opponent": "Them"})
        xi = lambda side: [{"name": n, "pos": p} for _, n, p, _, _ in side] + [{"name": "Keeper", "pos": "G"}]
        self.entry = {"teams": [{"name": "Hal", "side": "home"}, {"name": "Ari", "side": "away"}],
                      "lineups": {"confirmed": {"home": {"xi": xi(HOME)}, "away": {"xi": xi(AWAY)}}},
                      "players": self.rows}

    def tearDown(self):
        tl.CACHE, tl.FIT = self.saved
        tl._load.cache_clear()
        tl.fit.cache_clear()
        shutil.rmtree(self.tmp)

    def by(self, mu, side, name):
        return next(m for m in mu[side] if m["player"] == name)

    def test_pairs_by_usual_position_one_to_one(self):
        mu = tl.matchups(self.entry)
        self.assertEqual(self.by(mu, "home", "Hal Back")["opp"], "Ari Wing")
        self.assertEqual(self.by(mu, "away", "Ari Wing")["opp"], "Hal Back")

    def test_tackles_follow_the_dribbler(self):
        mu = tl.matchups(self.entry)
        e = self.by(mu, "home", "Hal Back")["effects"]["Tackles"]
        self.assertAlmostEqual(e["rate"], 4.0)
        self.assertAlmostEqual(e["mult"], math.exp(0.07 * math.log(4.0)))
        self.assertEqual(e["band"], "top 10%")

    def test_role_gate_on_shots_and_fouled(self):
        mu = tl.matchups(self.entry)
        nine = self.by(mu, "home", "Hal Nine")         # a forward: shots and fouled not used
        self.assertIsNone(nine["effects"]["Shots"]["rate"])
        self.assertEqual(nine["effects"]["Fouled"]["mult"], 1.0)
        back = self.by(mu, "home", "Hal Back")         # a defender facing a midfielder: used
        self.assertIsNotNone(back["effects"]["Shots"]["rate"])

    def test_same_line_pairs_are_dropped(self):
        # move the away nine onto the home back's spot: back v nine is fine,
        # but two centre-backs paired together would be dropped
        mu = tl.matchups(self.entry)
        self.assertFalse(any(m["pos"] == "F" and m["opp_pos"] == "F" for side in mu.values() for m in side))
        self.assertFalse(any(m["pos"] == "D" and m["opp_pos"] == "D" for side in mu.values() for m in side))

    def test_adjust_moves_the_chance_the_right_way(self):
        self.assertGreater(tl.adjust(0.5, "Tackles", 2, 1.1), 0.5)
        self.assertLess(tl.adjust(0.5, "Tackles", 2, 0.9), 0.5)
        self.assertEqual(tl.adjust(0.5, "Tackles", 2, 1.0), 0.5)

    def test_history_names_who_he_faced(self):
        h = tl.history(self.entry, 0, "Hal Back", "Tackles")
        self.assertEqual(len(h), 5)
        self.assertEqual(h[-1]["value"], 5)               # the last game: 2 + 3
        self.assertEqual(h[-1]["opp"], "Ari Wing")
        self.assertEqual(h[-1]["opp_did"], 4)              # his dribbles that game
        self.assertEqual(h[-1]["poss"], 45.0)

    def test_missing_cache_is_not_fatal(self):
        shutil.rmtree(self.tmp)
        self.tmp.mkdir()
        (self.tmp / "fit.json").write_text("{}")
        tl._load.cache_clear()
        tl.fit.cache_clear()
        self.assertEqual(tl.matchups(self.entry), {"home": [], "away": []})
        self.assertEqual(tl.history(self.entry, 0, "Hal Back", "Tackles"), [])


if __name__ == "__main__":
    unittest.main()
