"""usfeatures.py leakage checks and the US model audit helpers.

    .venv/bin/python -B -m unittest tests.test_us_audit

Synthetic games only, no cache needed. The leakage tests rebuild the
features after scrambling every box score from one day on and deleting
every later game: a row on that day or before must not change.
"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "usmodel" / "training"))

import usfeatures as U  # noqa: E402
import audit_us as A    # noqa: E402

DAY = 86400
T0 = 1_700_000_000


def synthetic(sport, n_rounds=12, seed=1):
    """Four teams, two games a round (one round a week), eight players a side."""
    rng = np.random.default_rng(seed)
    pos = ["QB", "RB", "WR", "WR", "TE", "LB", "CB", "SAF"] if sport == "nfl" else ["G", "G", "F", "F", "C", "G", "F", "C"]
    stats = list(U.NFL_P.values()) if sport == "nfl" else [v for v in U.NBA_P.values() if v != "secs"]
    M, T, P = [], [], []
    mid = 1
    for rnd in range(n_rounds):
        pairs = [(1, 2), (3, 4)] if rnd % 2 == 0 else [(1, 3), (2, 4)]
        for k, (h, a) in enumerate(pairs):
            ts = T0 + rnd * 7 * DAY + k * 3 * 3600
            hs, as_ = int(rng.integers(10, 40)), int(rng.integers(10, 40))
            M.append(dict(match=mid, ts=ts, season=2025, home=h, away=a, hs=hs, as_=as_,
                          home_name=str(h), away_name=str(a), playoff=False))
            for team, opp, home, pf, pa in ((h, a, 1, hs, as_), (a, h, 0, as_, hs)):
                T.append(dict(match=mid, ts=ts, season=2025, team=team, opp=opp, home=home,
                              pts_for=float(pf), pts_against=float(pa),
                              **{c: float(rng.integers(0, 300)) for c in U.CFG[sport]["team"]
                                 if c.startswith(("f_", "a_"))}))
                for j, p in enumerate(pos):
                    r = dict(match=mid, ts=ts, season=2025, pid=team * 100 + j, name=f"p{team}_{j}",
                             team=team, opp=opp, home=home, pos=p, starter=int(j < 5), has_stats=1)
                    for s in stats:
                        r[s] = float(rng.integers(0, 12))
                    if sport == "nba":
                        r["mins"] = float(rng.integers(5, 40))
                    P.append(r)
            mid += 1
    M, T, P = pd.DataFrame(M), pd.DataFrame(T), pd.DataFrame(P)
    if sport == "nba":
        P["pra"] = P.points + P.rebounds + P.assists
        P["pr"], P["pa"], P["ra"] = P.points + P.rebounds, P.points + P.assists, P.rebounds + P.assists
    else:
        P["rush_rec_yds"], P["pass_rush_yds"] = P.rush_yds + P.rec_yds, P.pass_yds + P.rush_yds
    return M, T, P


def scramble_from(M, T, P, cut, seed=9):
    """Every result and box score from `cut` on replaced by noise; later days dropped."""
    rng = np.random.default_rng(seed)
    end = cut + DAY
    M, T, P = M[M.ts < end].copy(), T[T.ts < end].copy(), P[P.ts < end].copy()
    m = M.ts >= cut
    M.loc[m, "hs"], M.loc[m, "as_"] = rng.integers(0, 60, m.sum()), rng.integers(0, 60, m.sum())
    t = T.ts >= cut
    for c in T.columns:
        if c.startswith(("f_", "a_", "pts_")):
            T[c] = T[c].astype(float)
            T.loc[t, c] = rng.random(t.sum()) * 500
    p = P.ts >= cut
    for c in P.columns:
        if P[c].dtype.kind == "f":
            P.loc[p, c] = np.floor(rng.random(p.sum()) * 40) + 1
    return M, T, P


def pre_game(F):
    return F[[c for c in F.columns if not c.startswith("y_")]].set_index(["match", "pid"]).sort_index()


class NoLookahead(unittest.TestCase):

    def check(self, sport):
        M, T, P = synthetic(sport)
        full = U.features(M, T, P, sport)
        cut = T0 + 6 * 7 * DAY                       # round 6: both of its games
        M2, T2, P2 = scramble_from(M, T, P, cut)
        part = U.features(M2, T2, P2, sport)
        a = pre_game(full[full.ts < cut + DAY])
        b = pre_game(part)
        self.assertEqual(len(a), len(b))
        self.assertGreater((a.ts >= cut).sum(), 0)
        b = b.loc[a.index]
        for c in a.columns:
            if a[c].dtype.kind in "fi":
                diff = (a[c].astype(float).fillna(-1e9) - b[c].astype(float).fillna(-1e9)).abs().max()
                self.assertLess(diff, 1e-9, f"{sport} {c} moves with same-day or later results")

    def test_nfl(self):
        self.check("nfl")

    def test_nba(self):
        self.check("nba")

    def test_same_day_earlier_game_is_not_seen(self):
        """Two games hours apart on one day: the later one sees neither's box score."""
        M, T, P = synthetic("nfl")
        F = U.features(M, T, P, "nfl")
        day = T0 + 6 * 7 * DAY
        late = F[F.ts == day + 3 * 3600]
        P2 = P.copy()
        early = P2.ts == day
        P2.loc[early, "rec"] = 99.0
        F2 = U.features(M, T, P2, "nfl")
        late2 = F2[F2.ts == day + 3 * 3600]
        pd.testing.assert_series_equal(late.oc_rec.reset_index(drop=True), late2.oc_rec.reset_index(drop=True))


