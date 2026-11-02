"""The football starter rules added to ruletrack.py on 2 Nov 2026."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ruletrack  # noqa: E402


def fb(player, stat, edge, started=True, result="win", comp="Premier League", line=0.5, over=True,
       price=1.8, event=1, ss_ok=None):
    last = {"price": price, "chance": (1 + edge) / price, "edge": edge, "t": 0}
    return {"event_id": event, "fixture": "Northbridge v Southfield", "kickoff": 1793700000,
            "sport": "football", "competition": comp, "player": player, "stat": stat, "line": line,
            "over": over, "label": "", "first": dict(last, edge=-0.5), "last": last,
            "started": started, "result": result, "ss_ok": ss_ok, "k10": 5, "n10": 10}


class FootballStarters(unittest.TestCase):
    def setUp(self):
        ruletrack._hist_model = lambda: {}

    def picks(self, rows):
        q = ruletrack.qualifying(rows)
        return {k: sorted(r["player"] for r in q.get(k, []))
                for k in ("fb_ss_fouls_model", "fb_ss_shots_model", "control_fb_ss_fouls")}

    def test_takes_starters_in_super_sub_games_judged_at_the_last_price(self):
        got = self.picks([
            fb("A", "Fouls", 0.08),                          # in: last price edge 8%, the first was -50%
            fb("B", "Fouls", 0.02),                          # model does not agree: control
            fb("C", "Shots", 0.10),                          # shots rule
            fb("D", "Fouls", 0.20, started=False),           # came off the bench: out
            fb("E", "Fouls", 0.20, started=None),            # settled with no line-up: out
            fb("F", "Fouls", 0.20, started=None, result=None),   # still to play: in, line-up decides
            fb("G", "Fouls", 0.20, comp="LaLiga"),           # no Super Sub there
            fb("H", "Fouls", 0.20, comp="LaLiga", ss_ok=True),   # the page said yes
            fb("I", "Fouls", 0.20, ss_ok=False),             # the page said no
            fb("J", "Tackles", 0.20),                        # not these markets
            fb("K", "Fouls", 0.20, line=3.5),                # 4+ fouls is not a Super Sub line
        ])
        self.assertEqual(got["fb_ss_fouls_model"], ["A", "F", "H"])
        self.assertEqual(got["fb_ss_shots_model"], ["C"])
        self.assertEqual(got["control_fb_ss_fouls"], ["B"])

    def test_one_bet_per_player_stat_and_game(self):
        got = self.picks([fb("A", "Fouls", 0.10, line=0.5, price=1.3),
                          fb("A", "Fouls", 0.10, line=1.5, price=2.1)])
        self.assertEqual(got["fb_ss_fouls_model"], ["A"])

    def test_scored_at_the_last_price_and_live_from_2_november(self):
        for r in ("fb_ss_fouls_model", "fb_ss_shots_model", "control_fb_ss_fouls"):
            self.assertEqual(ruletrack.SCORE_AT[r], "last")
            self.assertEqual(ruletrack.RULE_START[r], ruletrack._NOV02_FB)
            self.assertIn(r, ruletrack.RULES)


if __name__ == "__main__":
    unittest.main()
