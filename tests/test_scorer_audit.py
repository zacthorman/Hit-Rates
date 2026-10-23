"""scorer_audit.py and the replay hook it added to fmodel_live.features.

    python -B -m unittest tests.test_scorer_audit

The replay test builds a small league in memory, so it needs no cache: a
finished match emitted from the history must get exactly the features it
would have got as an upcoming fixture the day before, which is what lets the
audit claim it scored the page's own numbers.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fmodel_live as FL  # noqa: E402
import scorer_audit as SA  # noqa: E402


def _league(n_matches=14, seed=3):
    """Three teams, twelve players each (one keeper, one substitute), round robin."""
    rng = np.random.default_rng(seed)
    teams = [101, 102, 103]
    M, T, P = [], [], []
    ts = 1_780_000_000
    for i in range(n_matches):
        h, a = teams[i % 3], teams[(i + 1) % 3]
        mid = 9000 + i
        hg, ag = int(rng.integers(0, 4)), int(rng.integers(0, 4))
        M.append({"match": mid, "ts": ts, "comp_id": 17, "home": h, "away": a, "hg": hg, "ag": ag})
        for side, team, opp in (("home", h, a), ("away", a, h)):
            row = {"match": mid, "ts": ts, "team": team, "opp": opp, "home": int(side == "home")}
            for k in FL.TSTATS:
                row["f_" + k] = float(rng.integers(5, 60))
                row["a_" + k] = float(rng.integers(5, 60))
            T.append(row)
            sizes = [4, 4, 2]
            for j in range(12):
                pid = team * 100 + j
                starter = j < 11
                pos = "G" if j == 0 else "D" if j <= 4 else "M" if j <= 8 else "F"
                if j == 0 or not starter:
                    depth = lat = ls = None
                else:
                    li = 0 if j <= 4 else 1 if j <= 8 else 2
                    within = (j - 1) if li == 0 else (j - 5) if li == 1 else (j - 9)
                    depth, lat, ls = li / 2, within / (sizes[li] - 1), sizes[li]
                r = {"match": mid, "ts": ts, "team": team, "opp": opp, "home": int(side == "home"),
                     "pid": pid, "name": f"P{pid}", "pos": pos, "starter": int(starter),
                     "depth": depth, "lat": lat, "linesize": ls,
                     "mins": float(rng.integers(60, 91)) if starter else float(rng.integers(0, 30))}
                for v in FL.PSTATS.values():
                    r[v] = float(rng.integers(0, 4))
                for s in FL.COVER:
                    r["cov_" + s] = True
                P.append(r)
        ts += 4 * 86400
    return pd.DataFrame(M), pd.DataFrame(T), pd.DataFrame(P)


def _as_upcoming(M, T, P, mid):
    """The match as fmodel_live.upcoming() would hand it over: no result, no numbers, starters only."""
    M = M.copy()
    M.loc[M.match == mid, ["hg", "ag"]] = None
    T = T.copy()
    for k in FL.TSTATS:
        T.loc[T.match == mid, "f_" + k] = np.nan
        T.loc[T.match == mid, "a_" + k] = np.nan
    P = P[(P.match != mid) | (P.starter == 1)].copy()
    sel = P.match == mid
    P.loc[sel, "mins"] = 90
    for v in FL.PSTATS.values():
        P.loc[sel, v] = np.nan
    for s in FL.COVER:
        P.loc[sel, "cov_" + s] = False
    return M, T, P


def _rows(F, mid):
    return F[F.match == mid].sort_values("pid").reset_index(drop=True)


class ReplayHook(unittest.TestCase):
    def test_emitted_rows_match_the_live_path(self):
        M, T, P = _league()
        for mid in (9008, 9013):
            keep = M.ts <= int(M.loc[M.match == mid, "ts"].iloc[0])
            UM, UT, UP = _as_upcoming(M[keep], T[T.match.isin(M[keep].match)], P[P.match.isin(M[keep].match)], mid)
            live = _rows(FL.features(UM, UT, UP, {mid}), mid)
            replay = _rows(FL.features(M, T, P, set(), emit={mid}), mid)
            self.assertGreater(len(live), 0)
            self.assertEqual(list(live.pid), list(replay.pid))
            cols = sorted(set(live.columns) & set(replay.columns))
            pd.testing.assert_frame_equal(live[cols], replay[cols], check_dtype=False)

    def test_default_is_unchanged(self):
        M, T, P = _league()
        a = FL.features(M, T, P, {9013})
        b = FL.features(M, T, P, {9013}, emit=None)
        pd.testing.assert_frame_equal(a, b)
        self.assertTrue(set(a.match) <= {9013})

    def test_emit_still_writes_history(self):
        # emitting a match must not keep it out of later matches' histories
        M, T, P = _league()
        with_emit = _rows(FL.features(M, T, P, set(), emit={9008, 9013}), 9013)
        without = _rows(FL.features(M, T, P, set(), emit={9013}), 9013)
        pd.testing.assert_frame_equal(with_emit, without)


class FastTrees(unittest.TestCase):
    def test_tree_predict_equals_the_page_scorer(self):
        import json
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fmodel"))
        from fmodel_trees import Model
        root = Path(__file__).resolve().parents[1] / "fmodel"
        meta = json.loads((root / "meta.json").read_text())
        rng = np.random.default_rng(0)
        for name in ("goals_1", "shots_1", "sot_2"):
            feats = meta["lines"][name]["features"]
            X = rng.normal(0, 3, (200, len(feats)))
            # categorical columns get real category codes, some missing
            for j, f in enumerate(feats):
                if f in ("comp_c", "pos_c"):
                    X[:, j] = rng.integers(-1, 40 if f == "comp_c" else 4, len(X))
            X[rng.random(X.shape) < 0.15] = np.nan
            X[rng.random(X.shape) < 0.05] = 0.0
            m = Model(root / f"{name}.json")
            got = sum(SA.tree_predict(t, X) for t in m.trees)
            want = sum(t.predict(X) for t in m.trees)
            np.testing.assert_allclose(got, want, rtol=0, atol=1e-12)


class Scoring(unittest.TestCase):
    def test_log_loss_and_brier(self):
        self.assertAlmostEqual(SA.log_loss([0.5, 0.5], [1, 0]), math.log(2))
        self.assertAlmostEqual(SA.brier([0.8, 0.2], [1, 0]), 0.04)
        # a raw record of 10/10 that misses is clipped, not infinite
        self.assertAlmostEqual(SA.log_loss([1.0], [0]), -math.log(SA.CLIP))

    def test_bands_and_ece(self):
        p = [0.15] * 10 + [0.75] * 10
        y = [0] * 9 + [1] + [1] * 5 + [0] * 5
        b = SA.bands(p, y)
        self.assertEqual([(x[2], round(x[3], 2), round(x[4], 2)) for x in b], [(10, 0.15, 0.1), (10, 0.75, 0.5)])
        self.assertAlmostEqual(SA.ece(p, y), (0.05 + 0.25) / 2)

    def test_logistic_recovers_a_known_map(self):
        rng = np.random.default_rng(1)
        z = rng.normal(0, 1.2, 40000)
        p = 1 / (1 + np.exp(-z))
        truth = 1 / (1 + np.exp(-(-0.3 + 0.8 * z)))
        y = (rng.random(len(z)) < truth).astype(float)
        S = pd.DataFrame(index=range(len(z)))
        b = SA.fit_fix(p, y, S, [])
        self.assertAlmostEqual(b[0], -0.3, delta=0.05)
        self.assertAlmostEqual(b[1], 0.8, delta=0.05)

    def test_identity_fix_changes_nothing(self):
        p = np.array([0.05, 0.3, 0.71, 0.95])
        S = pd.DataFrame({"short_mins": [0, 1, 0, 1]})
        out = SA.apply_fix(np.array([0.0, 1.0, 0.0]), p, S, ["short_mins"])
        np.testing.assert_allclose(out, p, atol=1e-9)


class PageNumbers(unittest.TestCase):
    def test_penalty_game(self):
        self.assertTrue(SA.is_penalty_game(1, 0.7884))
        self.assertTrue(SA.is_penalty_game(1, 0.76))
        self.assertFalse(SA.is_penalty_game(2, 0.7884))
        self.assertFalse(SA.is_penalty_game(1, 0.42))
        self.assertFalse(SA.is_penalty_game(1, None))

    def test_scorecase_matches_the_profile(self):
        # report.py scoreCase: 0.6 xG + 0.4 goals per 90, median minutes, half recent half all
        apps = [{"mins": 90, "goals": 1, "xg": 0.5}, {"mins": 90, "goals": 0, "xg": 0.3},
                {"mins": 60, "goals": 0, "xg": 0.2}, {"mins": 20, "goals": 1, "xg": 0.6}]
        rate = 0.6 * (1.0 / 240 * 90) + 0.4 * (1 / 240 * 90)
        lam = rate * 90 / 90
        self.assertAlmostEqual(SA.scorecase_p(apps, apps), 1 - math.exp(-lam))
        self.assertIsNone(SA.scorecase_p(apps[:2], apps))


if __name__ == "__main__":
    unittest.main()


class TonightBlend(unittest.TestCase):
    """context.gs_adjust weighs fmodel against the shrunk record by fmodel/tonight_blend.json."""

    def setUp(self):
        import context
        self.context = context
        self.saved = (dict(context._FMODEL), dict(context._BLEND))
        context._FMODEL.clear()
        context._FMODEL["events"] = {"55": {"players": {"A Striker": {"lines": {
            "Goals": {"1": 0.12}, "Shots": {"1": 0.80, "2": 0.40}}}}}}
        context._BLEND.clear()
        context._BLEND["weights"] = {"Goals|1": 1.0, "Shots|2": 0.9}
        self.entry = {"fixture": {"id": 55}, "teams": [{"name": "Home", "side": "home"},
                                                         {"name": "Away", "side": "away"}]}

    def tearDown(self):
        self.context._FMODEL.clear()
        self.context._FMODEL.update(self.saved[0])
        self.context._BLEND.clear()
        self.context._BLEND.update(self.saved[1])

    def leg(self, stat, line, **kw):
        return {"player": "A Striker", "team": "Home", "stat": stat, "line": line, "over": True,
                "period": "ALL", "hits": 6, "total": 20, "pShrunk": 0.375, **kw}

    def test_weights_from_the_file(self):
        g = self.context.gs_adjust(self.leg("Goals", 0.5), self.entry, None)
        self.assertAlmostEqual(g["chance"], 0.12)
        self.assertAlmostEqual(g["base"], 0.375)
        g = self.context.gs_adjust(self.leg("Shots", 1.5), self.entry, None)
        self.assertAlmostEqual(g["chance"], 0.9 * 0.40 + 0.1 * 0.375)

    def test_a_line_not_in_the_file_keeps_half_and_half(self):
        g = self.context.gs_adjust(self.leg("Shots", 0.5), self.entry, None)
        self.assertAlmostEqual(g["chance"], (0.80 + 0.375) / 2)
        self.context._BLEND["weights"] = {"Shots|1": 7}       # nonsense weight: ignored
        self.assertAlmostEqual(self.context.blend_weight("Shots", 1), 0.5)

    def test_exchange_priced_and_unders_untouched(self):
        g = self.context.gs_adjust(self.leg("Goals", 0.5, chance_model=0.2), self.entry, None)
        self.assertAlmostEqual(g["chance"], 0.375)
        self.assertIsNone(self.context.gs_adjust(self.leg("Goals", 0.5, over=False), self.entry, None))

    def test_written_weights_are_the_audited_ones(self):
        import json
        path = Path(__file__).resolve().parents[1] / "fmodel" / "tonight_blend.json"
        if not path.exists():
            self.skipTest("no tonight_blend.json")
        w = json.loads(path.read_text())["weights"]
        self.assertTrue(set(w) <= set(SA.LEG_KEY.values()))
        self.assertTrue(all(0 <= v <= 1 for v in w.values()))


class PageFallback(unittest.TestCase):
    """report.py's siteCalibrated, run in node on the page as rendered."""

    def setUp(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node is not installed")

    def _script(self):
        import gzip
        import json
        from tests.test_gamestate import FIXTURES, page_script
        with gzip.open(FIXTURES / "confirmed.json.gz", "rt", encoding="utf-8") as f:
            return page_script(json.load(f))

    def test_page_matches_the_audit(self):
        import json
        import subprocess
        import tempfile
        import report
        from tests.test_gamestate import declaration
        script = self._script()
        self.assertNotIn("__SITE_CALIB__", script)
        maps = report.site_calibration()
        if not maps:
            self.skipTest("no fmodel/site_calib.json")
        cases = [{"p": 0.31, "n": 12, "source": "model", "stat": "Shots on target", "line": 1.5, "over": True},
                 {"p": 0.69, "n": 12, "source": "model", "stat": "Shots on target", "line": 1.5, "over": False},
                 {"p": 0.55, "n": 9, "source": "record", "stat": "Shots", "line": 0.5, "over": True},
                 {"p": 0.55, "n": 2, "source": "blend", "stat": "Shots", "line": 0.5, "over": True},
                 {"p": 0.40, "n": 12, "source": "model", "stat": "Passes", "line": 20.5, "over": True}]
        prog = ("\n\n".join(declaration(script, n) for n in ("fairOdds", "SPORT", "SITE_CALIB", "siteCalibrated"))
                + "\nconst cases = " + json.dumps(cases) + ";\n"
                + "console.log(JSON.stringify(cases.map(c => siteCalibrated({p: c.p, n: c.n, source: c.source, "
                  "need: 1 / c.p}, c.stat, c.line, c.over).p)));\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.js"
            path.write_text(prog)
            out = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)

        def want(c):
            m = maps.get(f"{c['stat']}|{int(c['line'] + 0.5)}")
            if not m or c["source"] == "blend" or c["n"] < 3:
                return c["p"]
            po = c["p"] if c["over"] else 1 - c["p"]
            q = 1 / (1 + math.exp(-(m[0] + m[1] * math.log(po / (1 - po)))))
            return q if c["over"] else 1 - q
        for c, g in zip(cases, got):
            self.assertAlmostEqual(g, want(c), places=12)
        # the under and the over of one line still add to one
        self.assertAlmostEqual(got[0] + got[1], 1.0, places=12)

    def test_whole_script_parses(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.js"
            path.write_text(self._script())
            out = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)


class TonightLine(unittest.TestCase):
    def test_goals_leg_shows_no_made_up_factor(self):
        import tonight
        leg = {"player": "A Striker", "team": "Home", "stat": "Goals", "line": 0.5, "over": True,
               "period": "ALL", "hits": 6, "total": 20, "fair": 1 / 0.12,
               "fixture": {"id": 55, "home": "Home", "away": "Away"},
               "gs": {"chance": 0.12, "base": 0.375, "model": 0.12, "plain": 0.12, "factor": 1.0,
                      "oppf": None, "kind": "player model"}}
        entry = {"fixture": {"id": 55}, "teams": [{"name": "Home", "side": "home"},
                                                   {"name": "Away", "side": "away"}], "records": [[], []]}
        html = tonight.leg_row(leg, entry)
        self.assertIn("Backtested player model <b>12%</b>. The record adds nothing on this line", html)
        self.assertNotIn("opponent &times;", html)
