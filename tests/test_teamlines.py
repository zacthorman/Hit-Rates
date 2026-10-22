"""Team lines: the take gate (teamlines.py), the backtest (teamline_backtest.py),
the team log (teamlog.py) and the page (report.py's teamValued()).

    .venv/bin/python -B -m unittest tests.test_teamlines

Synthetic data throughout, so it runs without cache/. The backtest tests need
numpy, pandas and statsmodels (as teamline_backtest.py does) and are skipped
without them; the page tests need node, and lift the page's own JavaScript out
of the script report.py renders, as test_gamestate.py does.
"""
from __future__ import annotations

import gzip
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import teamlines as TL  # noqa: E402

try:
    import numpy as np
    import pandas as pd
    import statsmodels.api  # noqa: F401
    import teamline_backtest as B
except ImportError:  # pragma: no cover
    B = None

GATE = {"generated": "2026-10-22", "take_shortfall": 0.04, "markets": {
    "Corner kicks|side": {"pass": True, "threshold": 0.05, "alpha_match": None},
    "Corner kicks|match": {"pass": False, "threshold": None, "alpha_match": 0.02},
    "Yellow cards|match": {"pass": True, "threshold": 0.10, "alpha_match": 0.0},
    "Fouls|side": {"pass": False, "threshold": None, "alpha_match": None}}}


def nb_reference(k, mu, alpha):
    """P(X >= k) summed from the negative binomial pmf with lgamma."""
    if alpha == 0:
        return 1 - sum(math.exp(-mu) * mu ** i / math.factorial(i) for i in range(k))
    r = 1 / alpha
    q = r / (r + mu)
    pmf = lambda i: math.exp(math.lgamma(i + r) - math.lgamma(i + 1) - math.lgamma(r)  # noqa: E731
                             + r * math.log(q) + i * math.log1p(-q))
    return 1 - sum(pmf(i) for i in range(k))


# ------------------------------------------------------------------ teamlines.py

class Distribution(unittest.TestCase):
    def test_matches_the_pmf(self):
        for mu, alpha in ((4.7, 0.0), (4.7, 0.05), (10.2, 0.012), (1.9, 0.3)):
            for k in range(0, 15):
                self.assertAlmostEqual(TL.nb_at_least(k, mu, alpha), nb_reference(k, mu, alpha), places=10)

    def test_over_and_under_add_to_one(self):
        for line in (0.5, 3.5, 9.5):
            self.assertAlmostEqual(TL.p_line(line, True, 5.1, 0.04) + TL.p_line(line, False, 5.1, 0.04), 1.0)

    def test_half_line_is_floor_plus_one(self):
        self.assertAlmostEqual(TL.p_line(4.5, True, 5.0, 0.0), TL.nb_at_least(5, 5.0, 0.0))

    def test_edges(self):
        self.assertEqual(TL.nb_at_least(0, 3.0, 0.1), 1.0)
        self.assertEqual(TL.nb_at_least(2, 0.0, 0.1), 0.0)


class Gate(unittest.TestCase):
    def test_market_key(self):
        self.assertEqual(TL.market_key("Corner kicks", "home"), "Corner kicks|side")
        self.assertEqual(TL.market_key("Corner kicks", "away"), "Corner kicks|side")
        self.assertEqual(TL.market_key("Yellow cards", "match"), "Yellow cards|match")
        self.assertEqual(TL.market_name("Yellow cards|match"), "cards (match total)")

    def test_market_gate_only_for_passed(self):
        self.assertIsNotNone(TL.market_gate("Corner kicks|side", GATE))
        self.assertIsNone(TL.market_gate("Corner kicks|match", GATE))
        self.assertIsNone(TL.market_gate("Shots on target|side", GATE))

    def test_page_gate_keeps_passed_only(self):
        g = TL.page_gate(GATE)
        self.assertEqual(sorted(g["markets"]), ["Corner kicks|side", "Yellow cards|match"])
        self.assertEqual(g["markets"]["Corner kicks|side"], {"threshold": 0.05, "alpha_match": None})
        self.assertEqual(g["shortfall"], 0.04)

    def test_gate_file_missing_reads_empty(self):
        self.assertEqual(TL.gate(Path(tempfile.gettempdir()) / "no-such-gate.json"), {})

    def test_shipped_gate_is_consistent(self):
        """The committed teamlines_gate.json: every market known, a threshold exactly when passed."""
        g = TL.gate(TL.GATE)
        if not g:
            self.skipTest("no teamlines_gate.json")
        keys = {TL.market_key(s, sc) for s, sc in TL.MARKETS}
        self.assertEqual(set(g["markets"]), keys)
        for k, m in g["markets"].items():
            self.assertEqual(m["threshold"] is not None, m["pass"], k)
            self.assertEqual(bool(m["why"]), not m["pass"], k)
            if m["pass"]:
                self.assertTrue(0.05 <= m["threshold"] <= TL.SUSPECT, k)
            if k.endswith("|match"):
                self.assertGreaterEqual(m["alpha_match"], 0, k)


