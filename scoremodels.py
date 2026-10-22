"""
Scoreline models for The case: goal means, a score grid, and the 1X2 from it.

    import scoremodels as sm
    m = sm.TeamGoals(half_life=240, ridge=2.0).fit(matches, now)
    lh, la = m.means(home_id, away_id)
    grid = m.grid(home_id, away_id)          # P(home i, away j), i, j < GRID_N
    ph, pd, pa = sm.outcome_probs(grid)

Why this exists. context.py has always printed a predicted score and home,
draw and away chances, and nobody had checked either against what happened.
case_score_backtest.py does that, walk-forward over the cache, and this module
holds the alternatives it measured:

  poisson      independent Poisson, attack and defence per team, one home
               edge, fitted by weighted maximum likelihood with recent matches
               counting more (half_life, in days) and a ridge pull towards
               the average side (ridge), so a club seen three times is not
               rated on three results
  dc           the same goal means with Dixon and Coles' low-score
               correction: 0-0 and 1-1 a little likelier, 1-0 and 0-1 a
               little less, governed by one fitted rho
  bivariate    Karlis and Ntzoufras' bivariate Poisson: a shared component
               lambda3 adds to both sides' goals, which is what lets draws
               come out more often than two independent counts allow. Fitted
               by direct maximum likelihood
  elo          independent Poisson whose means come from strength.py's Elo
               gap and the competition's recent scoring level, two small
               regressions and nothing per team

A "match" here is a dict with home, away (team ids), hg, ag (goals at full
time, before extra time), ts (kick-off, epoch seconds) and optionally tid.
Nothing in this module reads the cache or fetches anything.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import gammaln

GRID_N = 11          # goals 0..10 per side; the mass beyond is about 1e-6 at football means
DAY = 86400.0


# ------------------------------------------------------------------ grids

def _pois_vec(lam: float, n: int = GRID_N) -> np.ndarray:
    k = np.arange(n)
    logf = np.array([math.lgamma(i + 1) for i in range(n)])
    return np.exp(-lam + k * math.log(max(lam, 1e-12)) - logf)


def poisson_grid(lh: float, la: float, n: int = GRID_N) -> np.ndarray:
    """P(home scores i, away scores j) for two independent Poisson counts."""
    return np.outer(_pois_vec(lh, n), _pois_vec(la, n))


def dc_tau(grid: np.ndarray, lh: float, la: float, rho: float) -> np.ndarray:
    """Dixon and Coles' correction applied to the four low scores."""
    g = grid.copy()
    g[0, 0] *= max(1 - lh * la * rho, 0.0)
    g[0, 1] *= max(1 + lh * rho, 0.0)
    g[1, 0] *= max(1 + la * rho, 0.0)
    g[1, 1] *= max(1 - rho, 0.0)
    return g


def dc_grid(lh: float, la: float, rho: float, n: int = GRID_N) -> np.ndarray:
    return dc_tau(poisson_grid(lh, la, n), lh, la, rho)


def bivariate_grid(l1: float, l2: float, l3: float, n: int = GRID_N) -> np.ndarray:
    """Bivariate Poisson: home = X1 + X3, away = X2 + X3, all independent."""
    p1, p2, p3 = _pois_vec(l1, n), _pois_vec(l2, n), _pois_vec(l3, n)
    g = np.zeros((n, n))
    for k in range(n):
        if p3[k] < 1e-15:
            break
        g[k:, k:] += p3[k] * np.outer(p1[:n - k], p2[:n - k])
    return g


def outcome_probs(grid: np.ndarray) -> tuple[float, float, float]:
    """Home win, draw, away win, normalised over the grid."""
    total = grid.sum()
    ph = np.tril(grid, -1).sum() / total
    pd = np.trace(grid) / total
    return float(ph), float(pd), float(1 - ph - pd)


