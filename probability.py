"""
The probability helpers the rest of the project shares.

Before 22 October each of these lived in two to four modules as a private
copy (`_lg` in three files, `_nb_at_least` and `_nb_ge`, `nb_alpha` and
`alpha_of`, `wilson_low` and `review.wilson`, and so on). The old names are
still there, as aliases or one-line wrappers onto this module, so nothing that
imports them breaks.

Every function here is the old body moved, not rewritten. That matters more
than it looks: the pages are compared byte for byte before and after, and on
Python 3.12+ even swapping a `+=` loop for `sum()` changes the last bit of a
float (sum() compensates, the loop does not). So:

  * each Poisson and negative binomial sum keeps its own loop;
  * each clamp keeps its argument order, because min(max(p, lo), hi) and
    min(hi, max(lo, p)) disagree on NaN;
  * helpers that only look alike and are not bit-equal were left where they
    are: darts_model.poisson_tail and gamestate.pois_at_least (different
    guards and return types from poisson_cdf), besttrack._tail (log space,
    not math.comb), market_prices._pois (pmf by recurrence, summed with
    sum()), usmodel_live.calibrate (clamped at 1e-4, not 1e-9) and the
    various means (different summation and empty-input handling).

Pure standard library apart from nb_alpha, which imports numpy when called, so
rerender.py and the tests still run on a machine without numpy.
"""

from __future__ import annotations

import math


# ------------------------------------------------------------ odds space

def logit(p: float, eps: float = 1e-4) -> float:
    """log(p / (1 - p)) with p held inside [eps, 1 - eps].

    eps=1e-4: darts_market._logit, exchange_eval._lg, market_prices._lg,
    weekend._lp. eps=1e-3: learner._logit, strength._logit.
    """
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def sigmoid(z: float) -> float:
    """1 / (1 + e^-z). darts_model._p, exchange_eval._sig, learner._sig."""
    return 1 / (1 + math.exp(-z))


def platt(p: float, a: float, b: float) -> float:
    """sigmoid(a + b * logit(p)), p held inside [1e-9, 1 - 1e-9].

    The calibration shape model.calibrate, calibrate_record and
    calibrate_player all use, each with its own (a, b).
    """
    p = min(1 - 1e-9, max(1e-9, p))
    z = a + b * math.log(p / (1 - p))
    return 1 / (1 + math.exp(-z))


# ------------------------------------------------------------ proportions

def shrink(k: float, n: float, a: float) -> float:
    """(k + a) / (n + 2a): a hit rate pulled towards 50% by a pseudo-counts.

    bettrack.adjusted, weekend._shrunk and model.smooth_rate.
    """
    return (k + a) / (n + 2 * a)


def _wilson_terms(hits, total, z):
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return denom, centre, spread


def wilson_low(hits: int, total: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson interval for a proportion.

    The honest version of hits/total. Five from five is not 100%, it is
    "somewhere above 57%", and this is the number that says so.
    """
    if total == 0:
        return 0.0
    denom, centre, spread = _wilson_terms(hits, total, z)
    return max(0.0, (centre - spread) / denom)


def wilson(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Both ends of the Wilson interval; (0, 1) when there is no sample."""
    if not total:
        return 0.0, 1.0
    denom, centre, spread = _wilson_terms(hits, total, z)
    return max(0.0, (centre - spread) / denom), min(1.0, (centre + spread) / denom)


# ------------------------------------------------------------ counts

def poisson_pmf(k: int, lam: float) -> float:
    """P(X = k), closed form. context._poisson, match_result._pois."""
    return math.exp(-lam) * lam ** k / math.factorial(k)


def poisson_cdf(k: int, mean: float) -> float:
    """P(X <= k). Summed forwards rather than via a gamma function because k
    is always small here and the loop is exact."""
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


def neg_bin_cdf(k: int, mean: float, size: float) -> float:
    """P(X <= k) for a negative binomial with the given mean and dispersion.

    Parameterised by mean and `size` rather than by the usual r and p, because
    the mean is what the projection gives us and the dispersion is what the
    sample gives us. Computed in logs to stay stable when size is large.
    """
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


def nb_at_least(k: int, mu: float, alpha: float) -> float:
    """P(X >= k) for a negative binomial with mean mu and overdispersion
    alpha (var = mu + alpha mu^2), Poisson when alpha is under 1e-6.

    Summed by recurrence. context._nb_at_least, usgame._nb_ge and
    gs_backtest.p_at_least.
    """
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


def nb_alpha(y, mu):
    """Method-of-moments overdispersion: var = mu + alpha mu^2, never below 0.

    y and mu are numpy arrays. gs_backtest.nb_alpha, teammodel_train.alpha_of.
    """
    import numpy as np
    return max(0.0, float(np.mean((y - mu) ** 2 - mu) / max(1e-9, np.mean(mu ** 2))))


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for a binomial. The narrow end of the count family."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    p = min(1.0, max(0.0, p))
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
