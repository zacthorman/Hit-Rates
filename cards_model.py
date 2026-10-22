#!/usr/bin/env python3
"""
Walk-forward backtest of the cards model, against the estimates the site
uses now and against the exchange's price.

    python -B cards_model.py test               # replay the cache, print every table
    python -B cards_model.py test --md out.md   # the same tables to a file as well

The question. A team's yellow cards are priced today by the team model
(teammodel/, LightGBM on teamstyle.py features), and a player's "to be
booked" by a heuristic on the page (report.py cardCase): his fouls per 90,
times his side's cards per foul, over his expected minutes, times the side's
projected fouls against its usual. Neither was built for cards in
particular. Is there a cards model that does better on matches it never saw?

Two things in the data decide what can be tested:

  - SofaScore leaves the "Yellow cards" row out of a match's statistics when
    neither side was booked (208 matches in the cache, against 6 that carry
    an explicit 0-0). The team model reads that as missing and drops those
    matches, so it is trained without its 0-0 games. Here they count as 0.
  - Per-player cards are not in the cache at all: the line-ups carry fouls
    and minutes, never bookings (cards_backfill.py would fetch them, from
    the Mac). So a player's chance cannot be scored against his own card.
    What can be scored is what the XI's chances add up to: a heuristic whose
    eleven players sum to the wrong number of team cards is mispricing the
    players on average, whoever it picks out. The split between players is
    untested here, and CARDS-MODEL.md says so.

Every match is replayed in date order using only what was known before it
kicked off. The last 40% of dates are cut into four windows; each model is
fitted on everything before a window and scored on it. The cards variant is
chosen on windows 1 and 2 and confirmed on 3 and 4, which it did not see
when it was chosen.

Nothing here makes a request. It reads cache/ only.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"

WINDOW = 10          # short form window, matches
LONG = 38            # long window, the site's update.json games
K_SHRINK = 4.0       # team-games of league average added to a side's record
K_LEAGUE = 60.0      # team-games of the global average added to a league's
MIN_PRIOR = 6        # fewest prior matches before a side's row is used
MIN_MINUTES = 45     # model.py's football gate for a real appearance
CARDS_PER_FOUL_DEFAULT = 0.13   # report.py
TEAM_LINES = (0.5, 1.5, 2.5, 3.5)
MATCH_LINES = (2.5, 3.5, 4.5, 5.5, 6.5)
N_WINDOWS = 4
TEST_SHARE = 0.4


# ------------------------------------------------------------------ data

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _items(st: dict) -> dict:
    out = {}
    for block in st.get("statistics") or []:
        per = {}
        for g in block.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                per.setdefault(it.get("name"), (_num(it.get("homeValue")), _num(it.get("awayValue"))))
        out[block.get("period")] = per
    return out


def cards_pair(per: dict) -> tuple[float, float] | None:
    """Both sides' yellow cards from one period's items, or None when the
    match has no foul count either (a thin feed, not a clean game).

    SofaScore omits the row when neither side was booked; with fouls
    present that is a 0-0, not a gap."""
    y = per.get("Yellow cards")
    if y and y[0] is not None and y[1] is not None:
        return y
    f = per.get("Fouls")
    if f and f[0] is not None:
        return (0.0, 0.0)
    return None


def booked(cache: Path, mid) -> set | None:
    """Player ids shown a card in a match, from the incidents
    cards_backfill.py caches (event_<id>_incidents.json), or None when the
    match has no incidents on file."""
    try:
        d = json.loads((cache / f"event_{mid}_incidents.json").read_text())
    except (OSError, ValueError):
        return None
    if d.get("missing"):
        return None
    return {(i.get("player") or {}).get("id") for i in d.get("incidents") or []
            if i.get("incidentType") == "card" and (i.get("player") or {}).get("id")}


def load(cache: Path = CACHE) -> list[dict]:
    """The same matches as teamstyle.load (football, finished, statistics
    and line-ups), with the competition, both sides' cards, every player's
    minutes and fouls, and who was booked where the incidents are cached."""
    ev = {}
    for f in glob.glob(str(cache / "team_*_events_last_*.json")):
        try:
            for e in json.loads(Path(f).read_text()).get("events", []):
                ev[e["id"]] = e
        except (OSError, ValueError):
            pass
    out = []
    for mid, e in ev.items():
        t = e.get("tournament") or {}
        if ((t.get("category") or {}).get("sport") or {}).get("slug") != "football":
            continue
        if (e.get("status") or {}).get("type") != "finished":
            continue
        lf, sf = cache / f"event_{mid}_lineups.json", cache / f"event_{mid}_statistics.json"
        if not (lf.exists() and sf.exists()):
            continue
        try:
            lu, st = json.loads(lf.read_text()), json.loads(sf.read_text())
        except (OSError, ValueError):
            continue
        items = _items(st)
        if "ALL" not in items:
            continue
        per = items["ALL"]
        y = cards_pair(per)
        f = per.get("Fouls")
        if y is None or not f or f[0] is None or f[1] is None:
            continue
        players = {}
        for side in ("home", "away"):
            rows = []
            for p in (lu.get(side) or {}).get("players") or []:
                s = p.get("statistics") or {}
                rows.append({"pid": (p.get("player") or {}).get("id"), "pos": p.get("position"),
                             "sub": bool(p.get("substitute")), "min": s.get("minutesPlayed") or 0,
                             "fouls": s.get("fouls") or 0})
            players[side] = rows
        y1 = cards_pair(items.get("1ST") or {})
        y2 = cards_pair(items.get("2ND") or {})
        tid = (t.get("uniqueTournament") or {}).get("id") or t.get("id")
        out.append({"id": mid, "ts": e["startTimestamp"], "tid": tid,
                    "home": e["homeTeam"]["id"], "away": e["awayTeam"]["id"],
                    "hg": (e.get("homeScore") or {}).get("current"),
                    "ag": (e.get("awayScore") or {}).get("current"),
                    "y": y, "f": f, "y1": y1, "y2": y2, "players": players,
                    "booked": booked(cache, mid)})
    out.sort(key=lambda m: (m["ts"], m["id"]))
    return out


# ------------------------------------------------------------------ features

def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def shrunk(xs: list[float], prior: float, k: float = K_SHRINK) -> float:
    """A side's average pulled toward its league's, as if k games at the
    league average were added. A side with three games is mostly league."""
    return (sum(xs) + k * prior) / (len(xs) + k)


def heuristic_lambda(apps: list[dict], per_foul: float, match_adj: float) -> float | None:
    """report.py cardCase on one stretch of appearances: fouls per 90 over
    his expected (median) minutes, times cards per foul, times the side's
    projected fouls against its usual. The page's opponent factor (the
    fouled rate of the men he is up against, held to 0.85 to 1.2) needs the
    predicted shape and is left at 1."""
    gated = [a for a in apps if a["min"] >= MIN_MINUTES]
    if len(gated) < 3:
        return None
    mins = sum(a["min"] for a in gated)
    fouls90 = sum(a["fouls"] for a in gated) / mins * 90
    m = sorted(a["min"] for a in gated)
    exp_min = min(90, m[len(m) // 2])
    return fouls90 * exp_min / 90 * per_foul * match_adj


def player_card_chance(recent: list[dict], played: list[dict], per_foul: float,
                       match_adj: float, scale: float = 1.0) -> float | None:
    """The page's half last ten, half everything, with the cards model's
    scale on top (1 is the page as it is)."""
    a, b = heuristic_lambda(recent, per_foul, match_adj), heuristic_lambda(played, per_foul, match_adj)
    if a is None or b is None:
        return None
    return 1 - math.exp(-scale * (a + b) / 2)


class State:
    """Everything known before a kick-off, built one match at a time."""

    def __init__(self):
        self.team = defaultdict(list)     # team -> [{y, ya, f, fa}]
        self.league = defaultdict(lambda: [0.0, 0.0, 0])  # tid -> [cards, fouls, team-games]
        self.glob = [0.0, 0.0, 0]
        self.elo = defaultdict(lambda: 1500.0)
        self.player = defaultdict(list)   # pid -> [{min, fouls}]

    def league_rates(self, tid):
        g = self.glob
        gy = g[0] / g[2] if g[2] else 2.2
        gf = g[1] / g[2] if g[2] else 12.0
        c, f, n = self.league[tid]
        return ((c + K_LEAGUE * gy) / (n + K_LEAGUE), (f + K_LEAGUE * gf) / (n + K_LEAGUE))

    def side(self, team, opp, home, tid) -> dict | None:
        me, op = self.team[team], self.team[opp]
        if len(me) < MIN_PRIOR or len(op) < MIN_PRIOR:
            return None
        lg_y, lg_f = self.league_rates(tid)
        s10, o10, s38, o38 = me[-WINDOW:], op[-WINDOW:], me[-LONG:], op[-LONG:]
        F = sum(x["f"] for x in s38)
        Y = sum(x["y"] for x in s38)
        return {
            "home": float(home), "n": len(me), "lg_y": lg_y, "lg_f": lg_f,
            "own_y10": shrunk([x["y"] for x in s10], lg_y),
            "prov_y10": shrunk([x["ya"] for x in o10], lg_y),
            "own_y38": shrunk([x["y"] for x in s38], lg_y),
            "prov_y38": shrunk([x["ya"] for x in o38], lg_y),
            "own_f10": shrunk([x["f"] for x in s10], lg_f),
            "drawn_f10": shrunk([x["fa"] for x in o10], lg_f),
            "raw_own_f10": _mean([x["f"] for x in s10]),
            "raw_own_y10": _mean([x["y"] for x in s10]),
            "elo_diff": self.elo[team] - self.elo[opp] + (60 if home else -60),
            "per_foul": Y / F if F >= 30 else CARDS_PER_FOUL_DEFAULT,
        }

    def starters(self, rows: list[dict], booked: set | None = None) -> list[dict]:
        """Each outfield starter's two stretches, as the page reads them, and
        whether he was booked when the match's incidents are on file."""
        out = []
        for p in rows:
            if p["sub"] or p["pos"] == "G" or not p["pid"]:
                continue
            h = self.player[p["pid"]]
            gated = [a for a in h if a["min"] >= MIN_MINUTES]
            out.append({"pid": p["pid"], "recent": gated[-WINDOW:], "played": h[-LONG:],
                        "booked": None if booked is None else p["pid"] in booked})
        return out

    def add(self, m: dict) -> None:
        (yh, ya), (fh, fa) = m["y"], m["f"]
        self.team[m["home"]].append({"y": yh, "ya": ya, "f": fh, "fa": fa})
        self.team[m["away"]].append({"y": ya, "ya": yh, "f": fa, "fa": fh})
        L = self.league[m["tid"]]
        for agg in (L, self.glob):
            agg[0] += yh + ya
            agg[1] += fh + fa
            agg[2] += 2
        for side in ("home", "away"):
            for p in m["players"][side]:
                if p["pid"] and p["min"] > 0:
                    h = self.player[p["pid"]]
                    h.append({"min": p["min"], "fouls": p["fouls"]})
                    if len(h) > 2 * LONG:
                        del h[:-LONG]
        hg, ag = m["hg"], m["ag"]
        if hg is not None and ag is not None:
            h, a = self.elo[m["home"]], self.elo[m["away"]]
            e = 1 / (1 + 10 ** ((a - h - 60) / 400))
            res = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
            k = 20 * (1 + abs(hg - ag)) ** 0.5
            self.elo[m["home"]] += k * (res - e)
            self.elo[m["away"]] -= k * (res - e)