class ZeroStatGames(unittest.TestCase):
    """An NFL player in the line-up with no statistics played a game of zeros."""

    def setUp(self):
        M, T, P = synthetic("nfl")
        self.wr = 100 + 2                              # team 1's first WR
        self.blank = P[(P.pid == self.wr)].match.iloc[7]
        stat_cols = [c for c in P.columns if P[c].dtype.kind == "f"]
        b = (P.pid == self.wr) & (P.match == self.blank)
        P.loc[b, stat_cols] = 0.0
        P.loc[b, "has_stats"] = 0
        self.M, self.T, self.P = M, T, P
        self.F = U.features(M, T, P, "nfl")

    def test_blank_game_is_a_row(self):
        row = self.F[(self.F.pid == self.wr) & (self.F.match == self.blank)]
        self.assertEqual(len(row), 1, "a no-catch game must be scored, not dropped")
        self.assertEqual(float(row.y_rec.iloc[0]), 0.0)

    def test_blank_game_enters_form(self):
        mine = self.F[self.F.pid == self.wr].sort_values("ts")
        after = mine[mine.ts > self.P[self.P.match == self.blank].ts.iloc[0]].iloc[0]
        self.assertEqual(after.n, 8)                   # seven earlier games and the blank one
        hist = self.P[(self.P.pid == self.wr) & (self.P.ts < after.ts)].sort_values("ts")
        self.assertAlmostEqual(after.rec_m3, hist.rec.tail(3).mean())

    def test_nba_zero_minutes_still_not_a_row(self):
        M, T, P = synthetic("nba")
        pid = 100 + 1
        m = P[P.pid == pid].match.iloc[7]
        P.loc[(P.pid == pid) & (P.match == m), "mins"] = 0.0
        F = U.features(M, T, P, "nba")
        self.assertEqual(len(F[(F.pid == pid) & (F.match == m)]), 0)

    def test_upcoming_regulars_count_blank_games(self):
        games = [dict(match=999, ts=int(self.M.ts.max()) + 7 * DAY, home=1, away=2, season=2025)]
        P = self.P.copy()
        last5 = P[P.team == 1].sort_values("ts").match.unique()[-5:]
        # the WR's last five: blank, blank, missing, missing, missing
        P = P[~((P.pid == self.wr) & P.match.isin(last5[2:]))]
        z = (P.pid == self.wr) & P.match.isin(last5[:2])
        P.loc[z, "has_stats"] = 0
        _, _, P2 = U.add_upcoming(self.M, self.T, P, games, "nfl")
        self.assertIn(self.wr, set(P2[P2.upcoming == 1].pid))


class Folds(unittest.TestCase):

    def test_seasons(self):
        ts = np.arange(1000) * DAY + T0
        season = np.repeat([2020, 2021, 2022, 2023, 2024], 200)
        b = A.folds(ts, season, min_history=0.15, by="season")
        self.assertEqual([x[0] for x in b], ["2021", "2022", "2023", "2024"])
        for name, start, end in b:
            self.assertTrue((ts[(ts >= start) & (ts < end)] == ts[season == int(name)]).all())

    def test_auto_falls_back_to_months(self):
        ts = T0 + np.arange(3000) * 3600 * 2.0         # 250 days, one season
        b = A.folds(ts, np.full(len(ts), 2025), min_history=0.3, min_rows=300)
        self.assertGreaterEqual(len(b), 3)
        starts = [x[1] for x in b]
        self.assertEqual(starts, sorted(starts))
        self.assertGreaterEqual((ts < starts[0]).mean(), 0.3)

    def test_split_history_is_before_the_block(self):
        ts = np.arange(100, dtype=float)
        tr, va = A.split_history(ts, 80)
        self.assertTrue(ts[tr].max() < ts[va].min())
        self.assertTrue(ts[va].max() < 80)
        self.assertEqual(va.sum(), 20)