def pick_score(grid: np.ndarray) -> tuple[int, int, float]:
    """The score the page prints: the likeliest result, then the likeliest
    score within that result. The plain mode of two Poisson counts is nearly
    always 1-1 or 1-0, which says nothing about the game."""
    ph, pd, pa = outcome_probs(grid)
    want = max((ph, 0), (pd, 1), (pa, 2))[1]
    n = grid.shape[0]
    i, j = np.indices((n, n))
    mask = (i > j) if want == 0 else (i == j) if want == 1 else (i < j)
    flat = np.where(mask, grid, -1.0)
    bi, bj = np.unravel_index(int(np.argmax(flat)), flat.shape)
    return int(bi), int(bj), float(grid[bi, bj] / grid.sum())


def modal_score(grid: np.ndarray) -> tuple[int, int]:
    bi, bj = np.unravel_index(int(np.argmax(grid)), grid.shape)
    return int(bi), int(bj)


# ------------------------------------------------------------- scoring rules

def outcome_index(hg: int, ag: int) -> int:
    return 0 if hg > ag else 1 if hg == ag else 2


def rps(p, o: int) -> float:
    """Ranked probability score for an ordered home, draw, away forecast."""
    e = [1.0 if k == o else 0.0 for k in range(3)]
    c1 = p[0] - e[0]
    c2 = p[0] + p[1] - e[0] - e[1]
    return 0.5 * (c1 * c1 + c2 * c2)


def brier(p, o: int) -> float:
    return sum((p[k] - (1.0 if k == o else 0.0)) ** 2 for k in range(3))


def log_loss(p, o: int, floor: float = 1e-6) -> float:
    return -math.log(max(p[o], floor))


# ------------------------------------------------------- team goals models

def decay_weights(ts: np.ndarray, now: float, half_life: float) -> np.ndarray:
    age = np.maximum(now - ts, 0.0) / DAY
    return np.exp(-math.log(2) * age / half_life)


def _bp_pmf(x: np.ndarray, y: np.ndarray, l1, l2, l3) -> np.ndarray:
    """Bivariate Poisson probability of each (x, y), vectorised."""
    out = np.zeros(len(x))
    lg = gammaln
    m = np.minimum(x, y)
    for k in range(int(m.max()) + 1 if len(m) else 0):
        ok = m >= k
        xk, yk = x - k, y - k
        term = np.where(ok, np.exp(
            np.where(ok, xk, 0) * np.log(l1) + np.where(ok, yk, 0) * np.log(l2) + k * np.log(l3)
            - lg(np.where(ok, xk, 0) + 1) - lg(np.where(ok, yk, 0) + 1) - math.lgamma(k + 1)), 0.0)
        out += term
    return out * np.exp(-(l1 + l2 + l3))