def rows_from(matches: list[dict]) -> list[dict]:
    """One pre-kick-off row per side per match, with its outcome."""
    S = State()
    out = []
    for m in matches:
        for i, (team, opp, side) in enumerate(((m["home"], m["away"], "home"), (m["away"], m["home"], "away"))):
            x = S.side(team, opp, i == 0, m["tid"])
            if x is not None:
                x.update({"match": m["id"], "ts": m["ts"], "team": team, "opp": opp, "tid": m["tid"],
                          "y": m["y"][i], "y_opp": m["y"][1 - i],
                          "starters": S.starters(m["players"][side], m.get("booked"))})
                out.append(x)
        S.add(m)
    return out


# ------------------------------------------------------------------ models

def poisson_glm(X: np.ndarray, y: np.ndarray, iters: int = 50, ridge: float = 1e-6) -> np.ndarray:
    """Log-link Poisson regression by iteratively reweighted least squares."""
    b = np.zeros(X.shape[1])
    b[0] = math.log(max(1e-6, y.mean()))
    for _ in range(iters):
        mu = np.exp(np.clip(X @ b, -10, 10))
        z = X @ b + (y - mu) / mu
        W = mu
        A = X.T @ (W[:, None] * X) + ridge * np.eye(X.shape[1])
        nb = np.linalg.solve(A, X.T @ (W * z))
        if np.max(np.abs(nb - b)) < 1e-9:
            b = nb
            break
        b = nb
    return b


