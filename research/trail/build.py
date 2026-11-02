"""Player-match table with pre-match priors, direct opponents and game state.

Reads matches.jsonl.gz (extracted from the SofaScore cache). Football only.
Writes pm.parquet: one row per player-match.
"""
import gzip
import json
import math
from collections import defaultdict, deque

import numpy as np
import pandas as pd

R = [json.loads(l) for l in gzip.open("matches.jsonl.gz", "rt")]
R = [r for r in R if r.get("hf") and r.get("af") and r.get("ts")]
R.sort(key=lambda r: r["ts"])
print("football matches", len(R))

STATS = {"fouls": "fouls", "fouled": "wasFouled", "tackles": "totalTackle", "shots": "totalShots",
         "sot": "onTargetScoringAttempt", "dribbles": "totalContest", "duels": "duelWon",
         "touches": "touches", "lost": "possessionLostCtrl", "interc": "interceptionWon"}
NPRIOR = 10


def timeline(r):
    """Goals as (minute, home?) for game state."""
    g = []
    for i in r.get("inc") or []:
        if i[0] == "g" and i[1] is not None:
            home = i[3]
            if i[6] == "ownGoal":
                home = not home
            g.append((i[1] + (0 if not i[2] or i[2] == 999 else 0), home))
    return sorted(g)


def subs_out(r):
    """player id -> minute he went off; in -> minute he came on."""
    off, on = {}, {}
    for i in r.get("inc") or []:
        if i[0] == "s":
            if i[4]:
                off[i[4]] = i[1]
            if i[5]:
                on[i[5]] = i[1]
    return off, on


def state_minutes(goals, home, a, b):
    """Minutes level / ahead / behind for a side between minute a and b."""
    lv = ah = bh = 0.0
    hs = as_ = 0
    t = a
    events = [(m, h) for m, h in goals]
    cur = 0
    # score at minute a
    for m, h in events:
        if m <= a:
            hs += h; as_ += (not h)
    for m, h in events + [(b, None)]:
        if m <= a:
            continue
        m2 = min(m, b)
        if m2 > t:
            d = (hs - as_) if home else (as_ - hs)
            span = m2 - t
            if d == 0:
                lv += span
            elif d > 0:
                ah += span
            else:
                bh += span
            t = m2
        if h is None or m >= b:
            break
        hs += h; as_ += (not h)
    return lv, ah, bh


hist = defaultdict(lambda: deque(maxlen=NPRIOR))      # pid -> recent (minutes, stats)
pos_hist = defaultdict(lambda: deque(maxlen=NPRIOR))  # pid -> recent (x, y)
team_hist = defaultdict(lambda: deque(maxlen=NPRIOR)) # team -> recent dicts of team stats
rows = []

