#!/usr/bin/env python3
"""
Walk-forward backtest of the game state, and the fit the pages use.

    .venv/bin/python -B gs_backtest.py build    # matches + line-ups from cache/ -> cache/gs_dataset.json
    .venv/bin/python -B gs_backtest.py test     # walk forward, write gs_fit.json and GS_BACKTEST.md

The question. The game state says: Bayern usually have 67% of the ball,
tonight they should have 58%, so their shots come down and Arsenal's
tackles go up. Is that true, and how much? A rule that sounds right and
is not tested is how a page ends up claiming 93% for a 70% bet.

So every match in the cache is replayed in date order using only what was
known before it kicked off:

  possession  each side's usual share over its previous 10 games, run
              through gamestate.py's formula to a predicted share tonight
  team stat   for shots, shots on target, corners, fouls, tackles, cards,
              clearances and saves, four ways of predicting the count:
                M0 own   the side's own average over its last 10
                M1 +opp  own average and what the opponent allows, fitted
                M2 +gs   M1 plus the possession factor, fitted
                GS page  own average times gamestate.py's factor, unfitted
  player stat for shots, shots on target, fouls, fouled and tackles, the same
              ladder on each starter's last-10 average

Each model is fitted on every match before a test month and scored on that
month (Poisson deviance, and the log loss of the over/under at the line
nearest the average), so a model is only credited with what it would have
known. The final coefficients, fitted on everything, go to gs_fit.json, and
context.py uses them only for a stat where M2 beat M1 out of sample.
"""

from __future__ import annotations

import json
import math
import probability
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
DATA = CACHE / "gs_dataset.json"
FIT = ROOT / "gs_fit.json"
REPORT = ROOT / "GS_BACKTEST.md"

WINDOW = 10        # prior games behind every average
MIN_PRIOR = 6      # fewest prior games with stats before a match is used
MIN_PLAYER = 5     # fewest prior starts for a player row
MIN_MINUTES = 60   # a start counts at this many minutes

# stat -> +1 if more of the ball means more of it, -1 if fewer
TEAM_STATS = {"Total shots": +1, "Shots on target": +1, "Corner kicks": +1, "Big chances": +1,
              "Fouls": -1, "Total tackles": -1, "Yellow cards": -1, "Clearances": -1,
              "Goalkeeper saves": -1}
# player stat -> (lineups key, team stat whose opponent-allowed figure it reads, ball sign)
PLAYER_STATS = {"Shots": ("totalShots", ("Total shots", "against"), +1),
                "Shots on target": ("onTargetScoringAttempt", ("Shots on target", "against"), +1),
                "Fouls": ("fouls", ("Fouls", "own"), -1),
                "Fouled": ("wasFouled", ("Fouls", "against_own"), +1),
                "Tackles": ("totalTackle", ("Total tackles", "own"), -1)}
WANT = set(TEAM_STATS) | {"Ball possession", "Total tackles", "Fouls"}


# ------------------------------------------------------------------ dataset

def _stats(eid):
    try:
        d = json.loads((CACHE / f"event_{eid}_statistics.json").read_text())
    except (OSError, ValueError):
        return None
    for block in d.get("statistics") or []:
        if block.get("period") != "ALL":
            continue
        out = {"home": {}, "away": {}}
        for g in block.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                n = it.get("name")
                if n in WANT and isinstance(it.get("homeValue"), (int, float)):
                    out["home"].setdefault(n, it["homeValue"])
                    out["away"].setdefault(n, it.get("awayValue"))
        return out if out["home"].get("Ball possession") is not None else None
    return None


def _lineup(eid):
    try:
        d = json.loads((CACHE / f"event_{eid}_lineups.json").read_text())
    except (OSError, ValueError):
        return None
    out = {}
    for side in ("home", "away"):
        rows = []
        for p in (d.get(side) or {}).get("players") or []:
            s = p.get("statistics") or {}
            mins = s.get("minutesPlayed") or 0
            if mins < MIN_MINUTES or p.get("position") == "G":
                continue
            rows.append({"pid": (p.get("player") or {}).get("id"), "min": mins,
                         **{k: s.get(v[0]) or 0 for k, v in PLAYER_STATS.items()}})
        out[side] = rows
    return out