def alpha_of(y: np.ndarray, mu: np.ndarray) -> float:
    """Negative binomial dispersion by moments, nought for Poisson."""
    return max(0.0, float(np.mean((y - mu) ** 2 - mu) / max(1e-9, np.mean(mu ** 2))))


def sf(line: float, mu: np.ndarray, alpha: float) -> np.ndarray:
    """P(count > line) under Poisson (alpha 0) or negative binomial."""
    kmax = int(math.floor(line))
    mu = np.asarray(mu, dtype=float)
    if alpha < 1e-6:
        p = np.exp(-mu)
        cdf = p.copy()
        for k in range(kmax):
            p = p * mu / (k + 1)
            cdf += p
    else:
        r = 1 / alpha
        q = mu / (r + mu)
        p = np.exp(r * np.log(r / (r + mu)))
        cdf = p.copy()
        for k in range(kmax):
            p = p * (k + r) / (k + 1) * q
            cdf += p
    return np.clip(1 - cdf, 1e-4, 1 - 1e-4)


VARIANTS = {
    # name: feature columns, logged unless marked
    "N1 own+opp": ["own_y10", "prov_y10"],
    "N2 +league": ["own_y10", "prov_y10", "lg_y"],
    "N3 +long": ["own_y10", "prov_y10", "own_y38", "prov_y38", "lg_y"],
    "N4 +fouls+elo": ["own_y10", "prov_y10", "own_y38", "prov_y38", "lg_y", "own_f10", "drawn_f10", "elo_diff"],
}


def design(R: list[dict], cols: list[str]) -> np.ndarray:
    X = [np.ones(len(R)), np.array([r["home"] for r in R])]
    for c in cols:
        v = np.array([r[c] for r in R], dtype=float)
        X.append(v / 100 if c == "elo_diff" else np.log(np.clip(v, 0.05, None)))
    return np.column_stack(X)


class GLMCards:
    def __init__(self, cols):
        self.cols = cols

    def fit(self, R):
        y = np.array([r["y"] for r in R], dtype=float)
        self.b = poisson_glm(design(R, self.cols), y)
        self.alpha = alpha_of(y, self.mu(R))
        return self

    def mu(self, R):
        return np.exp(design(R, self.cols) @ self.b)


# ------------------------------------------------------------------ the current estimates

def ts_rows(cache: Path) -> dict:
    """teamstyle.py's training rows keyed by (match, team): the team model's
    own features, with its own cards history (where a 0-0 is missing)."""
    import teamstyle as TS
    S = TS.State.from_cache(cache)
    return {(r["match"], r["team"]): r for r in S.rows}


class CurrentTeamModel:
    """The team model as teammodel_train.py builds it, refitted before each
    window: LightGBM (Poisson) on every teamstyle feature, early stopping on
    the last fifth of the training dates, trained only on rows where the
    cards row exists (so without the 0-0s), negative binomial on top."""

    def __init__(self, ts: dict, zero_fill: bool = False):
        self.ts, self.zero_fill = ts, zero_fill

    def _X(self, R):
        import pandas as pd
        return pd.DataFrame([self.ts[(r["match"], r["team"])] for r in R])

    def fit(self, R):
        import lightgbm as lgb
        import teammodel_train as TT
        R = [r for r in R if (r["match"], r["team"]) in self.ts]
        Z = self._X(R)
        y = np.array([r["y"] for r in R], dtype=float)
        keep = Z["y_Yellow cards"].notna().values | self.zero_fill
        keep &= Z["own_Yellow cards"].notna().values & Z["opp_conc_Yellow cards"].notna().values
        Z, y = Z[keep], y[keep]
        self.f = TT.feats_for(Z, "Yellow cards")
        cut = np.quantile(Z.ts.values, 0.8)
        tr, va = Z.ts.values < cut, Z.ts.values >= cut
        dtr = lgb.Dataset(Z.loc[tr, self.f], y[tr])
        dva = lgb.Dataset(Z.loc[va, self.f], y[va], reference=dtr)
        self.m = lgb.train(TT.PARAMS, dtr, 3000, valid_sets=[dva],
                           callbacks=[lgb.early_stopping(100, verbose=False)])
        self.alpha = alpha_of(y[tr], self.m.predict(Z.loc[tr, self.f]))
        return self

    def mu(self, R):
        return self.m.predict(self._X(R)[self.f])


