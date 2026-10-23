"""case_score_backtest.py: the parts that decide what the backtest can see.

    .venv/bin/python -B -m unittest tests.test_case_score_backtest

Synthetic matches only; the full run needs the cache and takes minutes.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import case_score_backtest as cb  # noqa: E402

DAY = 86400
T0 = 1_780_000_000


def ev(i, ts, home, away, hg, ag, tid=17, friendly=False):
    return {"id": i, "ts": ts, "home": home, "away": away, "home_name": f"T{home}",
            "away_name": f"T{away}", "hg": hg, "ag": ag, "hc": hg, "ac": ag, "tid": tid,
            "comp": "League", "friendly": friendly}


class Form(unittest.TestCase):
    def setUp(self):
        events = [ev(i, T0 + i * DAY, 1, 2 + i % 3, 1, 0) for i in range(8)]
        events.append(ev(50, T0 + 3 * DAY + 3600, 1, 9, 2, 2, tid=99))            # a cup tie
        events.append(ev(51, T0 + 4 * DAY + 3600, 1, 9, 5, 0, friendly=True))     # never counted
        stats = {e["id"]: {"xg": (1.2, 0.8)} for e in events if e["id"] != 3}     # 3 has no statistics
        self.hist = cb.History(events, stats)

    def test_only_matches_before_the_cut(self):
        recs = self.hist.form(1, 17, T0 + 5 * DAY)
        self.assertEqual([r["id"] for r in recs], [0, 1, 2, 4])     # 3 has no stats, 5+ not yet played
        self.assertTrue(all(r["date"] < cb._date(T0 + 5 * DAY) for r in recs))

    def test_competition_preferred_then_all_competitive(self):
        self.assertNotIn(50, [r["id"] for r in self.hist.form(1, 17, T0 + 9 * DAY)])
        # Fewer than five in the cup: falls back to every competitive match, never the friendly.
        ids = [r["id"] for r in self.hist.form(1, 99, T0 + 9 * DAY)]
        self.assertIn(50, ids)
        self.assertNotIn(51, ids)

    def test_record_shape_from_the_away_side(self):
        r = self.hist.form(2, 17, T0 + 9 * DAY)[0]
        self.assertEqual((r["venue"], r["goals_for"], r["goals_against"], r["result"]), ("away", 0, 1, "L"))
        self.assertEqual(r["stats"]["ALL"]["Expected goals"], 0.8)
        self.assertEqual(r["against"]["ALL"]["Goals"], 1.0)


class Scoring(unittest.TestCase):
    def rows(self):
        return [{"o": 0, "hg": 1, "ag": 0, "window": 1,
                 "f": {"current": {"p": (0.4, 0.3, 0.3), "score": (1, 0), "modal": (1, 1), "pscore": 0.1},
                       "dc": {"p": (0.6, 0.2, 0.2), "score": (2, 0), "modal": (1, 0), "pscore": 0.12}}},
                {"o": 2, "hg": 0, "ag": 2, "window": 1,
                 "f": {"current": {"p": (0.5, 0.3, 0.2), "score": (1, 0), "modal": (1, 0), "pscore": 0.05},
                       "dc": {"p": (0.3, 0.3, 0.4), "score": (0, 2), "modal": (1, 1), "pscore": 0.06}}}]

    def test_summarise(self):
        s, n = cb.summarise(self.rows(), ["current", "dc"], need=())
        self.assertEqual(n, 2)
        self.assertEqual(s["current"]["exact"], 0.5)
        self.assertEqual(s["dc"]["exact"], 0.5)
        self.assertEqual(s["current"]["exact_modal"], 0.0)
        self.assertEqual(s["dc"]["acc"], 1.0)
        self.assertLess(s["dc"]["rps"], s["current"]["rps"])

    def test_paired_is_new_minus_current(self):
        d = cb.paired(self.rows(), "dc")
        self.assertEqual(d["n"], 2)
        self.assertLess(d["rps"][0], 0)
        self.assertLess(d["logloss"][0], 0)


class Bookmaker(unittest.TestCase):
    def test_last_snapshot_before_kickoff_and_swap(self):
        start = "2026-10-18T13:30:00.000Z"
        kick = 1792330200

        def snap(fetched, home_p, swapped=False):
            return {"fetched": fetched, "events": {"123": {
                "start": start, "sport": "football", "swapped": swapped,
                "markets": [{"type": "MATCH_ODDS", "runners": [
                    {"name": "A", "p": home_p}, {"name": "B", "p": 0.2}, {"name": "The Draw", "p": 0.3}]},
                    {"type": "CORRECT_SCORE", "runners": [{"name": "2 - 1", "p": 0.1}]}]}}}

        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.json").write_text(json.dumps(snap(kick - 7200, 0.4)))
            Path(d, "b.json").write_text(json.dumps(snap(kick - 3600, 0.5)))
            Path(d, "c.json").write_text(json.dumps(snap(kick + 600, 0.9)))      # in play: ignored
            b = cb.bookmaker(Path(d))[123]
            self.assertAlmostEqual(b["p"][0], 0.5)
            self.assertAlmostEqual(sum(b["p"]), 1.0)
            self.assertEqual(list(b["cs"]), [(2, 1)])
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.json").write_text(json.dumps(snap(kick - 7200, 0.5, swapped=True)))
            b = cb.bookmaker(Path(d))[123]
            self.assertAlmostEqual(b["p"][2], 0.5)          # Betfair's home side is our away side
            self.assertEqual(list(b["cs"]), [(1, 2)])


if __name__ == "__main__":
    unittest.main()
