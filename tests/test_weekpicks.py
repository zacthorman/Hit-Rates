"""Picks of the week (weekpicks.py) and the us_likely_top5 rule behind it."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ruletrack  # noqa: E402
import weekpicks  # noqa: E402

NOW = 1793235600.0


def us_row(player, chance, price=1.9, event=1, stat="Points", sport="basketball", kickoff=NOW + 3600):
    snap = {"price": price, "chance": chance, "t": 0}
    return {"event_id": event, "fixture": "A v B", "kickoff": kickoff, "sport": sport, "team": "A",
            "player": player, "stat": stat, "line": 10.5, "over": True, "label": "Over 10.5",
            "first": dict(snap), "last": dict(snap), "k10": 7, "n10": 10, "result": None}


class LikelyTop5(unittest.TestCase):
    def setUp(self):
        ruletrack._hist_model = lambda: {}

    def test_takes_the_five_most_likely_in_the_price_band(self):
        rows = [us_row(f"P{i}", 0.50 + i / 100, event=i) for i in range(8)]
        rows.append(us_row("Short", 0.95, price=1.40, event=20))      # price too short
        rows.append(us_row("Long", 0.90, price=2.80, event=21))       # price too long
        got = {r["player"] for r in ruletrack.qualifying(rows)["us_likely_top5"]}
        self.assertEqual(got, {"P3", "P4", "P5", "P6", "P7"})

    def test_one_line_per_player_per_game(self):
        rows = [us_row("Same", 0.70), us_row("Same", 0.69, stat="Rebounds")]
        rows += [us_row(f"P{i}", 0.5, event=i + 2) for i in range(5)]
        got = [r["player"] for r in ruletrack.qualifying(rows)["us_likely_top5"]]
        self.assertEqual(got.count("Same"), 1)

    def test_football_rows_never_qualify(self):
        rows = [us_row("F", 0.8, sport="football")]
        self.assertFalse(ruletrack.qualifying(rows).get("us_likely_top5"))

    def test_rule_is_frozen_with_a_start_date(self):
        self.assertIn("us_likely_top5", ruletrack.RULES)
        self.assertIn("us_likely_top5", ruletrack.RULE_START)


class SharpSection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._root = weekpicks.ROOT
        weekpicks.ROOT = Path(self.tmp.name)
        (weekpicks.ROOT / "reports").mkdir()
        (weekpicks.ROOT / "value").mkdir()

    def tearDown(self):
        weekpicks.ROOT = self._root
        self.tmp.cleanup()

    def bet(self, edge, kickoff=NOW + 7200, **kw):
        b = {"book": "B3", "player": "Bukayo Saka", "stat": "Shots", "line": 1.5, "over": True,
             "price": 2.2, "p": 0.5, "sharp": 0.5, "sharp_src": "pinnacle", "sharp_edge": edge,
             "kickoff": kickoff, "game": "Arsenal v Spurs"}
        b.update(kw)
        return b

    def test_keeps_only_two_percent_edges_inside_the_window(self):
        bets = [self.bet(0.10), self.bet(0.01), self.bet(0.05, kickoff=NOW + 72 * 3600),
                self.bet(0.04, player="Declan Rice"), self.bet(None)]
        (weekpicks.ROOT / "reports" / "value_books.json").write_text(json.dumps({"bets": bets}))
        got = weekpicks.sharp_bets(NOW)["football"]
        self.assertEqual([round(b["edge"], 2) for b in got], [0.10, 0.04])
        self.assertEqual(got[0]["bet"], "Bukayo Saka 2+ shots")
        self.assertEqual(got[0]["book"], "Bet365")
        self.assertIn("Pinnacle makes it 50%", got[0]["note"])

    def test_record_counts_only_settled_rows_with_a_sharp_price(self):
        rows = [{"result": "win", "first": {"price": 2.0, "sharp": 0.55}},
                {"result": "lose", "first": {"price": 2.0, "sharp": 0.55}},
                {"result": "win", "first": {"price": 3.0}},
                {"result": None, "first": {"price": 2.0, "sharp": 0.6}}]
        (weekpicks.ROOT / "value" / "log.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        rec = weekpicks.sharp_record()
        self.assertEqual((rec["n"], rec["won"]), (2, 1))
        self.assertAlmostEqual(rec["roi"], 0.0)
        self.assertAlmostEqual(rec["expected"], 0.10)

    def test_build_survives_missing_files(self):
        keep, weekpicks.rule_bets = weekpicks.rule_bets, (lambda now: {})
        try:
            out = weekpicks.build(NOW)
        finally:
            weekpicks.rule_bets = keep
        self.assertEqual(out["sports"], {})
        self.assertIsNone(out["sharpRecord"])


class RuleSection(unittest.TestCase):
    def test_keep_hides_rules_already_failing_live(self):
        self.assertTrue(weekpicks._keep({}))
        self.assertTrue(weekpicks._keep({"games": 5, "roi": -0.3, "hi": 0.4}))
        self.assertFalse(weekpicks._keep({"games": 4, "roi": -0.4, "hi": -0.07}))
        self.assertFalse(weekpicks._keep({"games": 11, "roi": -0.01, "hi": 0.2}))
        self.assertTrue(weekpicks._keep({"games": 17, "roi": 0.27, "hi": 0.47}))

    def test_bets_split_by_sport_and_shown_once(self):
        import pplog
        nba = us_row("Isaiah Stewart", 0.6, event=1)
        nfl = us_row("Kalif Raymond", 0.6, event=2, sport="american-football", stat="Receiving Yards")
        keep = (pplog.all_rows, ruletrack.qualifying, ruletrack.tonight, weekpicks._live)
        pplog.all_rows = lambda: []
        ruletrack.qualifying = lambda rows: {}
        ruletrack.tonight = lambda a, b, q: {"rule_a": [nba, nfl], "rule_b": [nba]}
        weekpicks._live = lambda rule, bets: {"n": 30, "games": 25, "roi": 0.1 if rule == "rule_a" else 0.05,
                                             "lo": 0.01, "hi": 0.2}
        try:
            out = weekpicks.rule_bets(NOW)
        finally:
            pplog.all_rows, ruletrack.qualifying, ruletrack.tonight, weekpicks._live = keep
        self.assertEqual([g["rule"] for g in out["basketball"]], ["rule_a"])
        self.assertEqual([g["rule"] for g in out["american-football"]], ["rule_a"])
        self.assertTrue(out["basketball"][0]["proven"])


class BetText(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(weekpicks.bet_text({"player": "X", "label": "Over 1.5", "stat": "Shots"}), "X over 1.5 shots")
        self.assertEqual(weekpicks.bet_text({"player": "X", "label": "to score", "stat": "Goals"}), "X to score")


if __name__ == "__main__":
    unittest.main()