class Verdict(unittest.TestCase):
    def test_take_only_in_a_passed_market_from_its_threshold(self):
        # p 0.6 at 1.77 is a 6.2% edge
        self.assertEqual(TL.verdict("Corner kicks|side", 0.6, 1.77, GATE), "take")
        self.assertEqual(TL.verdict("Corner kicks|side", 0.6, 1.72, GATE), "ok")       # 3.2%
        self.assertEqual(TL.verdict("Corner kicks|match", 0.6, 1.77, GATE), "ok")      # failed
        self.assertEqual(TL.verdict("Shots on target|side", 0.6, 1.77, GATE), "ok")    # not in the gate
        self.assertEqual(TL.verdict("Yellow cards|match", 0.6, 1.77, GATE), "ok")      # below its 10%
        self.assertEqual(TL.verdict("Yellow cards|match", 0.6, 1.90, GATE), "take")    # 14%

    def test_caps(self):
        self.assertEqual(TL.verdict("Corner kicks|side", 0.6, 2.30, GATE), "ok")       # 38%: suspect
        self.assertEqual(TL.verdict("Corner kicks|side", 0.45, 3.0, GATE), "long")
        self.assertEqual(TL.verdict("Corner kicks|side", 0.6, 1.5, GATE), "avoid")     # -10%
        self.assertIsNone(TL.verdict("Corner kicks|side", 0.6, 1.0, GATE))
        self.assertIsNone(TL.verdict("Corner kicks|side", None, 1.8, GATE))

    def test_no_gate_no_take(self):
        self.assertEqual(TL.verdict("Corner kicks|side", 0.6, 1.9, {"markets": {}}), "ok")


class ModelChance(unittest.TestCase):
    MODELS = {"Corner kicks": [{"mu": 5.6, "alpha": 0.03}, {"mu": 3.9, "alpha": 0.03}],
              "Yellow cards": [{"mu": 2.1, "alpha": 0.0}, None]}

    def test_side(self):
        p, mu = TL.model_chance(self.MODELS, "Corner kicks", "home", 1, 4.5, True, GATE)
        self.assertAlmostEqual(p, TL.nb_at_least(5, 3.9, 0.03))
        self.assertEqual(mu, 3.9)
        p, _ = TL.model_chance(self.MODELS, "Corner kicks", "away", 0, 4.5, False, GATE)
        self.assertAlmostEqual(p, 1 - TL.nb_at_least(5, 5.6, 0.03))

    def test_match_adds_sides_and_takes_the_gate_spread(self):
        p, mu = TL.model_chance(self.MODELS, "Corner kicks", "match", None, 9.5, True, GATE)
        self.assertAlmostEqual(mu, 9.5)
        self.assertAlmostEqual(p, TL.nb_at_least(10, 9.5, 0.02))

    def test_missing(self):
        self.assertIsNone(TL.model_chance(self.MODELS, "Yellow cards", "match", None, 3.5, True, GATE))
        self.assertIsNone(TL.model_chance(self.MODELS, "Yellow cards", "away", 1, 1.5, True, GATE))
        self.assertIsNone(TL.model_chance(self.MODELS, "Fouls", "home", 0, 10.5, True, GATE))
        self.assertIsNone(TL.model_chance(self.MODELS, "Corner kicks", "home", None, 4.5, True, GATE))


