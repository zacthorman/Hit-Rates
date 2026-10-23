"""scoremodels.py: score grids, scoring rules and the goal models.

    .venv/bin/python -B -m unittest tests.test_scoremodels

Synthetic leagues only, so the tests know the true answer.
"""
import math
import random
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scoremodels as sm  # noqa: E402

DAY = 86400


def league(n_teams=12, rounds=6, seed=1, home=0.25, l3=0.0):
    """A double round robin repeated, goals drawn from known strengths."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    att = {t: rng.gauss(0, 0.3) for t in range(n_teams)}
    dfn = {t: rng.gauss(0, 0.3) for t in range(n_teams)}
    out, ts = [], 1_700_000_000
    for _ in range(rounds):
        for h in range(n_teams):
            for a in range(n_teams):
                if h == a:
                    continue
                lh = math.exp(0.1 + home + att[h] - dfn[a])
                la = math.exp(0.1 + att[a] - dfn[h])
                shared = np_rng.poisson(l3) if l3 else 0
                out.append({"home": h, "away": a, "ts": ts,
                            "hg": int(np_rng.poisson(lh)) + shared, "ag": int(np_rng.poisson(la)) + shared})
                ts += 3600
    return out, att, dfn, ts


class Grids(unittest.TestCase):
    def test_poisson_grid_sums_to_one_and_matches_marginals(self):
        g = sm.poisson_grid(1.6, 1.1)
        self.assertAlmostEqual(g.sum(), 1.0, places=5)
        self.assertAlmostEqual((g.sum(axis=1) * np.arange(g.shape[0])).sum(), 1.6, places=4)

    def test_dc_moves_only_the_low_scores(self):
        p, d = sm.poisson_grid(1.4, 1.2), sm.dc_grid(1.4, 1.2, -0.1)
        self.assertGreater(d[0, 0], p[0, 0])
        self.assertGreater(d[1, 1], p[1, 1])
        self.assertLess(d[1, 0], p[1, 0])
        self.assertTrue(np.allclose(d[2:, :], p[2:, :]))
        self.assertAlmostEqual(d.sum(), 1.0, places=2)

    def test_bivariate_reduces_to_poisson_and_adds_draws(self):
        self.assertTrue(np.allclose(sm.bivariate_grid(1.3, 1.0, 0.0), sm.poisson_grid(1.3, 1.0)))
        # Same marginal means, shared component: more draws.
        b = sm.bivariate_grid(1.2, 0.9, 0.1)
        p = sm.poisson_grid(1.3, 1.0)
        self.assertAlmostEqual(b.sum(), 1.0, places=6)
        self.assertAlmostEqual((b.sum(axis=1) * np.arange(b.shape[0])).sum(), 1.3, places=5)
        self.assertGreater(sm.outcome_probs(b)[1], sm.outcome_probs(p)[1])

    def test_outcome_probs_and_pick(self):
        ph, pd, pa = sm.outcome_probs(sm.poisson_grid(2.2, 0.6))
        self.assertAlmostEqual(ph + pd + pa, 1.0)
        self.assertGreater(ph, pa)
        self.assertEqual(sm.pick_score(sm.poisson_grid(2.2, 0.6))[:2], (2, 0))
        # Level game: the draw is not the likeliest result, so the pick is a win score.
        i, j, _ = sm.pick_score(sm.poisson_grid(1.35, 1.3))
        self.assertGreater(i, j)


class Scoring(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(sm.rps((1, 0, 0), 0), 0.0)
        self.assertAlmostEqual(sm.rps((0, 0, 1), 0), 1.0)
        # A draw forecast is closer to a home win than an away-win forecast is.
        self.assertLess(sm.rps((0, 1, 0), 0), sm.rps((0, 0, 1), 0))
        self.assertAlmostEqual(sm.brier((0.5, 0.3, 0.2), 1), 0.25 + 0.49 + 0.04)
        self.assertAlmostEqual(sm.log_loss((0.5, 0.3, 0.2), 2), -math.log(0.2))
        self.assertEqual([sm.outcome_index(*s) for s in ((2, 1), (0, 0), (1, 3))], [0, 1, 2])


class Fits(unittest.TestCase):
    def test_poisson_recovers_strengths(self):
        ms, att, dfn, now = league(rounds=10)
        m = sm.TeamGoals("poisson", half_life=10_000, ridge=0.01).fit(ms, now)
        est = np.array([m.att[m.index[t]] for t in range(12)])
        true = np.array([att[t] for t in range(12)])
        self.assertGreater(np.corrcoef(est, true)[0, 1], 0.9)
        self.assertAlmostEqual(m.home, 0.25, delta=0.08)

    def test_nothing_on_or_after_now_is_used(self):
        ms, _, _, now = league(rounds=2)
        cut = ms[len(ms) // 2]["ts"]
        a = sm.TeamGoals("poisson").fit(ms, cut)
        b = sm.TeamGoals("poisson").fit(ms[:len(ms) // 2], cut)
        self.assertEqual(a.n_fit, b.n_fit)
        self.assertAlmostEqual(a.mu, b.mu, places=8)

    def test_ridge_pulls_a_rarely_seen_side_to_average(self):
        ms, _, _, now = league(rounds=3)
        ms.append({"home": 99, "away": 0, "ts": now - 10, "hg": 6, "ag": 0})
        loose = sm.TeamGoals("poisson", ridge=0.01).fit(ms, now)
        tight = sm.TeamGoals("poisson", ridge=8.0).fit(ms, now)
        self.assertLess(tight.att[tight.index[99]], loose.att[loose.index[99]])
        self.assertFalse(tight.knows(12345))
        self.assertGreater(sum(sm.outcome_probs(tight.grid(12345, 0))), 0.99)

    def test_dc_rho_and_bivariate_lambda3(self):
        ms, _, _, now = league(rounds=20, l3=0.25, seed=5)
        dc = sm.TeamGoals("dc", half_life=10_000, ridge=0.5).fit(ms, now)
        self.assertTrue(-0.3 < dc.rho < 0.3)
        bp = sm.TeamGoals("bivariate", half_life=10_000, ridge=0.5).fit(ms, now)
        # The maximum-likelihood figure on this sample is 0.21; the profile
        # likelihood is flat to within a point between 0.18 and 0.27.
        self.assertAlmostEqual(bp.l3, 0.25, delta=0.08)
        none, _, _, now = league(rounds=8, seed=4)
        self.assertLess(sm.TeamGoals("bivariate", half_life=10_000, ridge=0.5).fit(none, now).l3, 0.05)
        eh, ea = bp.expected_goals(0, 1)
        lh, la = bp.means(0, 1)
        self.assertAlmostEqual(eh - lh, bp.l3)

    def test_decay_halves_at_half_life(self):
        w = sm.decay_weights(np.array([0.0, 100 * DAY]), 100 * DAY, 100)
        self.assertAlmostEqual(w[0], 0.5)
        self.assertAlmostEqual(w[1], 1.0)


class Elo(unittest.TestCase):
    def test_gap_raises_home_mean(self):
        rng = np.random.default_rng(0)
        gaps = rng.normal(0, 0.5, 4000)
        lev = rng.normal(math.log(1.35), 0.05, 4000)
        hg = rng.poisson(np.exp(0.3 + 0.6 * gaps))
        ag = rng.poisson(np.exp(0.0 - 0.6 * gaps))
        m = sm.EloGoals().fit(gaps, lev, hg, ag)
        hi, lo = m.means(0.5, math.log(1.35)), m.means(-0.5, math.log(1.35))
        self.assertGreater(hi[0], lo[0])
        self.assertLess(hi[1], lo[1])


if __name__ == "__main__":
    unittest.main()
