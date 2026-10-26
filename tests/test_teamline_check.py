"""teamline_check.py and teamlog.py scoreboard, on synthetic data only.

    python -B -m unittest tests.test_teamline_check
    python -m pytest tests/test_teamline_check.py

Nothing here reads the cache, pplog/ or the network. Teams, matches and prices
are made up.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import teamline_check as tc  # noqa: E402
import teamlog  # noqa: E402

try:
    import numpy as np
    import pandas as pd
    import teamline_backtest as B
except ImportError:  # pragma: no cover
    B = None

GATE = {"markets": {
    "Corner kicks|side": {"pass": True, "threshold": 0.05, "alpha_match": None},
    "Corner kicks|match": {"pass": False, "threshold": None, "alpha_match": 0.02},
    "Shots on target|side": {"pass": True, "threshold": 0.05, "alpha_match": None},
}, "take_shortfall": 0.04}


class Intervals(unittest.TestCase):
    def test_wilson(self):
        lo, hi = tc.wilson(50, 100)
        self.assertAlmostEqual(lo, 0.4038, places=3)
        self.assertAlmostEqual(hi, 0.5962, places=3)
        self.assertEqual(tc.wilson(0, 10)[0], 0.0)

    def test_cluster_boot_is_seeded_and_degenerate_when_groups_agree(self):
        groups = {i: [{"x": 1.0}, {"x": 1.0}] for i in range(10)}
        self.assertEqual(tc.cluster_boot(groups, lambda rs: sum(r["x"] for r in rs) / len(rs)), (1.0, 1.0))
        g2 = {i: [{"x": float(i % 2)}] for i in range(30)}
        f = lambda rs: sum(r["x"] for r in rs) / len(rs)  # noqa: E731
        self.assertEqual(tc.cluster_boot(g2, f, n=300), tc.cluster_boot(g2, f, n=300))

    def test_summarise(self):
        # 10 matches, 2 lines each at 60% said and price 1.80; 12 of 20 land.
        rows = [{"match": m, "p": 0.6, "won": int(m < 6), "price": 1.8} for m in range(10) for _ in range(2)]
        s = tc.summarise(rows, lambda r: r["match"])
        self.assertEqual((s["n"], s["groups"], s["won"]), (20, 10, 12))
        self.assertAlmostEqual(s["got"], 0.6)
        self.assertAlmostEqual(s["gap"], 0.0)
        self.assertAlmostEqual(s["ratio"], 1.0)
        self.assertAlmostEqual(s["ret"], 0.6 * 1.8 - 1)
        self.assertAlmostEqual(s["edge"], 0.6 * 1.8 - 1)
        self.assertLessEqual(s["ret_ci"][0], s["ret"])
        self.assertGreaterEqual(s["ret_ci"][1], s["ret"])
        self.assertEqual(tc.summarise([], lambda r: r), {"n": 0})

    def test_tighten_rule(self):
        losing = {"ret_ci": (-0.12, -0.02), "ratio_ci": (0.80, 0.90)}
        self.assertEqual(len(tc.tighten(losing, 0.05)), 2)
        unclear = {"ret_ci": (-0.05, 0.04), "ratio_ci": (0.90, 1.02)}
        self.assertEqual(tc.tighten(unclear, 0.05), [])
        # got / said below 1/1.05 = 0.952 throughout: a take at 5% loses even at the book's price
        short = {"ret_ci": (-0.05, 0.04), "ratio_ci": (0.90, 0.94)}
        self.assertEqual(len(tc.tighten(short, 0.05)), 1)


class Record(unittest.TestCase):
    def test_record_rows_counts_each_leg_once(self):
        leg = {"event_id": 1, "kickoff": 1_790_000_000, "sport": "football", "team": "Northbridge",
               "player": None, "stat": "Corner kicks", "line": 4.5, "over": True, "fair": 1.5,
               "chance": 0.7, "result": "win", "exchange_back": None}
        bets = [{"category": "Pick: acca", "legs": [leg, dict(leg, event_id=2, result="lose", chance=0.65)]},
                {"category": "Fixture single", "legs": [dict(leg, chance=0.71)]},          # same leg again
                {"category": "Fixture single", "legs": [dict(leg, event_id=3, result="void")]},
                {"category": "Fixture single", "legs": [dict(leg, event_id=4, player="A Player")]},
                {"category": "Fixture single", "legs": [dict(leg, event_id=5, sport="american-football")]}]
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "b.json").write_text(json.dumps(bets))
            rows = tc.record_rows(tmp / "b.json")
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(sorted((r["event_id"], r["won"], r["p"]) for r in rows), [(1, 1, 0.7), (2, 0, 0.65)])
        self.assertEqual(rows[0]["market"], "Corner kicks|side")


@unittest.skipIf(B is None, "needs numpy, pandas and the backtest's dependencies")
class TakeBand(unittest.TestCase):
    def frame(self):
        # Two months either side of the June cut, one market, model against proxy.
        cut = pd.Timestamp(B.SELECT_END).timestamp()
        rows = []
        for i in range(40):
            for ts in (cut - 86400 * 30, cut + 86400 * 30):
                rows.append({"market": "Corner kicks|side", "match": f"{ts}-{i}", "ts": ts, "line": 4.5,
                             "model": 0.70, "lin": 0.55, "y": int(i % 10 < 6)})
        return pd.DataFrame(rows)

    def test_take_rows_use_the_band_and_the_cut(self):
        df = self.frame()
        held = tc.take_rows(df, "Corner kicks|side", 0.05, 0.09, True)
        early = tc.take_rows(df, "Corner kicks|side", 0.05, 0.09, False)
        # Over: p 0.70 against a book at 1/(0.55 x 1.09) = 1.668, edge +16.8%: a take.
        # Under: p 0.30, under 50%: never a take.
        self.assertEqual((len(held), len(early)), (40, 40))
        self.assertTrue(all(abs(r["edge"] - (0.70 / (0.55 * 1.09) - 1)) < 1e-9 for r in held))
        self.assertEqual(sum(r["won"] for r in held), 24)
        # An edge past the 30% cap is not a take.
        self.assertEqual(tc.take_rows(df.assign(lin=0.45), "Corner kicks|side", 0.05, 0.09, True), [])

    def test_likely_rows_take_both_sides_where_unders_are_offered(self):
        df = self.frame().assign(model=0.40)
        rows = tc.likely_rows(df, "Corner kicks|side", True)
        self.assertTrue(rows and all(abs(r["p"] - 0.60) < 1e-9 for r in rows))
        self.assertEqual(sum(r["won"] for r in rows), 16)     # the under lands when the over does not


def tl_row(eid, verdict, p, price, won, over=True, market="Corner kicks|side", first_price=None):
    first = {"t": 1, "price": first_price or price, "verdict": verdict}
    return {"event_id": eid, "scope": "home", "stat": "Corner kicks", "line": 4.5, "over": over,
            "tl_market": market, "model_p": p, "result": "win" if won else "lose",
            "first": first, "last": {"t": 2, "price": price, "verdict": verdict}}


class Scoreboard(unittest.TestCase):
    def setUp(self):
        import teamlines
        self._gate = dict(teamlines._GATE)
        teamlines._GATE.clear()
        teamlines._GATE.update(GATE)

    def tearDown(self):
        import teamlines
        teamlines._GATE.clear()
        teamlines._GATE.update(self._gate)

    def test_rows_keep_the_logged_chance_for_unders(self):
        g = teamlog.scoreboard_rows([tl_row(1, "take", 0.62, 1.9, True, over=False)])
        self.assertEqual(g[("Corner kicks|side", "take")][0]["p"], 0.62)

    def test_price_move_and_unpriced_lines(self):
        rows = [tl_row(1, "take", 0.6, 1.8, True, first_price=2.0),
                dict(tl_row(2, None, 0.6, 1.8, False), model_p=None)]
        g = teamlog.scoreboard_rows(rows)
        self.assertEqual(list(g), [("Corner kicks|side", "take")])
        self.assertAlmostEqual(g[("Corner kicks|side", "take")][0]["clv"], 2.0 / 1.8 - 1)

    def test_verdicts(self):
        self.assertIn("too few", teamlog.judge_takes({"n": 10}, 0.05))
        losing = [tl_row(i, "take", 0.65, 1.7, i % 10 < 3) for i in range(120)]
        winning = [tl_row(i, "take", 0.60, 1.9, i % 10 < 7) for i in range(120)]
        for rows, word in ((losing, "losing"), (winning, "holding")):
            s = tc.summarise(teamlog.scoreboard_rows(rows)[("Corner kicks|side", "take")], lambda x: x["match"])
            self.assertTrue(teamlog.judge_takes(s, 0.05).startswith(word), (word, teamlog.judge_takes(s, 0.05)))

    def test_scoreboard_runs_on_rows_and_flags_takes_in_failed_markets(self):
        rows = [tl_row(i, "take", 0.62, 1.8, i % 2 == 0) for i in range(60)]
        rows += [tl_row(100 + i, "take", 0.62, 1.8, True, market="Corner kicks|match") for i in range(3)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = teamlog.scoreboard(rows=rows)
        text = buf.getvalue()
        self.assertEqual(out[("last", "Corner kicks|side", "take")]["n"], 60)
        self.assertIn("which should be none", text)
        self.assertIn("shots on target (one side)", text)
        self.assertIn("too few settled takes", text)


if __name__ == "__main__":
    unittest.main()
