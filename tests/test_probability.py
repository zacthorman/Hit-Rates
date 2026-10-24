"""probability.py and the old names that now point at it.

    python -B -m unittest tests.test_probability

Each old helper was moved into probability.py on 22 October. The copies below
are the bodies as they were before the move, and every test asserts the new
function returns exactly the same float (==, not almost-equal) over a spread
of inputs, so the pages cannot drift by a last bit.
"""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bettrack       # noqa: E402
import context        # noqa: E402
import darts_market   # noqa: E402
import darts_model    # noqa: E402
import exchange_eval  # noqa: E402
import learner        # noqa: E402
import market_prices  # noqa: E402
import match_result   # noqa: E402
import model          # noqa: E402
import probability    # noqa: E402
import review         # noqa: E402
import strength       # noqa: E402
import weekend        # noqa: E402


# ------------------------------------------------- the bodies before 22 Oct

def old_wilson_low(hits, total, z=1.96):
    if total == 0:
        return 0.0
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - spread) / denom)


def old_wilson(hits, total, z=1.96):
    if not total:
        return 0.0, 1.0
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - spread) / denom), min(1.0, (centre + spread) / denom)


def old_platt(p, a, b):
    p = min(1 - 1e-9, max(1e-9, p))
    z = a + b * math.log(p / (1 - p))
    return 1 / (1 + math.exp(-z))


def old_logit(p, eps):
    if eps == 1e-4:
        p = min(max(p, 1e-4), 1 - 1e-4)
    else:
        p = min(max(p, 1e-3), 1 - 1e-3)
    return math.log(p / (1 - p))


def old_nb_at_least(k, mu, alpha):
    if k <= 0:
        return 1.0
    if alpha < 1e-6:
        cdf, term = 0.0, math.exp(-mu)
        for i in range(k):
            cdf += term
            term *= mu / (i + 1)
        return max(0.0, 1 - cdf)
    r = 1 / alpha
    p = r / (r + mu)
    cdf, term = 0.0, p ** r
    for i in range(k):
        cdf += term
        term *= (i + r) / (i + 1) * (1 - p)
    return max(0.0, 1 - cdf)


def old_poisson_cdf(k, mean):
    if mean <= 0:
        return 1.0
    if k < 0:
        return 0.0
    term = math.exp(-mean)
    total = term
    for i in range(1, k + 1):
        term *= mean / i
        total += term
    return min(1.0, total)


def old_neg_bin_cdf(k, mean, size):
    if mean <= 0:
        return 1.0
    if k < 0:
        return 0.0
    p = size / (size + mean)
    total = 0.0
    for i in range(k + 1):
        log_pmf = (
            math.lgamma(i + size) - math.lgamma(i + 1) - math.lgamma(size)
            + size * math.log(p) + i * math.log1p(-p)
        )
        total += math.exp(log_pmf)
    return min(1.0, total)


def old_binom_cdf(k, n, p):
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    p = min(1.0, max(0.0, p))
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def same(a, b):
    """Equal as floats, and NaN equal to NaN."""
    if isinstance(a, tuple):
        return all(same(x, y) for x, y in zip(a, b))
    return a == b or (a != a and b != b)