class HeuristicSum:
    """report.py cardCase for each outfield starter, added up over the XI.
    A starter the page cannot price (fewer than three real appearances) is
    given the mean of his priced team-mates. The side's projected fouls
    against its usual comes from a fouls model fitted the same way as the
    cards one. `scale` is the single number that best turns the XI's sum
    into the side's cards on the training data (it has to cover the
    substitutes too), so the heuristic is scored at its best level."""

    def fit(self, R):
        self.fouls = poisson_glm(self._fx(R), np.array([r.get("y_f", r["raw_own_f10"]) for r in R]))
        lam = self._sum(R)
        y = np.array([r["y"] for r in R], dtype=float)
        ok = np.isfinite(lam)
        self.raw_ratio = float(y[ok].sum() / lam[ok].sum())
        self.scale = self.raw_ratio
        self.alpha = alpha_of(y[ok], lam[ok] * self.scale)
        return self

    @staticmethod
    def _fx(R):
        return np.column_stack([np.ones(len(R)), [r["home"] for r in R],
                                np.log(np.clip([r["own_f10"] for r in R], .5, None)),
                                np.log(np.clip([r["drawn_f10"] for r in R], .5, None))])

    def lams(self, R) -> list[list[float | None]]:
        """The page's lambda for each outfield starter, unscaled."""
        proj = np.exp(self._fx(R) @ self.fouls)
        out = []
        for i, r in enumerate(R):
            adj = min(2.5, max(0.2, proj[i] / max(1e-6, r["raw_own_f10"] or 1e-6)))
            row = []
            for p in r["starters"]:
                a = heuristic_lambda(p["recent"], r["per_foul"], adj)
                b = heuristic_lambda(p["played"], r["per_foul"], adj)
                row.append(None if a is None or b is None else (a + b) / 2)
            out.append(row)
        return out

    def _sum(self, R):
        out = np.full(len(R), np.nan)
        for i, (r, lams) in enumerate(zip(R, self.lams(R))):
            known = [v for v in lams if v is not None]
            if len(r["starters"]) >= 9 and len(known) >= 7:
                fill = sum(known) / len(known)
                out[i] = sum(v if v is not None else fill for v in lams)
        return out

    def mu(self, R):
        return self._sum(R) * self.scale


# ------------------------------------------------------------------ scoring

MIN_PLAYER_LABELS = 200   # starters with incidents before the player test is printed


def score_players(test_rows: list[dict], mu_new: np.ndarray, heur_lams: list, shares: list[float]) -> dict:
    """To be booked, scored player by player where the incidents say who was
    booked: the page's heuristic as it is (no scale) against the cards
    model's split of the side's expected cards. Only starters both price.

    heur_lams[i] is HeuristicSum.lams for test_rows[i]; shares[i] the
    starter share fitted before that row's window."""
    ph, pn, y, g = [], [], [], []
    for r, mu, lams, share in zip(test_rows, mu_new, heur_lams, shares):
        if not np.isfinite(mu) or not r["starters"]:
            continue
        new = xi_chances(xi_weights(r["starters"]), float(mu), share)
        for p, lam, q in zip(r["starters"], lams, new):
            if p.get("booked") is None or lam is None or q is None:
                continue
            ph.append(1 - math.exp(-lam))
            pn.append(q)
            y.append(bool(p["booked"]))
            g.append(r["match"])
    out = {"n": len(y)}
    if len(y) < MIN_PLAYER_LABELS:
        return out
    ph, pn, y, g = np.array(ph), np.array(pn), np.array(y), np.array(g)
    out.update({"landed": float(y.mean()), "heuristic": (logloss(ph, y), brier(ph, y), float(ph.mean())),
                "model": (logloss(pn, y), brier(pn, y), float(pn.mean()))})
    lh = -np.where(y, np.log(np.clip(ph, 1e-4, 1)), np.log(np.clip(1 - ph, 1e-4, 1)))
    ln = -np.where(y, np.log(np.clip(pn, 1e-4, 1)), np.log(np.clip(1 - pn, 1e-4, 1)))
    out["boot"] = bootstrap_diff(ln, lh, g)
    out["calibration"] = {"model": calibration(pn, y.astype(float), (0, .1, .15, .2, .25, .3, .4, 1.0001)),
                          "heuristic": calibration(ph, y.astype(float), (0, .1, .15, .2, .25, .3, .4, 1.0001))}
    return out


def logloss(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(np.where(y, np.log(p), np.log(1 - p))))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def team_scores(mu, alpha, y):
    out = {}
    for L in TEAM_LINES:
        p = sf(L, mu, alpha)
        out[L] = (logloss(p, y > L), brier(p, y > L))
    out["mean"] = (float(np.mean([out[L][0] for L in TEAM_LINES])),
                   float(np.mean([out[L][1] for L in TEAM_LINES])))
    return out


