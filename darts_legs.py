"""
Darts leg model: leg strengths with shrinkage, and per-player stat lines
priced from the legs the match is expected to last.

Not wired into live pricing: see DARTS-MODEL.md for the evidence and why.
The checks are in darts_legs_backtest.py.

Two parts, both checked against what is live and written up in DARTS-MODEL.md.

THE LEG. Each player has a leg strength (log-odds of winning a leg against
an average tour player, throw neutral) and an uncertainty. A new name starts
below the tour average with a wide uncertainty, so a qualifier's first wins
move him a long way and a regular's barely at all: that is the shrinkage
towards the tour, done the Bayesian way rather than with one K for everyone.
The uncertainty grows while a player is away. A match is a binomial on legs,
but legs on one night are not independent (form, nerves, the board), so a
night-form term TAU2 is added to the noise of every match: a 6-0 is strong
evidence, not six independent pieces of it. Updated one match at a time in
date order (a Kalman step on the rating gap), so every rating is as of the
morning of the match.

THE MATCH. The gap for the night is uncertain (both ratings, plus night form),
so the score distribution is averaged over that uncertainty with
Gauss-Hermite nodes, each node worked out exactly for the format: first to N
legs, or first to S sets of first to L legs, throw alternating leg to leg and
set to set, who throws first averaged out. That gives the winner, handicap,
total legs and the legs each man is expected to win, which is what the stat
lines need.

STAT LINES. These are what the site actually bets on darts (best_bets.json):
180s, 3-dart average, highest checkout and 100+ checkouts, all currently
priced off the player's raw last-20 record, whatever the format. Here:
  180s           per leg played, gamma-shrunk to the tour rate, negative
                 binomial over the legs the match is expected to last
  100+ checkouts per leg won, gamma-shrunk, Poisson over his legs won
  highest        chance a leg won is finished above the line, beta-shrunk to
  checkout       the tour, then 1 - (1 - s)^W over his legs won
  3-dart average shrunk mean, spread that narrows with legs played
"""

from __future__ import annotations

import functools
import glob
import json
import math
from pathlib import Path

import darts_model as dm

HERE = Path(__file__).resolve().parent

# LEG fitted on matches before 2026, STATS on matches before July 2026
# (python darts_legs_backtest.py --tune); see DARTS-MODEL.md.
LEG = {
    "new": -0.10,       # a first-seen name, log-odds per leg below the tour
    "var0": 0.06,       # and how unsure of that we are
    "q": 0.0001,        # variance added per day away
    "tau2": 0.08,       # night form: noise on the gap shared by every leg of a match
    "throw": 0.6,       # log-odds edge of throwing first in a leg
    "slope": 0.7,       # the predicted gap is multiplied by this before pricing
}
STATS = {
    "m180": 80.0,       # prior strength in legs for 180s per leg
    "k180": 50.0,       # negative binomial size for match 180s
    "m100": 25.0,       # prior strength in legs won for 100+ checkouts
    "mhc": 240.0,       # prior strength in legs won for the highest checkout
    "mavg": 0.5,        # prior strength in matches for the 3-dart average
    "window": 20,       # recent matches with stats used per player
}
GH_NODES = 7
VAR_CAP = 0.5

STAT_NAMES = ("Thrown 180", "Checkouts over 100", "Highest checkout", "Average 3 darts")


def _p(x: float) -> float:
    return 1 / (1 + math.exp(-x))


# ------------------------------------------------------------------ loading

def load_matches(cache_dir: Path) -> list[dict]:
    """darts_model.load_matches, plus the legs each man won (summed over sets
    in a sets match, from the period scores)."""
    raw = {}
    for pattern in ("team_*_events_last_*.json", "team_*_events_next_*.json"):
        for path in glob.glob(str(Path(cache_dir) / pattern)):
            try:
                data = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for e in data.get("events") or []:
                if ((e.get("homeTeam") or {}).get("sport") or {}).get("slug") == "darts":
                    raw[e["id"]] = e
    out = []
    for m in dm.load_matches(Path(cache_dir)):
        m["la"], m["lb"] = legs_won(raw.get(m["id"]) or {}, m)
        out.append(m)
    return out