class SideModels(unittest.TestCase):
    def test_reads_ids_home_and_formations_per_side(self):
        import context
        entry = {"teams": [{"name": "A", "id": 1, "side": "home"}, {"name": "B", "id": 2, "side": "away"}],
                 "lineups": {"predicted": {"home": {"formation": "4-3-3", "xi": []},
                                           "away": {"formation": "3-5-2", "xi": []}}}}
        calls = []

        def fake(stat, team, opp, home, f_own, f_opp):
            calls.append((stat, team, opp, home, f_own, f_opp))
            return None if (stat == "Fouls" and team == 2) else {"mu": 4.123456, "alpha": 0.0312345, "x": {}}
        with mock.patch.object(context, "team_model_mu", fake):
            out = TL.side_models(entry, ["Corner kicks", "Fouls"])
        self.assertIn(("Corner kicks", 1, 2, True, "4-3-3", "3-5-2"), calls)
        self.assertIn(("Corner kicks", 2, 1, False, "3-5-2", "4-3-3"), calls)
        self.assertEqual(out["Corner kicks"][0], {"mu": 4.1235, "alpha": 0.03123})
        self.assertIsNone(out["Fouls"][1])

    def test_nothing_without_two_teams(self):
        self.assertEqual(TL.side_models({"teams": [{"id": 1}]}), {})


# ------------------------------------------------------------------ teamline_backtest.py

def lines_frame(rng, n, key, model_bias=0.0, proxy_noise=0.0):
    """Synthetic scored lines: y drawn from a true chance; model and proxy around it."""
    true = rng.uniform(0.2, 0.8, n)
    y = (rng.uniform(size=n) < true).astype(int)
    model = np.clip(true + model_bias, 0.01, 0.99)
    lin = np.clip(true + rng.normal(0, proxy_noise, n), 0.02, 0.98)
    ts = np.linspace(pd.Timestamp("2026-01-02").timestamp(), pd.Timestamp("2026-10-15").timestamp(), n)
    return pd.DataFrame({"market": key, "match": np.arange(n) // 2, "team": None, "ts": ts, "fold": "x",
                         "line": 4.5, "y": y, "base": np.full(n, y.mean()), "record": np.clip(true * 0.5 + 0.25, 0, 1),
                         "lin": lin, "gbm": model, "model": model, "mu": 4.0})


@unittest.skipIf(B is None, "needs numpy, pandas and statsmodels")
class Proxy(unittest.TestCase):
    def test_offered_prices_from_the_linear_fit_with_the_overround(self):
        df = pd.DataFrame({"model": [0.6], "lin": [0.5], "y": [1], "match": [1]})
        c = B.offered(df, "Corner kicks|side")
        self.assertEqual(len(c), 2)                          # over and under
        over = c[c.p == 0.6].iloc[0]
        self.assertAlmostEqual(over.price, 1 / (0.5 * (1 + B.OVERROUND)))
        self.assertAlmostEqual(over.edge, 0.6 * over.price - 1)
        self.assertEqual(c[c.p == 0.4].iloc[0].win, 0)
        self.assertEqual(len(B.offered(df, "Fouls|side")), 1)  # overs only

    def test_takes_window(self):
        c = pd.DataFrame({"p": [0.6, 0.6, 0.6, 0.45], "edge": [0.04, 0.06, 0.35, 0.2], "match": [1, 2, 3, 4]})
        self.assertEqual(B.takes(c, 0.05).index.tolist(), [1])

    def test_threshold_found_when_the_model_knows_more_than_the_book(self):
        rng = np.random.default_rng(1)
        c = B.offered(lines_frame(rng, 6000, "Corner kicks|side", proxy_noise=0.12), "Corner kicks|side")
        t, tried = B.choose_threshold(c)
        self.assertEqual(t, 0.05)
        self.assertGreater(tried[0]["ret"], 0)

    def test_no_threshold_when_the_model_only_flatters_itself(self):
        rng = np.random.default_rng(2)
        c = B.offered(lines_frame(rng, 6000, "Corner kicks|side", model_bias=0.08), "Corner kicks|side")
        t, tried = B.choose_threshold(c)
        self.assertIsNone(t)
        self.assertTrue(all(x["n"] == 0 or x["lo90"] < 0 for x in tried))

    def test_confirm(self):
        c = pd.DataFrame({"p": [0.6] * 60, "edge": [0.1] * 60, "price": [1.8] * 60,
                          "win": [1] * 40 + [0] * 20, "match": range(60)})
        x = B.confirm(c, 0.05)
        self.assertTrue(x["held"])
        self.assertAlmostEqual(x["ret"], 40 / 60 * 1.8 - 1)
        self.assertFalse(B.confirm(c.iloc[:40], 0.05)["held"])        # too few
        lose = c.assign(win=[1] * 30 + [0] * 30)
        self.assertFalse(B.confirm(lose, 0.05)["held"])