def windows(rows):
    ts = np.array(sorted({r["ts"] for r in rows}))
    start = ts[int(len(ts) * (1 - TEST_SHARE))]
    edges = np.quantile(ts[ts >= start], np.linspace(0, 1, N_WINDOWS + 1))
    edges[-1] += 1
    return [(edges[i], edges[i + 1]) for i in range(N_WINDOWS)]


def market_rows() -> list[dict]:
    """Every exchange price for a match cards over/under the repo has kept,
    the latest before kick-off per match and line: exchange_log.json at
    each commit, and the over runner of OVER_UNDER_xx_CARDS in each
    committed market_prices.json snapshot."""
    def show(path):
        try:
            hs = subprocess.check_output(["git", "-C", str(ROOT), "log", "--all", "--format=%h", "--", path],
                                         stderr=subprocess.DEVNULL).decode().split()
        except (OSError, subprocess.CalledProcessError):
            return
        for h in hs:
            try:
                yield json.loads(subprocess.check_output(["git", "-C", str(ROOT), "show", f"{h}:{path}"],
                                                         stderr=subprocess.DEVNULL))
            except (subprocess.CalledProcessError, ValueError):
                continue

    best = {}

    def put(eid, line, p_over, t, kick, src):
        if p_over is None or (kick and t and t > kick):
            return
        k = (int(eid), float(line))
        if k not in best or (t or 0) > best[k]["t"]:
            best[k] = {"event": int(eid), "line": float(line), "p": float(p_over), "t": t or 0, "src": src}

    for log in show("exchange_log.json"):
        for v in log.values():
            if v.get("stat") != "Match cards" or v.get("period") != "ALL":
                continue
            last = v.get("last") or {}
            mp = last.get("market")
            if mp is None:
                continue
            put(v["event_id"], v["line"], mp if v.get("over") else 1 - mp, last.get("t"), v.get("kickoff"), "exchange_log")
    for snap in show("market_prices.json"):
        t = snap.get("fetched")
        for eid, ev in (snap.get("events") or {}).items():
            if ev.get("sport") != "football":
                continue
            for m in ev.get("markets") or []:
                tp = m.get("type") or ""
                if not (tp.startswith("OVER_UNDER_") and tp.endswith("_CARDS")):
                    continue
                line = int(tp.split("_")[2]) / 10
                over = next((r for r in m.get("runners") or [] if r["name"].lower().startswith("over")), None)
                under = next((r for r in m.get("runners") or [] if r["name"].lower().startswith("under")), None)
                p = over.get("p") if over else None
                if p is None and under and under.get("p") is not None:
                    p = 1 - under["p"]
                put(eid, line, p, t, None, "market_prices")
    return list(best.values())


def bootstrap_diff(a_loss: np.ndarray, b_loss: np.ndarray, groups: np.ndarray, n: int = 1000, seed: int = 7):
    """95% interval for mean(a) - mean(b), resampling whole matches."""
    rng = np.random.default_rng(seed)
    ug, inv = np.unique(groups, return_inverse=True)
    sa = np.bincount(inv, a_loss)
    sb = np.bincount(inv, b_loss)
    cnt = np.bincount(inv)
    d = []
    for _ in range(n):
        idx = rng.integers(0, len(ug), len(ug))
        d.append((sa[idx].sum() - sb[idx].sum()) / cnt[idx].sum())
    return float(np.mean(a_loss - b_loss)), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def calibration(p, y, edges=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001)):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 20:
            out.append((lo, hi, int(m.sum()), float(p[m].mean()), float(y[m].mean())))
    return out


# ------------------------------------------------------------------ the test