def legs_won(e: dict, m: dict):
    if m.get("fmt") is None or not isinstance(m.get("sa"), int) or not isinstance(m.get("sb"), int):
        return None, None
    if m["fmt"][0] == "legs":
        return m["sa"], m["sb"]
    hs, aw = e.get("homeScore") or {}, e.get("awayScore") or {}
    la = lb = 0
    found = False
    for i in range(1, 16):
        x, y = hs.get(f"period{i}"), aw.get(f"period{i}")
        if isinstance(x, int) and isinstance(y, int):
            la += x
            lb += y
            found = True
    return (la, lb) if found else (None, None)


# ---------------------------------------------------------- match maths

@functools.lru_cache(maxsize=400000)
def _set_or_legs(n: int, pt: float, pr: float, first: bool):
    return dm._legs(n, pt, pr, first)


def node_distribution(gap: float, fmt, throw: float) -> dict:
    """{(score_a, score_b, legs_a, legs_b): p} for a known leg gap, who throws
    first averaged out. For a legs match the score is the legs."""
    pt, pr = round(_p(gap + throw), 5), round(_p(gap - throw), 5)
    out: dict = {}
    for first in (True, False):
        if fmt[0] == "legs":
            for (a, b), p in _set_or_legs(fmt[1], pt, pr, first):
                out[(a, b, a, b)] = out.get((a, b, a, b), 0) + 0.5 * p
            continue
        S, L = fmt[1], fmt[2]
        sets = {f: _set_or_legs(L, pt, pr, f) for f in (True, False)}
        state = {(0, 0, 0, 0, first): 1.0}
        while state:
            nxt = {}
            for (sa, sb, la, lb, f), p in state.items():
                for (x, y), q in sets[f]:
                    na, nb = (sa + 1, sb) if x > y else (sa, sb + 1)
                    key = (na, nb, la + x, lb + y)
                    if na == S or nb == S:
                        out[key] = out.get(key, 0) + 0.5 * p * q
                    else:
                        k2 = key + (not f,)
                        nxt[k2] = nxt.get(k2, 0) + p * q
            state = nxt
    return out


_GH = None


def _gh():
    """Gauss-Hermite nodes and weights for an expectation over N(0, 1)."""
    global _GH
    if _GH is None:
        import numpy as np
        x, w = np.polynomial.hermite_e.hermegauss(GH_NODES)
        _GH = list(zip(x.tolist(), (w / w.sum()).tolist()))
    return _GH


def match_distribution(mu: float, var: float, fmt, throw: float = LEG["throw"]) -> dict:
    """The score and legs distribution averaged over an uncertain gap
    N(mu, var)."""
    sd = math.sqrt(max(var, 0.0))
    out: dict = {}
    for z, w in _gh():
        for k, p in node_distribution(mu + sd * z, fmt, throw).items():
            out[k] = out.get(k, 0) + w * p
    return out


def summarise(dist: dict, fmt) -> dict:
    target = fmt[1]
    win = sum(p for (a, b, _, _), p in dist.items() if a == target)
    total = {}
    for (_, _, la, lb), p in dist.items():
        total[la + lb] = total.get(la + lb, 0) + p
    return {"win": win, "totalLegs": total,
            "expLegs": sum(t * p for t, p in total.items()),
            "legsA": sum(la * p for (_, _, la, _), p in dist.items()),
            "legsB": sum(lb * p for (_, _, _, lb), p in dist.items())}


# --------------------------------------------------------------- ratings