@unittest.skipIf(B is None, "needs numpy, pandas and statsmodels")
class Scoring(unittest.TestCase):
    def test_losses(self):
        y = np.array([1, 0])
        p = np.array([0.8, 0.3])
        self.assertAlmostEqual(B.logloss(y, p).mean(), -(math.log(0.8) + math.log(0.7)) / 2)
        self.assertAlmostEqual(B.brier(y, p).mean(), (0.04 + 0.09) / 2)

    def test_boot_diff_sign_and_interval(self):
        rng = np.random.default_rng(3)
        d = lines_frame(rng, 4000, "Corner kicks|side")
        mean, lo, hi = B.boot_diff(d, "model", "record", B.logloss)
        self.assertLess(hi, 0)
        self.assertLessEqual(lo, mean)
        self.assertLessEqual(mean, hi)

    def test_calibration_slope(self):
        rng = np.random.default_rng(4)
        p = rng.uniform(0.05, 0.95, 20000)
        y = (rng.uniform(size=p.size) < p).astype(int)
        a, b = B.calibration(y, p)
        self.assertAlmostEqual(b, 1.0, delta=0.08)
        self.assertAlmostEqual(a, 0.0, delta=0.08)
        z = np.log(p / (1 - p)) * 1.5           # overconfident
        _, b2 = B.calibration(y, 1 / (1 + np.exp(-z)))
        self.assertLess(b2, 0.75)

    def test_page_record_is_the_page_formula(self):
        import model as M
        vals = [3, 5, 6, 2, 7, 4, 5]
        self.assertAlmostEqual(B._page_record(4.5, vals), M.calibrate(M.prob_over(4.5, sum(vals) / 7, vals)))
        self.assertAlmostEqual(B._page_record(9.5, vals, 10.0), M.calibrate(M.prob_over(9.5, 10.0, vals)))