class Betting(unittest.TestCase):

    def test_take_rule(self):
        # p, price over, price under, n, days rest -> side
        cases = [
            (0.60, 1.80, 2.00, 10, 7, 1),    # edge 8%: over
            (0.60, 1.74, 2.00, 10, 7, -1),   # edge 4.4%: no
            (0.40, 2.00, 1.80, 10, 7, 0),    # under 60% at 1.80: 8%
            (0.45, 2.40, 1.60, 10, 7, -1),   # over has edge but under 50%: long shot
            (0.70, 2.00, 2.00, 10, 7, -1),   # edge 40%: over the 30% guard
            (0.60, 1.80, 2.00, 4, 7, -1),    # four games
            (0.60, 1.80, 2.00, 10, 90, -1),  # stale
        ]
        p, po, pu, n, d, want = (np.array(x) for x in zip(*cases))
        side, price, edge = A.take_bets(p, po, pu, n, d)
        self.assertEqual(side.tolist(), want.tolist())
        self.assertAlmostEqual(edge[0], 0.08)

    def test_settle(self):
        side = np.array([1, 0, 1, -1])
        price = np.array([2.0, 1.5, 3.0, np.nan])
        y = np.array([1, 1, 0, 1])
        prof = A.settle(side, price, y)
        self.assertEqual(prof[:3].tolist(), [1.0, -1.0, -1.0])
        self.assertTrue(np.isnan(prof[3]))

    def test_book_margin(self):
        po, pu = A.book_prices(np.array([0.5]), 0.075)
        self.assertAlmostEqual(1 / po[0] + 1 / pu[0], 1.075)

    def test_roi_interval(self):
        rng = np.random.default_rng(0)
        prof = np.where(rng.random(2000) < 0.5, 0.9, -1.0)
        r = A.roi_ci(prof, np.repeat(np.arange(200), 10), n_boot=500)
        self.assertEqual(r["bets"], 2000)
        self.assertLess(r["lo"], r["roi"])
        self.assertLess(r["roi"], r["hi"])
        self.assertLess(r["roi"], 0)


class Bootstrap(unittest.TestCase):

    def test_gain_sign_and_cluster_width(self):
        rng = np.random.default_rng(3)
        n_games, per = 300, 20
        g = np.repeat(np.arange(n_games), per)
        truth = rng.random(n_games * per)
        y = (rng.random(len(truth)) < truth).astype(int)
        good, flat = truth, np.full(len(truth), 0.5)
        pt, lo, hi, p0 = A.loss_gain_ci(y, flat, good, g, n_boot=400)
        self.assertGreater(lo, 0)
        self.assertLess(p0, 0.01)
        # a game-level shock shared by all lines in a game: the cluster
        # interval must be wider than one that treats lines as independent
        shock = np.repeat(rng.normal(0, 1.5, n_games), per)
        y2 = (rng.random(len(truth)) < A.sig(shock)).astype(int)
        _, l1, h1, _ = A.loss_gain_ci(y2, flat, good, g, n_boot=400)
        _, l2, h2, _ = A.loss_gain_ci(y2, flat, good, np.arange(len(g)), n_boot=400)
        self.assertGreater(h1 - l1, h2 - l2)


class Summary(unittest.TestCase):
    """summarise() and audit_report.tables() on made-up predictions."""

    def test_tables(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.skipTest("scikit-learn not installed")
        import audit_report
        rng = np.random.default_rng(5)
        n = 1200
        truth = rng.random(n)
        df = pd.DataFrame({
            "target": np.where(np.arange(n) % 2, "rec", "pass_att"), "y": (rng.random(n) < truth).astype(int),
            "match": np.repeat(np.arange(n // 12), 12), "pid": np.arange(n) % 40,
            "fold": np.where(np.arange(n) < n / 2, "2025", "2026"), "use_blend": True,
            "w_model": 0.6, "w_site": 0.5, "n_games": 10, "days_rest": 7.0})
        noisy = np.clip(truth + rng.normal(0, 0.2, n), 0.02, 0.98)
        for v in ("site", "site_fair"):
            df[f"p_{v}"] = noisy
        for v in ("new", "blend", "live"):
            df[f"p_{v}"] = np.clip(truth, 0.02, 0.98)
        d = A.summarise(df, "nfl", n_boot=200)
        self.assertEqual(set(d["markets"]), {"rec", "pass_att"})
        self.assertTrue(d["markets"]["rec"]["gain_vs_site_fair"]["survives"])
        self.assertGreater(d["betting"]["rec"]["live|site_fair|0.075"]["bets"], 0)
        md = audit_report.tables(d, before=d)
        self.assertIn("| rec |", md)
        self.assertIn("zero-stat fix", md)


if __name__ == "__main__":
    unittest.main()