class LegRatings:
    """Leg strengths with uncertainty, one Kalman step per match."""

    def __init__(self, matches: list[dict], params: dict | None = None):
        self.p = dict(LEG, **(params or {}))
        self.mu: dict = {}
        self.var: dict = {}
        self.last: dict = {}
        self.n: dict = {}
        self.names: dict = {}
        self.preds: dict = {}      # match id -> (mu_gap, var_gap) before the match
        for m in matches:
            self.update(m)

    def state(self, pid, ts):
        if pid not in self.mu:
            return self.p["new"], self.p["var0"]
        days = max(0.0, (ts - self.last[pid]) / 86400)
        return self.mu[pid], min(self.var[pid] + self.p["q"] * days, VAR_CAP)

    def gap(self, a, b, ts):
        """(mean, variance) of a's leg edge over b for the night."""
        ma, va = self.state(a, ts)
        mb, vb = self.state(b, ts)
        c = self.p["slope"]
        return c * (ma - mb), c * c * (va + vb + self.p["tau2"])

    def update(self, m):
        if m["status"] != "finished" or m["fmt"] is None or m["a"] is None or m["b"] is None:
            return
        la, lb = m.get("la"), m.get("lb")
        if not isinstance(la, int) or not isinstance(lb, int) or la + lb == 0:
            return
        a, b, ts = m["a"], m["b"], m["ts"]
        self.preds[m["id"]] = self.gap(a, b, ts)
        ma, va = self.state(a, ts)
        mb, vb = self.state(b, ts)
        g, n, th = ma - mb, la + lb, self.p["throw"]
        p1, p2 = _p(g + th), _p(g - th)
        pbar = (p1 + p2) / 2
        w = (p1 * (1 - p1) + p2 * (1 - p2)) / 2
        # One Newton step from the prior gap is the observed gap, with
        # sampling noise 1/(n w) plus night form.
        g_hat = g + (la - n * pbar) / (n * w)
        s, r = va + vb, 1 / (n * w) + self.p["tau2"]
        dg = (g_hat - g) * s / (s + r)
        self.mu[a] = ma + va / s * dg
        self.mu[b] = mb - vb / s * dg
        self.var[a] = va - va * va / (s + r)
        self.var[b] = vb - vb * vb / (s + r)
        for pid, name in ((a, m["a_name"]), (b, m["b_name"])):
            self.last[pid] = ts
            self.n[pid] = self.n.get(pid, 0) + 1
            self.names[pid] = name

    def games(self, pid):
        return self.n.get(pid, 0)


# ----------------------------------------------------------------- stat lines

def _negbin_tail(mean: float, size: float, line: float) -> float:
    """P(X > line) for a negative binomial with this mean and size."""
    if mean <= 0:
        return 0.0
    k = int(math.floor(line))
    q = size / (size + mean)
    term = q ** size
    cdf = term
    for i in range(1, k + 1):
        term *= (i - 1 + size) / i * (1 - q)
        cdf += term
    return max(0.0, 1 - cdf)


def _poisson_tail(lam: float, line: float) -> float:
    return dm.poisson_tail(lam, line) if lam > 0 else 0.0


def _norm_sf(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2))