@unittest.skipIf(B is None, "needs numpy, pandas and statsmodels")
class Judge(unittest.TestCase):
    def frame(self):
        rng = np.random.default_rng(5)
        good = lines_frame(rng, 6000, "Corner kicks|side", proxy_noise=0.12)
        bad = lines_frame(rng, 6000, "Fouls|side", model_bias=0.08)
        shots = lines_frame(rng, 6000, "Total shots|side")
        return pd.concat([good, bad, shots], ignore_index=True)

    def test_pass_and_fail_with_reasons(self):
        uses = {"Corner kicks": "gbm", "Fouls": "gbm", "Total shots": "linear"}
        res = B.judge(self.frame(), pd.DataFrame(), uses)
        self.assertEqual(set(res), {"Corner kicks|side", "Fouls|side", "Total shots|side"})
        self.assertTrue(res["Corner kicks|side"]["pass"], res["Corner kicks|side"]["why"])
        self.assertEqual(res["Corner kicks|side"]["threshold"], 0.05)
        self.assertFalse(res["Fouls|side"]["pass"])
        self.assertIsNone(res["Fouls|side"]["threshold"])
        self.assertTrue(any("calibration" in w or "threshold" in w for w in res["Fouls|side"]["why"]))
        self.assertFalse(res["Total shots|side"]["pass"])
        self.assertIn("linear fit itself", " ".join(res["Total shots|side"]["why"]))

    def test_write_produces_the_gate_and_the_tables(self):
        uses = {"Corner kicks": "gbm", "Fouls": "gbm", "Total shots": "linear"}
        res = B.judge(self.frame(), pd.DataFrame(), uses)
        tmp = Path(tempfile.mkdtemp())
        try:
            with mock.patch.object(B, "GATE", tmp / "gate.json"), mock.patch.object(B, "REPORT", tmp / "T.md"):
                B.write(res, {}, "2026-10-22T00:00:00+00:00", 123)
            g = json.loads((tmp / "gate.json").read_text())
            self.assertTrue(g["markets"]["Corner kicks|side"]["pass"])
            self.assertFalse(g["markets"]["Fouls|side"]["pass"])
            self.assertIn("take_shortfall", g)
            md = (tmp / "T.md").read_text()
            for head in ("## Results by market", "### Model against the baselines", "### Calibration",
                         "## The take threshold", "### Every threshold", "### How much the overround matters",
                         "## Against Betfair's prices", "## Verdict by market"):
                self.assertIn(head, md)
            self.assertNotIn("—", md)                      # no em dashes
        finally:
            shutil.rmtree(tmp)


def _stat_items(**kv):
    return [{"name": k.replace("_", " "), "homeValue": v[0], "awayValue": v[1]} for k, v in kv.items()]