def build() -> None:
    import strength
    events = strength.load_events(CACHE)
    rows = []
    for e in events:
        st = _stats(e["id"])
        if not st:
            continue
        rows.append({"id": e["id"], "ts": e["ts"], "home": e["home"], "away": e["away"],
                     "tid": e["tid"], "kind": e["kind"], "hg": e["hg"], "ag": e["ag"],
                     "stats": st, "lineup": _lineup(e["id"])})
    DATA.write_text(json.dumps(rows))
    with_lu = sum(1 for r in rows if r["lineup"])
    print(f"{len(rows)} matches with statistics ({with_lu} with line-ups) -> {DATA}")


# ------------------------------------------------------------------ helpers

def predicted_possession(home_usual, away_usual):
    """gamestate.py's gsState: each side's usual share -> tonight's, home side first."""
    lg = lambda p: math.log(p / (1 - p))  # noqa: E731
    h = min(0.85, max(0.15, home_usual / 100))
    a = min(0.85, max(0.15, away_usual / 100))
    lo = 0.85 * (lg(h) - lg(a)) + 0.06
    p0 = 100 / (1 + math.exp(-lo))
    return p0, 100 - p0


def ball_factor(here, usual, sign):
    f = here / usual if sign > 0 else (100 - here) / (100 - usual)
    return min(1.6, max(0.6, f))


def fit_poisson(X, y, ridge=1e-4, iters=50):
    b = np.zeros(X.shape[1])
    b[0] = math.log(max(1e-6, y.mean()))
    for _ in range(iters):
        eta = np.clip(X @ b, -10, 10)
        mu = np.exp(eta)
        grad = X.T @ (y - mu) - ridge * b
        H = (X * mu[:, None]).T @ X + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return b


def deviance(y, mu):
    mu = np.maximum(mu, 1e-9)
    t = np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0)
    return float(np.mean(2 * (t - (y - mu))))


nb_alpha = probability.nb_alpha


p_at_least = probability.nb_at_least


def logloss_over(y, mu, own, alpha):
    """Log loss of 'over the line nearest the side's own average' (line = floor(own) + 0.5)."""
    tot = 0.0
    for yi, mi, oi in zip(y, mu, own):
        k = int(math.floor(oi)) + 1
        p = min(0.999, max(0.001, p_at_least(k, mi, alpha)))
        tot += -math.log(p if yi >= k else 1 - p)
    return tot / max(1, len(y))


# ------------------------------------------------------------ the replays

def team_rows(matches):
    hist = defaultdict(list)          # team -> list of (ts, own stats, opp stats)
    out = []
    for m in matches:
        sides = [("home", m["home"], m["away"]), ("away", m["away"], m["home"])]
        prior = {t: hist[t][-WINDOW:] for _, t, _ in sides}
        ok = all(len(prior[t]) >= MIN_PRIOR for _, t, _ in sides)
        if ok:
            usual = {t: np.mean([h[1]["Ball possession"] for h in prior[t]]) for _, t, _ in sides}
            ph, pa = predicted_possession(usual[m["home"]], usual[m["away"]])
            here = {m["home"]: ph, m["away"]: pa}
            for side, t, o in sides:
                own_now = m["stats"][side]
                actual_poss = own_now.get("Ball possession")
                row = {"ts": m["ts"], "home": side == "home", "poss_pred": here[t], "poss_usual": usual[t],
                       "poss_actual": actual_poss, "stats": {}}
                for s, sign in TEAM_STATS.items():
                    y = own_now.get(s)
                    own = [h[1].get(s) for h in prior[t] if h[1].get(s) is not None]
                    allow = [h[2].get(s) for h in prior[o] if h[2].get(s) is not None]
                    if y is None or len(own) < MIN_PRIOR or len(allow) < MIN_PRIOR:
                        continue
                    row["stats"][s] = {"y": y, "own": max(0.1, np.mean(own)), "allow": max(0.1, np.mean(allow)),
                                       "f": ball_factor(here[t], usual[t], sign)}
                out.append(row)
        for side, t, o in sides:
            other = "away" if side == "home" else "home"
            hist[t].append((m["ts"], m["stats"][side], m["stats"][other]))
    return out