class StatBook:
    """Per-player stat history, as of any date, and the tour averages
    to shrink towards. Built from matches with statistics only."""

    def __init__(self, matches: list[dict], params: dict | None = None):
        self.p = dict(STATS, **(params or {}))
        self.rows: dict = {}       # pid -> list of row dicts, date order
        self.tour: list = []       # all rows, date order
        for m in matches:
            self.add(m)

    def add(self, m):
        st = m.get("stats")
        if m["status"] != "finished" or not st or not isinstance(m.get("la"), int) \
                or not isinstance(m.get("lb"), int):
            return
        legs = m["la"] + m["lb"]
        for side, pid, won in (("a", m["a"], m["la"]), ("b", m["b"], m["lb"])):
            s = st[side]
            row = {"ts": m["ts"], "id": m["id"], "legs": legs, "won": won,
                   "fmt": m["fmt"], **{k: s.get(k) for k in STAT_NAMES}}
            self.rows.setdefault(pid, []).append(row)
            self.tour.append(row)

    def history(self, pid, ts):
        return [r for r in self.rows.get(pid, []) if r["ts"] < ts][-self.p["window"]:]

    def tour_rows(self, ts, last=600):
        out = []
        for r in reversed(self.tour):
            if r["ts"] < ts:
                out.append(r)
                if len(out) >= last:
                    break
        return out

    # Tour figures, recomputed from what was known before ts.
    def tour_rates(self, ts):
        rows = self.tour_rows(ts)
        legs = sum(r["legs"] for r in rows if r["Thrown 180"] is not None) or 1
        won = sum(r["won"] for r in rows if r["Checkouts over 100"] is not None) or 1
        avgs = [r["Average 3 darts"] for r in rows if r["Average 3 darts"]]
        mean_avg = sum(avgs) / len(avgs) if avgs else 90.0
        # Match averages spread by player and by night; the night part
        # narrows with legs played. Fitted once, see DARTS-MODEL.md.
        return {"r180": sum(r["Thrown 180"] for r in rows if r["Thrown 180"] is not None) / legs,
                "r100": sum(r["Checkouts over 100"] for r in rows if r["Checkouts over 100"] is not None) / won,
                "avg": mean_avg, "rows": rows}

    def player(self, pid, ts, tour=None):
        """Shrunk rates for one player, as of ts."""
        tour = tour or self.tour_rates(ts)
        h = self.history(pid, ts)
        p = self.p
        h180 = [r for r in h if r["Thrown 180"] is not None]
        legs = sum(r["legs"] for r in h180)
        r180 = (sum(r["Thrown 180"] for r in h180) + p["m180"] * tour["r180"]) / (legs + p["m180"])
        h100 = [r for r in h if r["Checkouts over 100"] is not None]
        won = sum(r["won"] for r in h100)
        r100 = (sum(r["Checkouts over 100"] for r in h100) + p["m100"] * tour["r100"]) / (won + p["m100"])
        ha = [r for r in h if r["Average 3 darts"]]
        # Weighted by legs, so a 6-5 counts for more than a 6-0.
        wsum = sum(r["legs"] for r in ha)
        own = sum(r["Average 3 darts"] * r["legs"] for r in ha) / wsum if wsum else tour["avg"]
        k = len(ha)
        avg = (k * own + p["mavg"] * tour["avg"]) / (k + p["mavg"])
        return {"r180": r180, "r100": r100, "avg": avg, "n": len(h), "hc": h,
                "avg_se2": AVG_PLAYER_SD ** 2 * p["mavg"] / (k + p["mavg"])}

    def hc_rate(self, rows, line, ts=None, tour_rows=None, m=None):
        """Chance one leg won is checked out above `line`, beta-shrunk to the
        tour figure, by a grid posterior over the matches in rows."""
        m = self.p["mhc"] if m is None else m
        s0 = _tour_hc(tuple((r["won"], r["Highest checkout"]) for r in (tour_rows or [])
                            if r["Highest checkout"] is not None), line)
        return _hc_posterior(tuple((r["won"], r["Highest checkout"]) for r in rows
                                   if r["Highest checkout"] is not None), line, s0, m)


# Match averages around a player's own mean, fitted on matches before July
# 2026: about 5.8 points either way, and over the 6 to 11 legs most matches
# last it barely narrows with length, so most of it is the night rather than
# the legs. Player means spread about 3.3 around the tour.
AVG_PLAYER_SD = 3.0      # how far a player's true average sits from the tour's
AVG_NIGHT_SD = 5.0       # night to night, whatever the length
AVG_LEG_SD = 6.0         # per leg, so a match of L legs adds 6 / sqrt(L)

_GRID = [(i + 0.5) / 400 for i in range(400)]


