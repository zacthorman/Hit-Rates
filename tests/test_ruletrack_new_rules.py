"""The rules added to ruletrack.py on 28 Oct 2026: which rows they take."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import blowout  # noqa: E402
import ruletrack  # noqa: E402


def row(player, stat, line, over, price, k10=10, n10=10, team="Utah Jazz", event=1, result=None):
    snap = {"price": price, "chance": 0.5, "t": 0}
    return {"event_id": event, "fixture": "Utah Jazz v San Antonio Spurs", "kickoff": 1793235600,
            "sport": "basketball", "team": team, "player": player, "stat": stat, "line": line,
            "over": over, "label": "", "first": dict(snap), "last": dict(snap),
            "k10": k10, "n10": n10, "result": result}


class NewRules(unittest.TestCase):
    def setUp(self):
        # no history file, no report: every projection comes from this stub
        ruletrack._hist_model = lambda: {}
        self._proj = blowout.projection
        blowout.projection = lambda e, f, k: {
            "home": "Utah Jazz", "away": "San Antonio Spurs", "margin": -15.0,
            "starters": {"Utah Jazz": ["Ace Bailey"], "San Antonio Spurs": ["Stephon Castle"]}}

    def tearDown(self):
        blowout.projection = self._proj

    def test_alt_perfect_takes_only_one_sided_lines_with_ten_of_ten(self):
        rows = [row("A", "Points", 9.5, True, 1.30),                      # alt, 10/10: in
                row("B", "Points", 9.5, True, 1.30, k10=9),               # 9/10: control
                row("C", "Points", 9.5, True, 1.20),                      # too short
                row("D", "Points", 19.5, True, 1.80), row("D", "Points", 19.5, False, 1.95)]  # main line
        q = ruletrack.qualifying(rows)
        self.assertEqual([r["player"] for r in q.get("nba_alt_perfect", [])], ["A"])
        self.assertEqual([r["player"] for r in q.get("control_nba_alt_nine", [])], ["B"])

    def test_blowout_under_takes_the_underdogs_starters_only(self):
        rows = []
        for who, team in (("Ace Bailey", "Utah Jazz"), ("Bench Guy", "Utah Jazz"),
                          ("Stephon Castle", "San Antonio Spurs")):
            rows += [row(who, "Points", 15.5, True, 1.85, team=team),
                     row(who, "Points", 15.5, False, 1.90, team=team)]
        rows += [row("Ace Bailey", "Rebounds", 4.5, True, 1.85), row("Ace Bailey", "Rebounds", 4.5, False, 1.90)]
        q = ruletrack.qualifying(rows)
        got = [(r["player"], r["stat"]) for r in q.get("nba_under_blowout", [])]
        self.assertEqual(got, [("Ace Bailey", "Points")])

    def test_blowout_needs_a_twelve_point_projection(self):
        blowout.projection = lambda e, f, k: {"home": "Utah Jazz", "away": "San Antonio Spurs", "margin": -8.0,
                                              "starters": {"Utah Jazz": ["Ace Bailey"]}}
        rows = [row("Ace Bailey", "Points", 15.5, True, 1.85), row("Ace Bailey", "Points", 15.5, False, 1.90)]
        self.assertFalse(ruletrack.qualifying(rows).get("nba_under_blowout"))

    def test_new_rules_start_live_on_28_october(self):
        for r in ("nba_alt_perfect", "control_nba_alt_nine", "nba_under_blowout"):
            self.assertEqual(ruletrack.RULE_START[r], ruletrack._OCT28)
            self.assertIn(r, ruletrack.RULES)


class DriftRules(unittest.TestCase):
    """The rules added on 31 Oct 2026."""

    def setUp(self):
        ruletrack._hist_model = lambda: {}

    def game(self, price, k10=9, result=None, kickoff=1793235600, event=1, over=True, last=None):
        r = row("A", "Rebounds", 3.5, over, price, k10=k10, event=event, result=result)
        r["kickoff"] = kickoff
        if last is not None:
            r["last"] = {"price": last, "chance": 0.5, "t": 0}
        return r

    def test_drift_after_a_miss(self):
        earlier = self.game(1.20, result="lose", kickoff=1793149200, event=0)
        now = self.game(1.33, k10=9, event=1)
        q = ruletrack.qualifying([earlier, now])
        self.assertEqual([r["event_id"] for r in q.get("nba_alt_drift_miss", [])], [1])

    def test_no_drift_rule_after_a_win_or_without_a_drift(self):
        for prev_result, now_price in (("win", 1.33), ("lose", 1.22)):
            earlier = self.game(1.20, result=prev_result, kickoff=1793149200, event=0)
            now = self.game(now_price, k10=9, event=1)
            self.assertFalse(ruletrack.qualifying([earlier, now]).get("nba_alt_drift_miss"))

    def test_drift_needs_eight_of_ten(self):
        earlier = self.game(1.20, result="lose", kickoff=1793149200, event=0)
        now = self.game(1.40, k10=7, event=1)
        self.assertFalse(ruletrack.qualifying([earlier, now]).get("nba_alt_drift_miss"))

    def test_short_perfect_band(self):
        q = ruletrack.qualifying([row("A", "Points", 9.5, True, 1.20), row("B", "Points", 9.5, True, 1.12)])
        self.assertEqual([r["player"] for r in q.get("nba_alt_short_perfect", [])], ["A"])

    def test_day_drift_and_steam_on_main_lines(self):
        o = row("A", "Points", 19.5, True, 1.80); o["last"] = {"price": 2.00, "chance": 0.5, "t": 0}
        u = row("A", "Points", 19.5, False, 2.00); u["last"] = {"price": 1.80, "chance": 0.5, "t": 0}
        q = ruletrack.qualifying([o, u])
        self.assertEqual([r["over"] for r in q.get("nba_main_day_drift", [])], [True])
        self.assertEqual([r["over"] for r in q.get("control_nba_main_steam", [])], [False])

    def test_day_drift_scored_at_the_last_price(self):
        o = row("A", "Points", 19.5, True, 1.80, result="win"); o["last"] = {"price": 2.00, "chance": 0.5, "t": 0}
        s = ruletrack._score([o], ruletrack.SCORE_AT["nba_main_day_drift"])
        self.assertAlmostEqual(s["profit"], 1.0)


if __name__ == "__main__":
    unittest.main()