def run(cache: Path = CACHE, md_path: Path | None = None) -> dict:
    matches = load(cache)
    rows = rows_from(matches)
    ts = ts_rows(cache)
    for r in rows:
        t = ts.get((r["match"], r["team"]))
        r["y_f"] = (t or {}).get("y_Fouls") or r["raw_own_f10"]
    W = windows(rows)
    models = {name: (lambda c=cols: GLMCards(c)) for name, cols in VARIANTS.items()}
    models["Team model (current)"] = lambda: CurrentTeamModel(ts)
    models["Team model, 0-0s kept"] = lambda: CurrentTeamModel(ts, zero_fill=True)
    models["XI heuristic (current)"] = HeuristicSum
    preds = {k: [] for k in models}
    info = defaultdict(list)
    test_rows = []
    heur_lams, shares = [], []
    for wi, (lo, hi) in enumerate(W):
        train = [r for r in rows if r["ts"] < lo]
        test = [r for r in rows if lo <= r["ts"] < hi]
        share = starter_share([m for m in matches if m["ts"] < lo])
        info["starter_share"].append(share)
        for name, mk in models.items():
            m = mk().fit(train)
            mu = np.asarray(m.mu(test), dtype=float)
            preds[name].append((mu, m.alpha))
            if isinstance(m, HeuristicSum):
                info["heuristic_scale"].append(m.scale)
                heur_lams += m.lams(test)
                shares += [share] * len(test)
            if isinstance(m, GLMCards):
                info[name].append([float(v) for v in m.b])
        for r in test:
            r["window"] = wi
        test_rows += test
    y = np.array([r["y"] for r in test_rows], dtype=float)
    win = np.array([r["window"] for r in test_rows])
    mu = {k: np.concatenate([p[0] for p in v]) for k, v in preds.items()}
    al = {k: np.concatenate([np.full(len(p[0]), p[1]) for p in v]) for k, v in preds.items()}
    # a common set: rows every model priced (the heuristic needs a priced XI)
    common = np.all([np.isfinite(mu[k]) for k in mu], axis=0)

    def p_line(k, L, mask):
        return np.concatenate([sf(L, mu[k][mask & (win == w)], al[k][mask & (win == w)][0])
                               if (mask & (win == w)).any() else np.array([]) for w in range(N_WINDOWS)])

    def y_m(mask):
        return np.concatenate([y[mask & (win == w)] for w in range(N_WINDOWS)])

    res = {"n_matches": len(matches), "n_rows": len(rows), "n_test": int(len(y)), "n_common": int(common.sum()),
           "windows": [[float(a), float(b)] for a, b in W], "info": dict(info)}
    # per window, mean over the four team lines
    tab = {}
    for k in models:
        tab[k] = []
        for w in range(N_WINDOWS):
            mk = common & (win == w)
            s = team_scores(mu[k][mk], al[k][mk][0], y[mk])
            tab[k].append(s["mean"])
    res["per_window"] = tab
    sel = {k: np.mean([tab[k][w][0] for w in (0, 1)]) for k in VARIANTS}
    chosen = min(sel, key=sel.get)
    res["chosen"] = chosen
    # per line, all windows
    lines = {}
    for k in models:
        lines[k] = {}
        for L in TEAM_LINES:
            p = p_line(k, L, common)
            yy = y_m(common) > L
            lines[k][L] = (logloss(p, yy), brier(p, yy))
    res["per_line"] = lines
    # bootstrap: chosen against the current team model and the heuristic, windows 3-4 and all
    groups = np.array([r["match"] for r in test_rows])
    boot = {}
    for other in ("Team model (current)", "Team model, 0-0s kept", "XI heuristic (current)"):
        for label, wmask in (("all", common), ("windows 3-4", common & (win >= 2))):
            la, lb = [], []
            for L in TEAM_LINES:
                pa, pb = p_line(chosen, L, wmask), p_line(other, L, wmask)
                yy = y_m(wmask) > L
                pa, pb = np.clip(pa, 1e-4, 1 - 1e-4), np.clip(pb, 1e-4, 1 - 1e-4)
                la.append(-np.where(yy, np.log(pa), np.log(1 - pa)))
                lb.append(-np.where(yy, np.log(pb), np.log(1 - pb)))
            g = np.concatenate([groups[wmask & (win == w)] for w in range(N_WINDOWS)])
            boot[(other, label)] = bootstrap_diff(np.mean(la, axis=0), np.mean(lb, axis=0), g)
    res["boot"] = {f"{a} | {b}": v for (a, b), v in boot.items()}
    # calibration, pooled over the four team lines
    cal = {}
    for k in (chosen, "Team model (current)", "XI heuristic (current)"):
        ps = np.concatenate([p_line(k, L, common) for L in TEAM_LINES])
        ys = np.concatenate([y_m(common) > L for L in TEAM_LINES])
        cal[k] = calibration(ps, ys.astype(float))
    res["calibration"] = cal
    # level: what each said on average against what landed
    res["level"] = {k: (float(mu[k][common].mean()), float(y[common].mean())) for k in models}
    # player by player, where cards_backfill.py has cached who was booked
    res["players"] = score_players(test_rows, mu[chosen], heur_lams, shares)
    # match totals: both sides' means added, negative binomial with the match dispersion
    res["match"], res["market"] = match_and_market(test_rows, mu, win, common, models, rows, W)
    if md_path:
        md_path.write_text(markdown(res))
    return res


def match_and_market(test_rows, mu, win, common, models, rows, W):
    by = defaultdict(dict)
    for i, r in enumerate(test_rows):
        if common[i]:
            by[r["match"]][r["home"]] = i
    pairs = [(v[1.0], v[0.0]) for v in by.values() if len(v) == 2]
    ih = np.array([a for a, _ in pairs])
    ia = np.array([b for _, b in pairs])
    y = np.array([r["y"] for r in test_rows], dtype=float)
    tot = y[ih] + y[ia]
    wn = win[ih]
    out = {}
    for k in models:
        m_mu = mu[k][ih] + mu[k][ia]
        a = alpha_of(tot, m_mu)    # one figure; the windows differ little
        out[k] = {}
        for L in MATCH_LINES:
            p = sf(L, m_mu, a)
            out[k][L] = (logloss(p, tot > L), brier(p, tot > L))
    # the exchange
    mrows = market_rows()
    mid = {test_rows[i]["match"]: (i, j) for i, j in zip(ih, ia)}
    mk = []
    for r in mrows:
        if r["event"] in mid:
            i, j = mid[r["event"]]
            mk.append((r, i, j))
    mkt = {"n": len(mk), "events": len({r["event"] for r, _, _ in mk})}
    if mk:
        yy = np.array([(y[i] + y[j]) > r["line"] for r, i, j in mk])
        pm = np.array([r["p"] for r, _, _ in mk])
        mkt["Exchange"] = (logloss(pm, yy), brier(pm, yy))
        for k in models:
            a = alpha_of(tot, mu[k][ih] + mu[k][ia])
            pk = np.array([sf(r["line"], np.array([mu[k][i] + mu[k][j]]), a)[0] for r, i, j in mk])
            mkt[k] = (logloss(pk, yy), brier(pk, yy))
        mkt["landed"] = float(yy.mean())
        mkt["said_exchange"] = float(pm.mean())
    return out, mkt