@functools.lru_cache(maxsize=20000)
def _tour_hc(rows: tuple, line: float) -> float:
    if not rows:
        return 0.15
    best = None
    for s in _GRID[::4]:
        ll = 0.0
        for w, hc in rows:
            if w <= 0:
                continue
            miss = (1 - s) ** w
            ll += math.log(max(1 - miss, 1e-12)) if hc > line else math.log(max(miss, 1e-12))
        if best is None or ll > best[0]:
            best = (ll, s)
    return best[1]


@functools.lru_cache(maxsize=200000)
def _hc_posterior(rows: tuple, line: float, s0: float, m: float) -> float:
    a0, b0 = max(m * s0, 1e-3), max(m * (1 - s0), 1e-3)
    logs = []
    for s in _GRID:
        ll = (a0 - 1) * math.log(s) + (b0 - 1) * math.log(1 - s)
        for w, hc in rows:
            if w <= 0:
                continue
            miss = (1 - s) ** w
            ll += math.log(max(1 - miss, 1e-12)) if hc > line else math.log(max(miss, 1e-12))
        logs.append(ll)
    top = max(logs)
    ws = [math.exp(x - top) for x in logs]
    total = sum(ws)
    return sum(s * w for s, w in zip(_GRID, ws)) / total


def stat_chance(stat: str, line: float, side: str, dist: dict, pl: dict,
                book: StatBook | None = None, ts=None, tour=None) -> float | None:
    """P(over line) for one player's stat, mixed over the legs distribution.
    side 'a' or 'b' says which player in dist this is."""
    k = book.p if book else STATS
    if stat == "Thrown 180":
        by_legs = {}
        for (_, _, la, lb), p in dist.items():
            by_legs[la + lb] = by_legs.get(la + lb, 0) + p
        return sum(p * _negbin_tail(pl["r180"] * L, k["k180"], line) for L, p in by_legs.items())
    won = {}
    for (_, _, la, lb), p in dist.items():
        w = la if side == "a" else lb
        won[w] = won.get(w, 0) + p
    if stat == "Checkouts over 100":
        return sum(p * _poisson_tail(pl["r100"] * w, line) for w, p in won.items())
    if stat == "Highest checkout":
        if book is None:
            return None
        s = book.hc_rate(pl["hc"], line, ts, (tour or {}).get("rows"))
        return sum(p * (1 - (1 - s) ** w) for w, p in won.items())
    if stat == "Average 3 darts":
        by_legs = {}
        for (_, _, la, lb), p in dist.items():
            by_legs[la + lb] = by_legs.get(la + lb, 0) + p
        out = 0.0
        for L, p in by_legs.items():
            sd = math.sqrt(AVG_NIGHT_SD ** 2 + AVG_LEG_SD ** 2 / max(L, 1) + pl["avg_se2"])
            out += p * _norm_sf((line - pl["avg"]) / sd)
        return out
    return None


def record_chance(rows: list[dict], stat: str, line: float, last: int = 20):
    """What is live: the player's last `last` matches with the stat, (hits +
    0.5) / (n + 1), no calibration for darts (model.smooth_rate)."""
    vals = [r[stat] for r in rows if r.get(stat) is not None][-last:]
    if not vals:
        return None, 0
    hits = sum(1 for v in vals if v > line)
    return (hits + 0.5) / (len(vals) + 1), len(vals)


# ----------------------------------------------------------------- live use

def price_match(r: LegRatings, book: StatBook, a, b, fmt, ts) -> dict:
    mu, var = r.gap(a, b, ts)
    dist = match_distribution(mu, var, fmt, r.p["throw"])
    s = summarise(dist, fmt)
    tour = book.tour_rates(ts)
    return {"dist": dist, "summary": s, "pa": book.player(a, ts, tour),
            "pb": book.player(b, ts, tour), "tour": tour, "gap": (mu, var)}