@unittest.skipIf(B is None, "needs numpy, pandas and statsmodels")
class Build(unittest.TestCase):
    """build() on a tiny cache: results scored as settled, and nothing from on or after kick-off."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        events = []
        for i, (h, a) in enumerate([(1, 2), (2, 1), (1, 2)]):
            mid = 100 + i
            events.append({"id": mid, "startTimestamp": 1767312000 + i * 86400 * 7,
                           "tournament": {"category": {"sport": {"slug": "football"}}},
                           "status": {"type": "finished"}, "homeTeam": {"id": h}, "awayTeam": {"id": a},
                           "homeScore": {"current": 1}, "awayScore": {"current": 0}})
            items = dict(Corner_kicks=(5 + i, 3), Fouls=(10, 12), Shots_on_target=(4, 2), Total_shots=(12, 8),
                         Ball_possession=("55%", "45%"))
            if i != 1:
                items["Yellow_cards"] = (2, 1 + i)          # match 101 has no cards row: settled as none
            (self.tmp / f"event_{mid}_statistics.json").write_text(json.dumps(
                {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": _stat_items(**items)}]}]}))
            (self.tmp / f"event_{mid}_lineups.json").write_text(json.dumps(
                {"home": {"formation": "4-4-2"}, "away": {"formation": "4-3-3"}}))
        (self.tmp / "team_1_events_last_0.json").write_text(json.dumps({"events": events}))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_rows(self):
        R = B.build(self.tmp).set_index(["match", "team"])
        self.assertEqual(len(R), 6)
        self.assertEqual(R.loc[(101, 2), "t_Yellow cards"], 0.0)     # missing row -> 0
        self.assertEqual(R.loc[(100, 1), "t_Corner kicks"], 5)
        # the record before each match holds earlier matches only
        self.assertEqual(R.loc[(100, 1), "rec_Corner kicks"], [])
        self.assertEqual(R.loc[(101, 2), "rec_Corner kicks"], [3])     # team 2 away in 100: 3 corners
        self.assertEqual(R.loc[(102, 1), "rec_Corner kicks"], [5, 3])  # 100 at home, 101 away
        self.assertEqual(R.loc[(102, 1), "tot_Corner kicks"], [8, 9])
        self.assertEqual(R.loc[(102, 1), "rec_Yellow cards"], [2, 0.0])


@unittest.skipIf(B is None, "needs numpy, pandas and statsmodels")
class Exchange(unittest.TestCase):
    def test_one_over_per_event_and_line(self):
        rows = {}
        for i, (team, over, res) in enumerate([("A", True, "win"), ("B", True, "win"), ("A", False, "lose"),
                                               ("A", True, None)]):
            rows[str(i)] = {"event_id": 7 if res else 8, "stat": "Match corners", "line": 9.5, "over": over,
                            "team": team, "result": res, "first": {"market": 0.5}, "last": {"market": 0.55}}
        rows["x"] = {"event_id": 7, "stat": "Goals", "line": 1.5, "over": True, "result": "win",
                     "first": {"market": 0.5}, "last": {"market": 0.5}}
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "x.json").write_text(json.dumps(rows))
            out = B.exchange_lines(tmp / "x.json")
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(dict(out), {(7, "Corner kicks"): [{"line": 9.5, "p": 0.55}]})


# ------------------------------------------------------------------ teamlog.py

class TeamLog(unittest.TestCase):
    def setUp(self):
        import teamlog
        self.teamlog = teamlog
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_snapshot_logs_the_model_and_the_verdict(self):
        import playerlines
        tl = self.teamlog
        recs = [{"stats": {"ALL": {"Corner kicks": v, "Yellow cards": 2}}} for v in (4, 6, 5, 7, 3, 6)]
        entry = {"fixture": {"sport": "football"},
                 "teams": [{"name": "Home FC", "id": 1, "side": "home"}, {"name": "Away FC", "id": 2, "side": "away"}],
                 "records": [recs, recs]}
        meta = {"id": 55, "home": "Home FC", "away": "Away FC", "kickoff": 4102444800, "competition": "Test"}
        pp = {"events": {"55": {"ppHome": "Home FC", "team": [
            {"stat": "Corner kicks", "scope": "home", "line": 4.5, "over": True, "price": 1.80, "market": "m"},
            {"stat": "Corner kicks", "scope": "match", "line": 9.5, "over": True, "price": 1.90, "market": "m"},
            {"stat": "Yellow cards", "scope": "away", "line": 1.5, "over": True, "price": 1.50, "market": "m"}]}}}
        (self.tmp / "pp.json").write_text(json.dumps(pp))
        (self.tmp / "mk.json").write_text(json.dumps({"events": {}}))
        models = {"Corner kicks": [{"mu": 5.8, "alpha": 0.02}, {"mu": 4.0, "alpha": 0.02}]}
        with mock.patch.object(tl, "DIR", self.tmp / "pplog"), mock.patch.object(tl, "PP", self.tmp / "pp.json"), \
                mock.patch.object(tl, "MARKETS", self.tmp / "mk.json"), \
                mock.patch.object(playerlines, "upcoming", lambda h: [(entry, meta)]), \
                mock.patch.object(TL, "side_models", lambda e: models), \
                mock.patch.object(TL, "_GATE", dict(GATE)):
            self.assertEqual(tl.snapshot(), 3)
            rows = {(r["stat"], r["scope"]): r for p in sorted((self.tmp / "pplog").glob("team-*.jsonl"))
                    for r in tl._read(p)}
            side = rows[("Corner kicks", "home")]
            self.assertEqual(side["tl_market"], "Corner kicks|side")
            self.assertAlmostEqual(side["model_p"], round(TL.nb_at_least(5, 5.8, 0.02), 4))
            self.assertEqual(side["first"]["verdict"], TL.verdict("Corner kicks|side", side["model_p"], 1.80, GATE))
            self.assertEqual(side["first"]["verdict"], "take")
            match = rows[("Corner kicks", "match")]
            self.assertAlmostEqual(match["model_p"], round(TL.nb_at_least(10, 9.8, 0.02), 4))
            self.assertIn(match["first"]["verdict"], ("ok", "long", "avoid"))        # failed market
            cards = rows[("Yellow cards", "away")]
            self.assertIsNone(cards["model_p"])
            self.assertIsNone(cards["first"]["verdict"])
            # a second snapshot re-prices without adding rows
            self.assertEqual(tl.snapshot(), 0)

    def test_summary_groups_by_market_and_last_verdict(self):
        rows = [
            {"stat": "Corner kicks", "scope": "home", "tl_market": "Corner kicks|side", "model_p": 0.6,
             "result": "win", "first": {"price": 1.8, "verdict": "take"}, "last": {"price": 1.9, "verdict": "take"}},
            {"stat": "Corner kicks", "scope": "away", "tl_market": "Corner kicks|side", "model_p": 0.7,
             "result": "lose", "first": {"price": 1.8, "verdict": "take"}, "last": {"price": 1.7, "verdict": "take"}},
            {"stat": "Fouls", "scope": "home", "result": "win", "first": {"price": 1.5}, "last": {"price": 1.5}},
            {"stat": "Fouls", "scope": "home", "result": None, "first": {"price": 1.5}},
        ]
        s = self.teamlog.summary(rows)
        self.assertEqual(set(s), {("Corner kicks|side", "take"), ("Fouls|side", "unpriced")})
        t = s[("Corner kicks|side", "take")]
        self.assertEqual((t["n"], t["won"]), (2, 1))
        self.assertAlmostEqual(t["pl"], 0.9 - 1)
        self.assertAlmostEqual(t["said"], 0.65)
        self.assertIsNone(s[("Fouls|side", "unpriced")]["said"])


# ------------------------------------------------------------------ report.py

class Attach(unittest.TestCase):
    def payload(self):
        return {"fixtures": [
            {"fixture": {"id": 1, "sport": "football"}, "teams": [{"id": 1, "side": "home"}, {"id": 2, "side": "away"}]},
            {"fixture": {"id": 2, "sport": "basketball"}, "teams": [{"id": 3, "side": "home"}, {"id": 4, "side": "away"}]}]}

    def test_attaches_to_football_only_and_only_passed_stats(self):
        import report
        seen = []

        def fake(entry, stats=None):
            seen.append(sorted(stats))
            return {"Corner kicks": [{"mu": 5.0, "alpha": 0.02}, {"mu": 4.0, "alpha": 0.02}]}
        p = self.payload()
        with mock.patch.object(TL, "_GATE", dict(GATE)), mock.patch.object(TL, "side_models", fake):
            report._attach_team_lines(p)
        self.assertEqual(seen, [["Corner kicks", "Yellow cards"]])
        self.assertIn("teamModel", p["fixtures"][0])
        self.assertNotIn("teamModel", p["fixtures"][1])
        self.assertEqual(sorted(p["teamLineGate"]["markets"]), ["Corner kicks|side", "Yellow cards|match"])

    def test_nothing_passed_nothing_attached(self):
        import report
        p = self.payload()
        with mock.patch.object(TL, "_GATE", {"markets": {"Fouls|side": {"pass": False}}}), \
                mock.patch.object(TL, "side_models", mock.Mock(side_effect=AssertionError("not called"))):
            report._attach_team_lines(p)
        self.assertEqual(p["teamLineGate"]["markets"], {})
        self.assertNotIn("teamModel", p["fixtures"][0])

    def test_a_failure_never_costs_the_report(self):
        import report
        p = self.payload()
        with mock.patch.object(TL, "_GATE", dict(GATE)), \
                mock.patch.object(TL, "side_models", mock.Mock(side_effect=RuntimeError("boom"))):
            report._attach_team_lines(p)
        self.assertNotIn("teamModel", p["fixtures"][0])


PAGE_NAMES = [
    "SPORT", "games", "venue", "tier", "tierOf", "DISPERSION_PRIOR", "CALIBRATION_A", "CALIBRATION_B", "BOOKS", "TEAM_ODDS_POWER", "TEAM_STAT_LABEL",
    "filtered", "isCrossLeague", "goalLambdas", "normName", "fixtureMarket", "ppTeamOrder", "teamExpected",
    "LG_C", "logGamma", "logChoose", "poissonCdf", "negBinCdf", "binomCdf", "dispersion", "probOver", "calibrate",
    "teamModelChance", "verdictOf", "teamValued", "teamGateNote",
]

DRIVER = """
const out = [];
DATA = ALL.fixtures[0];
MARKETS = ALL.markets;
for (const v of teamValued()) out.push({name: v.name, stat: v.stat, line: v.line, over: v.over, price: v.price,
  p: v.p, tested: v.tested, basis: v.basis, verdict: verdictOf(v)});