def player_rows(matches):
    team_hist = defaultdict(list)
    player_hist = defaultdict(list)
    out = []
    for m in matches:
        lu = m.get("lineup")
        sides = [("home", m["home"], m["away"]), ("away", m["away"], m["home"])]
        prior = {t: team_hist[t][-WINDOW:] for _, t, _ in sides}
        ok = lu and all(len(prior[t]) >= MIN_PRIOR for _, t, _ in sides)
        if ok:
            usual = {t: np.mean([h[1]["Ball possession"] for h in prior[t]]) for _, t, _ in sides}
            ph, pa = predicted_possession(usual[m["home"]], usual[m["away"]])
            here = {m["home"]: ph, m["away"]: pa}
            for side, t, o in sides:
                for p in lu.get(side) or []:
                    ph_ = player_hist[p["pid"]][-WINDOW:]
                    if len(ph_) < MIN_PLAYER:
                        continue
                    row = {"ts": m["ts"], "stats": {}}
                    for s, (key, (team_stat, mode), sign) in PLAYER_STATS.items():
                        avg = np.mean([h[s] for h in ph_])
                        if avg <= 0:
                            continue
                        # the opponent's allowance against what this side usually sees
                        if mode == "against":
                            allow = np.mean([h[2].get(team_stat, 0) for h in prior[o]])
                            usual_team = np.mean([h[1].get(team_stat, 0) for h in prior[t]])
                        elif mode == "own":
                            allow = np.mean([h[2].get(team_stat, 0) for h in prior[o]])
                            usual_team = np.mean([h[1].get(team_stat, 0) for h in prior[t]])
                        else:   # fouled: the opponent's own fouls committed
                            allow = np.mean([h[1].get(team_stat, 0) for h in prior[o]])
                            usual_team = np.mean([h[2].get(team_stat, 0) for h in prior[t]])
                        oppf = (allow / usual_team) if usual_team > 0 and allow > 0 else 1.0
                        row["stats"][s] = {"y": p[s], "own": max(0.05, avg), "allow": max(0.2, min(5, oppf)),
                                           "f": ball_factor(here[t], usual[t], sign)}
                    out.append(row)
        for side, t, o in sides:
            other = "away" if side == "home" else "home"
            team_hist[t].append((m["ts"], m["stats"][side], m["stats"][other]))
            for p in (lu or {}).get(side) or []:
                player_hist[p["pid"]].append(p)
    return out


# ------------------------------------------------------------ the scoring

def design(recs, kind):
    own = np.array([r["own"] for r in recs])
    allow = np.array([r["allow"] for r in recs])
    f = np.array([r["f"] for r in recs])
    home = np.array([1.0 if r.get("home") else 0.0 for r in recs])
    cols = [np.ones(len(recs)), np.log(own)]
    if kind in ("M1", "M2"):
        cols.append(np.log(allow))
        if "home" in recs[0]:
            cols.append(home)
    if kind == "M2":
        cols.append(np.log(f))
    return np.column_stack(cols)


def walk_forward(rows, stat, team=True):
    recs = []
    for r in rows:
        x = r["stats"].get(stat)
        if x:
            recs.append({**x, "ts": r["ts"], **({"home": r["home"]} if team else {})})
    if len(recs) < 600:
        return None
    recs.sort(key=lambda r: r["ts"])
    ts = np.array([r["ts"] for r in recs])
    cut0 = np.quantile(ts, 0.6)
    edges = np.quantile(ts[ts >= cut0], [0, 0.25, 0.5, 0.75, 1.0])
    res = defaultdict(lambda: {"dev": 0.0, "ll": 0.0, "n": 0})
    for a, b in zip(edges[:-1], edges[1:]):
        train = [r for r in recs if r["ts"] < a]
        test = [r for r in recs if a <= r["ts"] <= b]
        if len(train) < 300 or len(test) < 50:
            continue
        ytr = np.array([r["y"] for r in train], dtype=float)
        yte = np.array([r["y"] for r in test], dtype=float)
        own_te = np.array([r["own"] for r in test])
        preds = {}
        preds["M0"] = (own_te, own_te_tr := np.array([r["own"] for r in train]))
        for kind in ("M1", "M2"):
            bt = fit_poisson(design(train, kind), ytr)
            preds[kind] = (np.exp(design(test, kind) @ bt), np.exp(design(train, kind) @ bt))
        f_te = np.array([r["f"] for r in test])
        f_tr = np.array([r["f"] for r in train])
        preds["GS"] = (own_te * f_te, own_te_tr * f_tr)
        for kind, (mu_te, mu_tr) in preds.items():
            alpha = nb_alpha(ytr, mu_tr)
            res[kind]["dev"] += deviance(yte, mu_te) * len(test)
            res[kind]["ll"] += logloss_over(yte, mu_te, own_te, alpha) * len(test)
            res[kind]["n"] += len(test)
    if not res:
        return None
    out = {k: {"dev": v["dev"] / v["n"], "ll": v["ll"] / v["n"], "n": v["n"]} for k, v in res.items()}
    # final fit on everything, for the page
    y = np.array([r["y"] for r in recs], dtype=float)
    b = fit_poisson(design(recs, "M2"), y)
    mu = np.exp(design(recs, "M2") @ b)
    out["coef"] = [float(x) for x in b]
    out["alpha"] = nb_alpha(y, mu)
    out["n_all"] = len(recs)
    return out