class TeamGoals:
    """Attack and defence per team, fitted on every match before `now`.

    kind is "poisson", "dc" or "bivariate". The "dc" fit is the Poisson fit
    plus rho estimated by weighted likelihood with the means held fixed, the
    usual two-stage shortcut: the correction moves four cells and barely
    shifts the means.
    """

    def __init__(self, kind: str = "poisson", half_life: float = 240.0, ridge: float = 2.0,
                 max_age_days: float = 1100.0):
        self.kind = kind
        self.half_life = half_life
        self.ridge = ridge
        self.max_age_days = max_age_days
        self.index: dict = {}
        self.att = self.dfn = None
        self.mu = 0.0
        self.home = 0.0
        self.rho = 0.0
        self.l3 = 0.0
        self.n_fit = 0
        self._x0 = None

    # -- fitting
    def _arrays(self, matches, now):
        rows = [m for m in matches if m["ts"] < now and now - m["ts"] <= self.max_age_days * DAY]
        teams = sorted({m["home"] for m in rows} | {m["away"] for m in rows})
        index = {t: i for i, t in enumerate(teams)}
        h = np.array([index[m["home"]] for m in rows], dtype=int)
        a = np.array([index[m["away"]] for m in rows], dtype=int)
        hg = np.array([m["hg"] for m in rows], dtype=float)
        ag = np.array([m["ag"] for m in rows], dtype=float)
        w = decay_weights(np.array([m["ts"] for m in rows], dtype=float), now, self.half_life)
        return index, h, a, hg, ag, w

    def _fit_means(self, nt, h, a, yh, ya, w, x0=None):
        """Weighted Poisson ML for mu, home, att, dfn on targets yh, ya."""
        lam = self.ridge

        def f(theta):
            mu, home = theta[0], theta[1]
            att, dfn = theta[2:2 + nt], theta[2 + nt:]
            eh = mu + home + att[h] - dfn[a]
            ea = mu + att[a] - dfn[h]
            mh, ma = np.exp(eh), np.exp(ea)
            nll = np.sum(w * (mh - yh * eh)) + np.sum(w * (ma - ya * ea))
            nll += 0.5 * lam * (att @ att + dfn @ dfn)
            rh, ra = w * (mh - yh), w * (ma - ya)
            g = np.empty_like(theta)
            g[0] = rh.sum() + ra.sum()
            g[1] = rh.sum()
            g[2:2 + nt] = np.bincount(h, rh, nt) + np.bincount(a, ra, nt) + lam * att
            g[2 + nt:] = -np.bincount(a, rh, nt) - np.bincount(h, ra, nt) + lam * dfn
            return nll, g

        if x0 is None or len(x0) != 2 + 2 * nt:
            x0 = np.zeros(2 + 2 * nt)
            x0[0] = math.log(max((np.sum(w * (yh + ya)) / (2 * np.sum(w))), 0.1))
        res = minimize(f, x0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
        return res.x

    def fit(self, matches, now: float) -> "TeamGoals":
        index, h, a, hg, ag, w = self._arrays(matches, now)
        nt = len(index)
        self.index, self.n_fit = index, len(h)
        if nt == 0:
            return self
        if self.kind == "bivariate":
            theta = self._fit_bivariate(nt, h, a, hg, ag, w)
        else:
            theta = self._fit_means(nt, h, a, hg, ag, w)
        self.mu, self.home = float(theta[0]), float(theta[1])
        self.att, self.dfn = theta[2:2 + nt], theta[2 + nt:]
        if self.kind == "dc":
            self.rho = self._fit_rho(h, a, hg, ag, w)
        return self

    def _lams(self, h, a, theta, nt):
        mu, home, att, dfn = theta[0], theta[1], theta[2:2 + nt], theta[2 + nt:]
        return np.exp(mu + home + att[h] - dfn[a]), np.exp(mu + att[a] - dfn[h])

    def _fit_rho(self, h, a, hg, ag, w) -> float:
        lh = np.exp(self.mu + self.home + self.att[h] - self.dfn[a])
        la = np.exp(self.mu + self.att[a] - self.dfn[h])
        c00 = (hg == 0) & (ag == 0)
        c01 = (hg == 0) & (ag == 1)
        c10 = (hg == 1) & (ag == 0)
        c11 = (hg == 1) & (ag == 1)

        def nll(rho):
            t = np.ones_like(lh)
            t = np.where(c00, 1 - lh * la * rho, t)
            t = np.where(c01, 1 + lh * rho, t)
            t = np.where(c10, 1 + la * rho, t)
            t = np.where(c11, 1 - rho, t)
            if np.any(t <= 0):
                return 1e18
            return -np.sum(w * np.log(t))

        return float(minimize_scalar(nll, bounds=(-0.3, 0.3), method="bounded").x)

    def _fit_bivariate(self, nt, h, a, hg, ag, w):
        """Bivariate Poisson with one global lambda3, by direct maximum likelihood.

        EM is the textbook route, but it moves lambda3 very slowly on football
        scores (a synthetic league with lambda3 = 0.25 was still at 0.18 after
        a hundred rounds). The gradient is cheap from the recurrences
        d log P(x, y) / d lambda1 = P(x-1, y) / P(x, y) - 1, and likewise for
        lambda2 with (x, y-1) and lambda3 with (x-1, y-1), so everything is
        fitted together, starting from the independent Poisson fit."""
        lam = self.ridge
        x, y = hg.astype(int), ag.astype(int)
        xm, ym = np.maximum(x - 1, 0), np.maximum(y - 1, 0)

        def f(theta):
            mu, home = theta[0], theta[1]
            att, dfn = theta[2:2 + nt], theta[2 + nt:-1]
            l3 = math.exp(theta[-1])
            l1 = np.exp(mu + home + att[h] - dfn[a])
            l2 = np.exp(mu + att[a] - dfn[h])
            p = np.maximum(_bp_pmf(x, y, l1, l2, l3), 1e-300)
            r1 = np.where(x > 0, _bp_pmf(xm, y, l1, l2, l3), 0.0) / p
            r2 = np.where(y > 0, _bp_pmf(x, ym, l1, l2, l3), 0.0) / p
            r3 = np.where((x > 0) & (y > 0), _bp_pmf(xm, ym, l1, l2, l3), 0.0) / p
            nll = -np.sum(w * np.log(p)) + 0.5 * lam * (att @ att + dfn @ dfn)
            g1 = -w * l1 * (r1 - 1)          # d nll / d eta1
            g2 = -w * l2 * (r2 - 1)
            g = np.empty_like(theta)
            g[0] = g1.sum() + g2.sum()
            g[1] = g1.sum()
            g[2:2 + nt] = np.bincount(h, g1, nt) + np.bincount(a, g2, nt) + lam * att
            g[2 + nt:-1] = -np.bincount(a, g1, nt) - np.bincount(h, g2, nt) + lam * dfn
            g[-1] = np.sum(-w * l3 * (r3 - 1))
            return nll, g

        start = self._fit_means(nt, h, a, hg, ag, w)
        l3 = 0.05
        start[0] += math.log(max(1 - l3 / math.exp(start[0]), 0.5))
        x0 = np.append(start, math.log(l3))
        bounds = [(None, None)] * (len(x0) - 1) + [(math.log(1e-4), math.log(0.8))]
        res = minimize(f, x0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
        self.l3 = float(math.exp(res.x[-1]))
        return res.x[:-1]

    # -- predicting
    def knows(self, team) -> bool:
        return team in self.index

    def means(self, home, away) -> tuple[float, float]:
        """Goal means. For the bivariate model these are lambda1 and lambda2;
        each side's expected goals is that plus lambda3."""
        ih, ia = self.index.get(home), self.index.get(away)
        ah = self.att[ih] if ih is not None else 0.0
        dh = self.dfn[ih] if ih is not None else 0.0
        aa = self.att[ia] if ia is not None else 0.0
        da = self.dfn[ia] if ia is not None else 0.0
        return (math.exp(self.mu + self.home + ah - da), math.exp(self.mu + aa - dh))

    def grid(self, home, away) -> np.ndarray:
        lh, la = self.means(home, away)
        if self.kind == "dc":
            return dc_grid(lh, la, self.rho)
        if self.kind == "bivariate":
            return bivariate_grid(lh, la, self.l3)
        return poisson_grid(lh, la)

    def expected_goals(self, home, away) -> tuple[float, float]:
        lh, la = self.means(home, away)
        return (lh + self.l3, la + self.l3) if self.kind == "bivariate" else (lh, la)


class EloGoals:
    """Independent Poisson from the Elo gap and the competition's scoring.

        log(home mean) = a0 + a1 * gap + a2 * level
        log(away mean) = b0 + b1 * gap + b2 * level

    gap is (home Elo + home edge - away Elo) / 400, as of kick-off, and level
    is the log of the competition's goals per side over the previous year,
    pulled towards the overall figure when the competition has few matches.
    """

    def __init__(self):
        self.a = np.zeros(3)
        self.b = np.zeros(3)

    @staticmethod
    def _fit(X, y):
        def f(beta):
            eta = X @ beta
            m = np.exp(eta)
            return np.sum(m - y * eta), X.T @ (m - y)
        x0 = np.zeros(X.shape[1])
        x0[0] = math.log(max(y.mean(), 0.1))
        return minimize(f, x0, jac=True, method="L-BFGS-B").x

    def fit(self, gaps, levels, hg, ag) -> "EloGoals":
        X = np.column_stack([np.ones(len(gaps)), gaps, levels])
        self.a = self._fit(X, np.asarray(hg, float))
        self.b = self._fit(X, np.asarray(ag, float))
        return self

    def means(self, gap: float, level: float) -> tuple[float, float]:
        x = np.array([1.0, gap, level])
        return float(math.exp(x @ self.a)), float(math.exp(x @ self.b))

    def grid(self, gap: float, level: float) -> np.ndarray:
        return poisson_grid(*self.means(gap, level))