def _d(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d %b %Y")


def markdown(res: dict) -> str:
    L = []
    L.append(f"{res['n_matches']} matches, {res['n_rows']} side rows, {res['n_test']} in the four test windows, "
             f"{res['n_common']} priced by every model (the heuristic needs nine starters and seven with three "
             f"real appearances).\n")
    L.append("| Window | From | To |\n|---|---|---|")
    for i, (a, b) in enumerate(res["windows"]):
        L.append(f"| {i + 1} | {_d(a)} | {_d(b - 1)} |")
    L.append("\n### Team cards, log loss by window (mean of the 0.5, 1.5, 2.5 and 3.5 lines; lower is better)\n")
    L.append("| Model | W1 | W2 | W3 | W4 | Brier W1-W4 |\n|---|---|---|---|---|---|")
    for k, v in res["per_window"].items():
        L.append(f"| {k} | " + " | ".join(f"{x[0]:.4f}" for x in v) + " | "
                 + " / ".join(f"{x[1]:.4f}" for x in v) + " |")
    L.append(f"\nChosen on windows 1 and 2: **{res['chosen']}**.\n")
    L.append("### Team cards by line, all four windows (log loss / Brier)\n")
    L.append("| Model | " + " | ".join(f"over {x}" for x in TEAM_LINES) + " |\n|---|" + "---|" * len(TEAM_LINES))
    for k, v in res["per_line"].items():
        L.append(f"| {k} | " + " | ".join(f"{v[x][0]:.4f} / {v[x][1]:.4f}" for x in TEAM_LINES) + " |")
    L.append("\n### Chosen model minus the others, log loss, 95% interval resampling matches (negative favours the chosen model)\n")
    L.append("| Against | Windows | Difference | 95% interval |\n|---|---|---|---|")
    for k, (d, lo, hi) in res["boot"].items():
        a, b = k.split(" | ")
        L.append(f"| {a} | {b} | {d:+.4f} | {lo:+.4f} to {hi:+.4f} |")
    L.append("\n### Average cards a side, said against landed (common rows)\n")
    L.append("| Model | Said | Landed |\n|---|---|---|")
    for k, (s, g) in res["level"].items():
        L.append(f"| {k} | {s:.3f} | {g:.3f} |")
    hs = res["info"].get("heuristic_scale")
    if hs:
        L.append(f"\nThe heuristic's XI adds up to {1 / np.mean(hs):.2f} of the side's cards on the training data "
                 f"(scale {', '.join(f'{x:.2f}' for x in hs)} by window); it is scored above with that scale applied, "
                 f"which is its best case.\n")
    L.append("### Calibration, the four team lines pooled\n")
    for k, rows in res["calibration"].items():
        L.append(f"**{k}**\n\n| Said | n | Average said | Landed |\n|---|---|---|---|")
        for lo, hi, n, s, g in rows:
            L.append(f"| {lo:.0%} to {min(hi, 1):.0%} | {n} | {s:.1%} | {g:.1%} |")
        L.append("")
    L.append("### Match cards (both sides' yellows), log loss / Brier\n")
    L.append("| Model | " + " | ".join(f"over {x}" for x in MATCH_LINES) + " |\n|---|" + "---|" * len(MATCH_LINES))
    for k, v in res["match"].items():
        L.append(f"| {k} | " + " | ".join(f"{v[x][0]:.4f} / {v[x][1]:.4f}" for x in MATCH_LINES) + " |")
    pl = res.get("players") or {"n": 0}
    L.append("\n### To be booked, player by player\n")
    if pl["n"] < MIN_PLAYER_LABELS:
        L.append(f"{pl['n']} test-window starters have their match's incidents cached, under the "
                 f"{MIN_PLAYER_LABELS} this test needs. The cache holds no per-player cards until "
                 f"cards_backfill.py has run on the Mac; re-run `cards_model.py test` then.\n")
    else:
        d, lo, hi = pl["boot"]
        L.append(f"{pl['n']} starters with incidents; {pl['landed']:.1%} were booked.\n")
        L.append("| Chance | Log loss | Brier | Average said |\n|---|---|---|---|")
        for k in ("heuristic", "model"):
            a, b, s = pl[k]
            L.append(f"| {'Page heuristic (current)' if k == 'heuristic' else 'Cards model split'} | {a:.4f} | {b:.4f} | {s:.1%} |")
        L.append(f"\nCards model minus heuristic: {d:+.4f} (95% interval {lo:+.4f} to {hi:+.4f}).\n")
        for k, rows in pl["calibration"].items():
            L.append(f"**{k}**\n\n| Said | n | Average said | Landed |\n|---|---|---|---|")
            for a, b, n, s, g in rows:
                L.append(f"| {a:.0%} to {min(b, 1):.0%} | {n} | {s:.1%} | {g:.1%} |")
            L.append("")
    mk = res["market"]
    L.append(f"\n### Against the exchange: {mk['n']} match cards prices on {mk['events']} matches in the test windows\n")
    if mk["n"]:
        L.append(f"Landed {mk['landed']:.1%}; the exchange said {mk['said_exchange']:.1%} on average.\n")
        L.append("| Source | Log loss | Brier |\n|---|---|---|")
        for k, v in mk.items():
            if isinstance(v, tuple):
                L.append(f"| {k} | {v[0]:.4f} | {v[1]:.4f} |")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ the fit and the live model

def starter_share(matches: list[dict]) -> float:
    """Share of a side's cards that fall to its outfield starters.

    The cache never says who was booked, so this is worked out from who was
    on the pitch when: each half's cards per player-minute (the second half
    carries about two thirds of them), starters from the first minute,
    substitutes from 90 minus their minutes, every outfield player alike.
    Keepers are left out on both sides: they are rarely booked, and the
    page gives them no chance."""
    c1 = c2 = 0.0
    st = [0.0, 0.0]
    al = [0.0, 0.0]
    for m in matches:
        if not (m["y1"] and m["y2"]):
            continue
        c1 += sum(m["y1"])
        c2 += sum(m["y2"])
        for side in ("home", "away"):
            for p in m["players"][side]:
                mn = min(90, p["min"] or 0)
                if mn <= 0 or p["pos"] == "G":
                    continue
                a, b = (min(45, mn), max(0, mn - 45)) if not p["sub"] else (max(0, mn - 45), min(45, mn))
                al[0] += a
                al[1] += b
                if not p["sub"]:
                    st[0] += a
                    st[1] += b
    r1, r2 = c1 / max(1, al[0]), c2 / max(1, al[1])
    return (st[0] * r1 + st[1] * r2) / max(1e-9, al[0] * r1 + al[1] * r2)


FIT = ROOT / "cards_fit.json"


def fit(cache: Path = CACHE, variant: str | None = None, res: dict | None = None) -> dict:
    """Refit the chosen variant on every row and write cards_fit.json."""
    matches = load(cache)
    rows = rows_from(matches)
    variant = variant or (res or {}).get("chosen") or "N4 +fouls+elo"
    m = GLMCards(VARIANTS[variant]).fit(rows)
    tot = defaultdict(float)
    mus = defaultdict(float)
    for r, mu in zip(rows, m.mu(rows)):
        tot[r["match"]] += r["y"]
        mus[r["match"]] += mu
    both = [k for k in tot if k in mus]
    out = {"variant": variant, "columns": VARIANTS[variant], "coef": [float(v) for v in m.b],
           "alpha": m.alpha,
           "alpha_match": alpha_of(np.array([tot[k] for k in both]), np.array([mus[k] for k in both])),
           "starter_share": starter_share(matches), "rows": len(rows),
           "fitted_to": max(r["ts"] for r in rows)}
    if res:
        out["backtest"] = {"chosen": res["chosen"], "boot": res["boot"], "per_window": res["per_window"]}
    FIT.write_text(json.dumps(out, indent=1))
    return out


def xi_weights(starters: list[dict]) -> list[float | None]:
    """Each starter's weight in the XI: the page's fouls per 90 over his
    expected minutes, half last ten and half everything. Cards per foul and
    the side's projected fouls are the same for the whole side, so they
    cancel once the XI is scaled to the side's total and are left out."""
    out = []
    for p in starters:
        a, b = heuristic_lambda(p["recent"], 1.0, 1.0), heuristic_lambda(p["played"], 1.0, 1.0)
        out.append(None if a is None or b is None else (a + b) / 2)
    return out


def xi_chances(weights: list[float | None], side_mu: float, share: float) -> list[float | None]:
    """To be booked for each starter: his share of the XI's weight times the
    cards the XI is expected to pick up (the side's expected cards times the
    starters' share). A starter with too thin a record to weigh is given the
    mean of the rest for the split, and no chance of his own."""
    known = [w for w in weights if w is not None]
    if not known:
        return [None] * len(weights)
    fill = sum(known) / len(known)
    total = sum(w if w is not None else fill for w in weights)
    if total <= 0:
        return [None] * len(weights)
    return [None if w is None else 1 - math.exp(-share * side_mu * w / total) for w in weights]


class Live:
    """The fitted cards model at "now": every finished match in the cache
    replayed through the same State the backtest uses."""

    def __init__(self, cache: Path = CACHE, fit_data: dict | None = None):
        self.fit = fit_data or json.loads(FIT.read_text())
        self.cols = self.fit["columns"]
        self.b = np.array(self.fit["coef"])
        self.S = State()
        self.last_tid = {}
        for m in load(cache):
            self.S.add(m)
            self.last_tid[m["home"]] = self.last_tid[m["away"]] = m["tid"]

    def side_mu(self, team, opp, home: bool, tid=None) -> dict | None:
        tid = tid if tid is not None else self.last_tid.get(team)
        x = self.S.side(team, opp, home, tid)
        if x is None:
            return None
        mu = float(np.exp(design([x], self.cols) @ self.b)[0])
        # the names context.py reads for the "opponent x" line on a team leg
        x = dict(x, **{"own_Yellow cards": x["own_y10"], "opp_conc_Yellow cards": x["prov_y10"]})
        return {"mu": mu, "alpha": self.fit["alpha"], "x": x, "kind": "cards model"}

    def player_chances(self, team, opp, home: bool, tid, xi: list[dict]) -> dict:
        """xi: the starters as {pid, pos} (keepers are skipped). Returns
        {pid: chance} for every outfield starter the model can weigh."""
        side = self.side_mu(team, opp, home, tid)
        if side is None:
            return {}
        st = self.S.starters([{"pid": p.get("pid"), "pos": p.get("pos"), "sub": False} for p in xi])
        ps = xi_chances(xi_weights(st), side["mu"], self.fit["starter_share"])
        return {s["pid"]: p for s, p in zip(st, ps) if p is not None}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["test", "fit"])
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--md")
    a = ap.parse_args(argv)
    if a.cmd == "fit":
        res = run(Path(a.cache))
        out = fit(Path(a.cache), res=res)
        print(json.dumps({k: out[k] for k in ("variant", "coef", "alpha", "alpha_match", "starter_share", "rows")}))
        return
    res = run(Path(a.cache), Path(a.md) if a.md else None)
    print(markdown(res))
    print(json.dumps({k: res[k] for k in ("chosen", "info")}, default=str))


if __name__ == "__main__":
    sys.exit(main())