def test() -> None:
    matches = json.loads(DATA.read_text())
    matches.sort(key=lambda m: (m["ts"], m["id"]))
    trows = team_rows(matches)
    prows = player_rows(matches)
    pe = [abs(r["poss_pred"] - r["poss_actual"]) for r in trows if r["poss_actual"] is not None]
    pu = [abs(r["poss_usual"] - r["poss_actual"]) for r in trows if r["poss_actual"] is not None]
    fit = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "matches": len(matches), "team_rows": len(trows), "player_rows": len(prows),
           "possession": {"mae_predicted": float(np.mean(pe)), "mae_usual_only": float(np.mean(pu))},
           "team": {}, "player": {}}
    for s in TEAM_STATS:
        r = walk_forward(trows, s, team=True)
        if r:
            fit["team"][s] = r
    for s in PLAYER_STATS:
        r = walk_forward(prows, s, team=False)
        if r:
            fit["player"][s] = r
    for scope in ("team", "player"):
        for s, r in fit[scope].items():
            r["use"] = bool(r["M2"]["ll"] < r["M1"]["ll"] - 1e-4 and r["M2"]["dev"] < r["M1"]["dev"])
            r["better_than_page"] = bool(r["M2"]["ll"] < r["GS"]["ll"])
    FIT.write_text(json.dumps(fit, indent=1))
    lines = [f"# Game state walk-forward backtest\n",
             f"Generated {fit['generated']}. {fit['matches']} matches, {fit['team_rows']} team rows, "
             f"{fit['player_rows']} player rows. Each model fitted on everything before a test window, "
             f"scored on the last 40% of dates in four windows.\n",
             f"Possession: predicted from both sides' usual share, error {fit['possession']['mae_predicted']:.1f} pts; "
             f"a side's usual share alone, {fit['possession']['mae_usual_only']:.1f} pts.\n",
             "Log loss of the over/under at each side's own average (lower is better). "
             "M0 own average, M1 + opponent, M2 + game state, GS the page's unfitted formula.\n"]
    for scope in ("team", "player"):
        lines.append(f"\n## {scope.title()} stats\n\n| Stat | n | M0 | M1 +opp | M2 +gs | GS page | game state coef | used |\n|---|---|---|---|---|---|---|---|")
        for s, r in fit[scope].items():
            lines.append(f"| {s} | {r['M2']['n']} | {r['M0']['ll']:.4f} | {r['M1']['ll']:.4f} | {r['M2']['ll']:.4f} | "
                         f"{r['GS']['ll']:.4f} | {r['coef'][-1]:+.2f} | {'yes' if r['use'] else 'no'} |")
    lines += ["", "## Player calibration at 1+, 2+, 3+", "",
              "Fitted on the first 60% of dates, scored on the rest. 'Said' is the model's average chance "
              "in the bucket, 'got' how often it landed.", ""]
    for s in PLAYER_STATS:
        recs = [{**r["stats"][s], "ts": r["ts"]} for r in prows if s in r["stats"]]
        recs.sort(key=lambda r: r["ts"])
        cut = int(len(recs) * 0.6)
        tr, te = recs[:cut], recs[cut:]
        if len(tr) < 300 or len(te) < 100:
            continue
        ytr = np.array([r["y"] for r in tr], float)
        yte = np.array([r["y"] for r in te], float)
        b = fit_poisson(design(tr, "M2"), ytr)
        alpha = nb_alpha(ytr, np.exp(design(tr, "M2") @ b))
        mu = np.exp(design(te, "M2") @ b)
        for k in (1, 2, 3):
            p = np.array([p_at_least(k, x, alpha) for x in mu])
            cells = []
            for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9)):
                sel = (p >= lo) & (p < hi)
                if sel.sum() >= 50:
                    cells.append(f"{lo:.0%}-{hi:.0%}: said {p[sel].mean():.0%}, got {(yte[sel] >= k).mean():.0%} (n {sel.sum()})")
            if cells:
                lines.append(f"- {s} {k}+: " + "; ".join(cells))
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    {"build": build, "test": test}[cmd]()