console.log(JSON.stringify({rows: out, note: teamGateNote()}));
"""


@unittest.skipIf(shutil.which("node") is None, "needs node")
class Page(unittest.TestCase):
    """teamValued() and verdictOf() from the page, against teamlines.py's rule."""

    def run_page(self, payload):
        from tests.test_gamestate import declaration, page_script
        script = page_script(payload)
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "payload.json").write_text(json.dumps(payload))
            prog = tmp / "page.js"
            prog.write_text('const ALL = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));\n'
                            "let DATA = null, MARKETS = null;\n\n"
                            + "\n\n".join(declaration(script, n) for n in PAGE_NAMES) + "\n" + DRIVER)
            done = subprocess.run(["node", str(prog), str(tmp / "payload.json")], capture_output=True,
                                  text=True, timeout=120)
            if done.returncode:
                raise AssertionError(done.stderr[-3000:])
            return json.loads(done.stdout)
        finally:
            shutil.rmtree(tmp)

    def payload(self, gate):
        with gzip.open(ROOT / "tests" / "fixtures" / "gamestate" / "confirmed.json.gz", "rt") as fh:
            p = json.load(fh)
        f = p["fixtures"][0]
        p["fixtures"] = [f]
        home, away = f["teams"][0]["name"], f["teams"][1]["name"]
        models = {"Corner kicks": [{"mu": 7.4, "alpha": 0.018}, {"mu": 3.1, "alpha": 0.018}],
                  "Yellow cards": [{"mu": 1.6, "alpha": 0.0}, {"mu": 2.2, "alpha": 0.0}]}
        f["teamModel"] = models
        p["teamLineGate"] = TL.page_gate(gate)
        lines = [("Corner kicks", "home", 5.5, True, 1.70), ("Corner kicks", "away", 3.5, False, 1.75),
                 ("Corner kicks", "match", 9.5, True, 1.80), ("Yellow cards", "match", 3.5, True, 1.95),
                 ("Yellow cards", "home", 1.5, True, 2.10), ("Corner kicks", "home", 7.5, True, 2.60)]
        p["markets"] = {str(f["fixture"]["id"]): {"pp": {"home": home, "away": away, "team": [
            {"stat": s, "scope": sc, "line": ln, "over": o, "price": pr} for s, sc, ln, o, pr in lines]}}}
        return p, models

    def test_passed_markets_priced_by_the_model_and_judged_by_the_rule(self):
        p, models = self.payload(GATE)
        got = self.run_page(p)
        rows = got["rows"]
        self.assertTrue(rows)
        names = [t["name"] for t in p["fixtures"][0]["teams"]]
        for r in rows:
            scope = "match" if r["name"] == "Match" else "side"
            key = f"{r['stat']}|{scope}"
            t = None if scope == "match" else names.index(r["name"])
            if TL.market_gate(key, GATE):
                self.assertTrue(r["tested"], r)
                self.assertEqual(r["basis"], "model")
                p_py, _ = TL.model_chance(models, r["stat"], "match" if scope == "match" else "home", t,
                                          r["line"], r["over"], GATE)
                self.assertAlmostEqual(r["p"], p_py, places=9)
                self.assertEqual(r["verdict"], TL.verdict(key, r["p"], r["price"], GATE), r)
            else:
                self.assertFalse(r["tested"], r)
                self.assertNotEqual(r["verdict"], "take", r)
        self.assertIn("take", [r["verdict"] for r in rows])       # the fixture is built to have one
        self.assertIn("Only markets that passed the backtest can be take", got["note"])
        self.assertIn("corners (one side) from a 5% edge", got["note"])

    def test_no_gate_no_take(self):
        p, _ = self.payload({"markets": {}})
        got = self.run_page(p)
        self.assertTrue(got["rows"])
        self.assertTrue(all(not r["tested"] and r["verdict"] != "take" for r in got["rows"]))
        self.assertIn("No team market has passed the backtest", got["note"])


if __name__ == "__main__":
    unittest.main()