class Unchanged(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(22102026)

    def ps(self, n=2000):
        edge = [0.0, 1e-12, 1e-9, 1e-4, 0.001, 0.5, 0.999, 1 - 1e-9, 1.0]
        return edge + [self.rng.random() for _ in range(n)]

    def test_wilson(self):
        for _ in range(3000):
            total = self.rng.randint(0, 60)
            hits = self.rng.randint(0, total) if total else 0
            if self.rng.random() < 0.3 and total:
                hits = self.rng.random() * total          # weekend passes floats
            z = self.rng.choice([1.96, 1.645, 1.0 + self.rng.random()])
            want = old_wilson_low(hits, total, z)
            self.assertTrue(same(model.wilson_low(hits, total, z), want))
            self.assertTrue(same(probability.wilson_low(hits, total, z), want))
            self.assertTrue(same(review.wilson(hits, total, z), old_wilson(hits, total, z)))

    def test_calibration(self):
        for p in self.ps():
            self.assertTrue(same(model.calibrate(p),
                                 old_platt(p, model.CALIBRATION_A, model.CALIBRATION_B)))
            for sport in ("football", "american-football", "basketball", "darts", "nowhere"):
                a, b = model.PLAYER_CALIBRATION_BY_SPORT.get(
                    sport, (model.PLAYER_CALIBRATION_A, model.PLAYER_CALIBRATION_B))
                self.assertTrue(same(model.calibrate_player(p, sport), old_platt(p, a, b)))
                for kind in ("team", "player"):
                    fit = model.RECORD_CALIBRATION.get((sport, kind))
                    want = old_platt(p, *fit) if fit else p
                    self.assertTrue(same(model.calibrate_record(p, sport, kind), want))

    def test_logit_and_sigmoid(self):
        for p in self.ps() + [-0.5, 1.5]:
            for fn in (darts_market._logit, exchange_eval._lg, market_prices._lg, weekend._lp):
                self.assertTrue(same(fn(p), old_logit(p, 1e-4)))
            for fn in (learner._logit, strength._logit):
                self.assertTrue(same(fn(p), old_logit(p, 1e-3)))
        for _ in range(2000):
            z = self.rng.uniform(-30, 30)
            for fn in (darts_model._p, exchange_eval._sig, learner._sig):
                self.assertEqual(fn(z), 1 / (1 + math.exp(-z)))

    def test_counts(self):
        for _ in range(3000):
            k = self.rng.randint(-2, 15)
            mu = self.rng.choice([0.0, -1.0, self.rng.uniform(0.01, 12)])
            alpha = self.rng.choice([0.0, 5e-7, self.rng.uniform(1e-5, 2)])
            if mu > 0:
                want = old_nb_at_least(k, mu, alpha)
                for fn in (context._nb_at_least, probability.nb_at_least):
                    self.assertTrue(same(fn(k, mu, alpha), want))
            self.assertTrue(same(model.poisson_cdf(k, mu), old_poisson_cdf(k, mu)))
            size = self.rng.uniform(0.2, 40)
            self.assertTrue(same(model.neg_bin_cdf(k, mu, size), old_neg_bin_cdf(k, mu, size)))
            n = self.rng.randint(0, 30)
            p = self.rng.choice([-0.1, 0.0, 1.0, 1.1, self.rng.random()])
            self.assertTrue(same(model.binom_cdf(k, n, p), old_binom_cdf(k, n, p)))
            if k >= 0:
                lam = self.rng.uniform(0.01, 6)
                want = math.exp(-lam) * lam ** k / math.factorial(k)
                self.assertEqual(context._poisson(k, lam), want)
                self.assertEqual(match_result._pois(lam, k), want)

    def test_shrink(self):
        for _ in range(2000):
            n = self.rng.randint(0, 50)
            k = self.rng.randint(0, n)
            a = self.rng.choice([0.5, 2.0, self.rng.uniform(0.1, 6)])
            want = (k + a) / (n + 2 * a)
            self.assertEqual(bettrack.adjusted(k, n, a), want)
            self.assertEqual(weekend._shrunk({"hits": k, "total": n}, a), want)
            self.assertEqual(model.smooth_rate(k, n),
                             0.0 if n <= 0 else (k + 0.5) / (n + 2 * 0.5))

    def test_nb_alpha(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy is not installed")
        for _ in range(200):
            mu = np.array([self.rng.uniform(0.1, 9) for _ in range(40)])
            y = np.array([float(self.rng.randint(0, 15)) for _ in range(40)])
            want = max(0.0, float(np.mean((y - mu) ** 2 - mu) / max(1e-9, np.mean(mu ** 2))))
            self.assertEqual(probability.nb_alpha(y, mu), want)


if __name__ == "__main__":
    unittest.main()