for r in R:
    goals = timeline(r) if "inc" in r else None
    off, on = subs_out(r)
    sides = []
    for s, oth in (("h", "a"), ("a", "h")):
        team = r["home"] if s == "h" else r["away"]
        opp = r["away"] if s == "h" else r["home"]
        sides.append((s, oth, team, opp))
    # pre-match priors for every player
    prior = {}
    for s, oth, team, opp in sides:
        for p in r[s + "p"]:
            h = hist[p["i"]]
            mins = sum(m for m, _ in h)
            pr = {"apps": len(h), "pmins": mins}
            for k, sk in STATS.items():
                pr["r_" + k] = (sum(st.get(sk, 0) for _, st in h) / mins * 90) if mins >= 90 else np.nan
            ph = pos_hist[p["i"]]
            pr["px"] = np.mean([x for x, _ in ph]) if ph else np.nan
            pr["py"] = np.mean([y for _, y in ph]) if ph else np.nan
            pr["starts_share"] = np.nan
            prior[p["i"]] = pr
    # team priors
    tprior = {}
    for s, oth, team, opp in sides:
        th = team_hist[team]
        tp = {}
        for k in ("Fouls", "Ball possession", "Total shots", "Tackles", "Corner kicks", "Total tackles"):
            vals = [d.get(k) for d in th if d.get(k) is not None]
            tp["t_" + k] = float(np.mean(vals)) if vals else np.nan
            vals = [d.get("opp_" + k) for d in th if d.get("opp_" + k) is not None]
            tp["ta_" + k] = float(np.mean(vals)) if vals else np.nan
        tprior[s] = tp
    # direct opponents from PRIOR positions (pre-match knowable), starters only
    starters = {s: [p for p in r[s + "p"] if not p["s"] and p.get("p") != "G"] for s, *_ in sides}

    def nearest(p, s, oth):
        a = prior[p["i"]]
        if math.isnan(a["px"]):
            return None
        best, bd = None, 1e9
        for q in starters[oth]:
            b = prior[q["i"]]
            if math.isnan(b["px"]):
                continue
            # mirror: opponent's x runs the other way
            d = (a["px"] - (100 - b["px"])) ** 2 + (a["py"] - (100 - b["py"])) ** 2
            if d < bd:
                best, bd = q, d
        return best, math.sqrt(bd) if best else None

    ts_ = r.get("ts_") or {}

    def tv(name, side):
        v = ts_.get(name)
        if not v:
            return None
        x = v[0 if side == "h" else 1]
        try:
            return float(str(x).rstrip("%"))
        except (TypeError, ValueError):
            return None
    mom = r.get("mom")
    for s, oth, team, opp in sides:
        tp, op = tprior[s], tprior[oth]
        for p in r[s + "p"]:
            st = p["st"]
            m = st.get("minutesPlayed") or 0
            row = {"eid": r["id"], "ts": r["ts"], "tour": r["tour"], "side": s, "team": team, "opp": opp,
                   "pid": p["i"], "name": p["n"], "pos": p.get("p"), "sub": p["s"], "min": m,
                   "form": r[s + "f"], "oform": r[oth + "f"]}
            for k, sk in STATS.items():
                row[k] = st.get(sk, 0)
            row.update(prior[p["i"]])
            row.update({k: v for k, v in tp.items()})
            row.update({"o" + k: v for k, v in op.items()})
            row["has_pos"] = p.get("xy") is not None
            if p.get("xy"):
                row["x"], row["y"] = p["xy"][0], p["xy"][1]
            if not p["s"] and p.get("p") != "G":
                nn = nearest(p, s, oth)
                if nn and nn[0]:
                    q, d = nn
                    row["dopp"] = q["n"]
                    row["dopp_dist"] = d
                    qp = prior[q["i"]]
                    for k in STATS:
                        row["d_r_" + k] = qp["r_" + k]
                    # what the direct opponent actually did that game (for the trail)
                    for k, sk in STATS.items():
                        row["d_" + k] = q["st"].get(sk, 0)
                    row["d_min"] = q["st"].get("minutesPlayed")
            # game state while he was on
            if goals is not None and m:
                a = on.get(p["i"], 0) if p["s"] else 0
                b = off.get(p["i"], 90) if p["i"] in off else (a + m if p["s"] else 90)
                lv, ah, bh = state_minutes(goals, s == "h", a, max(a, b))
                row["gs_level"], row["gs_ahead"], row["gs_behind"] = lv, ah, bh
            row["poss"] = tv("Ball possession", s)
            row["team_fouls"], row["opp_fouls"] = tv("Fouls", s), tv("Fouls", oth)
            if mom:
                vals = [v for v in mom if v is not None]
                sgn = 1 if s == "h" else -1
                row["mom_share"] = (sum(max(0, sgn * v) for v in vals) /
                                    max(1, sum(abs(v) for v in vals)))
            rows.append(row)
    # update histories after the match
    for s, oth, team, opp in sides:
        for p in r[s + "p"]:
            m = p["st"].get("minutesPlayed") or 0
            if m >= 15:
                hist[p["i"]].append((m, p["st"]))
            if p.get("xy") and not p["s"]:
                pos_hist[p["i"]].append((p["xy"][0], p["xy"][1]))
        d = {}
        for k in ("Fouls", "Ball possession", "Total shots", "Tackles", "Corner kicks", "Total tackles"):
            a, b = tv(k, s), tv(k, oth)
            if a is not None:
                d[k] = a
            if b is not None:
                d["opp_" + k] = b
        team_hist[team].append(d)

df = pd.DataFrame(rows)
df.to_parquet("pm.parquet")
print(df.shape)
print(df[["has_pos"]].mean(), df["dopp"].notna().sum(), "rows with a pre-match direct opponent")
