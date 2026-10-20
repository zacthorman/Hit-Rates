"""Pre-kick-off features for every starter in every match.

Strictly causal: every feature for a match is built from matches that started
before it. Rows are starters who played (Paddy Power voids a non-starter's bet;
the line-up is known about an hour before kick-off, when the bets are placed).
"""
import math
from collections import defaultdict, deque
import numpy as np
import pandas as pd

D = "/home/claude/bt/data"
STATS = ["shots", "sot", "fouls", "fouled", "tackles", "goals", "assists", "xg", "xa", "keypass",
         "dribbles", "touches", "intercepts", "duelwon", "recoveries", "crosses", "passes",
         "dispossessed", "aerialwon", "challengelost", "clearances"]
TARGETS = ["shots", "sot", "fouls", "fouled", "tackles", "goals", "assists"]
TEAMF = ["Ball possession", "Total shots", "Shots on target", "Fouls", "Tackles", "Dribbles", "Crosses",
         "Long balls", "Final third entries", "Touches in penalty area", "Yellow cards", "Expected goals",
         "Corner kicks", "Interceptions", "Passes", "Fouled in final third"]
# Coverage: a match counts for a stat only if its player numbers add up to
# something like the team's. Some leagues carry no player fouls at all.
COVER = {"fouls": "Fouls", "fouled": "a_Fouls", "shots": "Total shots", "sot": "Shots on target",
         "tackles": "Total tackles"}


def per90(vals, mins):
    m = sum(mins)
    return sum(vals) / m * 90 if m > 0 else np.nan


def main():
    P = pd.read_parquet(f"{D}/players.parquet")
    T = pd.read_parquet(f"{D}/teams.parquet")
    M = pd.read_parquet(f"{D}/matches.parquet").sort_values("ts")

    # --- coverage: decided once in build.py (cov_* on players.parquet)
    # goals/assists/xg etc are basic: covered if minutes recorded
    P = P[P.mins > 0].copy()

    # --- Elo over every match in order
    elo = defaultdict(lambda: 1500.0)
    pre_elo = {}
    for r in M.itertuples():
        h, a = elo[r.home], elo[r.away]
        pre_elo[r.match] = (h, a)
        if r.hg is None or r.ag is None or (isinstance(r.hg, float) and math.isnan(r.hg)):
            continue
        exp = 1 / (1 + 10 ** ((a - h - 60) / 400))
        res = 1.0 if r.hg > r.ag else 0.5 if r.hg == r.ag else 0.0
        k = 20 * (1 + abs(r.hg - r.ag)) ** 0.5
        elo[r.home] += k * (res - exp); elo[r.away] -= k * (res - exp)

    # --- team rolling style (last 10), for and against, plus league fouls level
    T = T.sort_values("ts")
    team_hist = defaultdict(lambda: deque(maxlen=10))
    team_feat = {}
    comp_of = dict(zip(M.match, M.comp_id))
    league_hist = defaultdict(lambda: deque(maxlen=200))
    league_feat = {}
    for mid, grp in T.groupby("match", sort=False):
        pass
    T_by_match = {mid: g for mid, g in T.groupby("match")}
    # also per team: what opponents' players by position did against them (positional concession)
    concede = defaultdict(lambda: defaultdict(lambda: deque(maxlen=10)))   # team -> pos -> deque of per90 dicts
    team_concede_feat = {}
    Pm = {mid: g for mid, g in P.groupby("match")}
    ts_of = dict(zip(M.match, M.ts))
    pending_league = []          # (comp, fouls) held until the kick-off time changes
    current_ts = None
    for mid in M.match:
        g = T_by_match.get(mid)
        if g is None:
            continue
        if ts_of[mid] != current_ts:
            for cid_, v in pending_league:
                league_hist[cid_].append(v)
            pending_league, current_ts = [], ts_of[mid]
        cid = comp_of.get(mid)
        lf = league_hist[cid]
        league_feat[mid] = {"lg_fouls": np.mean([x for x in lf]) if lf else np.nan}
        for r in g.itertuples(index=False):
            h = team_hist[r.team]
            feat = {}
            for k in TEAMF:
                fv = [x["f_" + k] for x in h if x.get("f_" + k) is not None and not pd.isna(x.get("f_" + k))]
                av = [x["a_" + k] for x in h if x.get("a_" + k) is not None and not pd.isna(x.get("a_" + k))]
                feat["tf_" + k] = np.mean(fv) if fv else np.nan
                feat["ta_" + k] = np.mean(av) if av else np.nan
            feat["t_n"] = len(h)
            team_feat[(mid, r.team)] = feat
            # positional concession feature (before this match)
            cf = {}
            for pos in "DMF":
                dq = concede[r.team][pos]
                for s in ("fouls", "fouled", "shots", "tackles", "sot"):
                    v = [x[s] for x in dq if not pd.isna(x.get(s, np.nan))]
                    cf[f"oc_{pos}_{s}"] = np.mean(v) if v else np.nan
            team_concede_feat[(mid, r.team)] = cf
        # update after
        for rec in g.to_dict("records"):
            team_hist[rec["team"]].append(rec)
        fsum = g["f_Fouls"].sum(min_count=2)
        if not pd.isna(fsum):
            pending_league.append((cid, fsum))
        pm = Pm.get(mid)
        if pm is not None:
            for team in g.team:
                opp_players = pm[(pm.team != team) & (pm.starter == 1)]
                for pos in "DMF":
                    sub = opp_players[opp_players.pos == pos]
                    if len(sub) == 0:
                        continue
                    d = {}
                    for s in ("fouls", "fouled", "shots", "tackles", "sot"):
                        if s in COVER and not sub["cov_" + s].all():
                            d[s] = np.nan
                        else:
                            d[s] = per90(sub[s].tolist(), sub.mins.tolist())
                    concede[team][pos].append(d)

    # --- player histories
    P = P.sort_values(["ts", "match"])
    hist = defaultdict(list)          # pid -> list of dicts (appearances)
    h2h = defaultdict(list)           # (pid, opp) -> list
    rows = []
    # pre-index players per match for partners / matchups
    for mid, pm in P.groupby("match", sort=False):
        ts = pm.ts.iloc[0]
        # snapshot each player's prior profile
        prof = {}
        for r in pm.itertuples(index=False):
            hh = hist[r.pid]
            prof[r.pid] = profile(hh)
        el = pre_elo.get(mid, (1500, 1500))
        lg = league_feat.get(mid, {})
        for r in pm.itertuples(index=False):
            if r.starter != 1:
                continue
            pr = prof[r.pid]
            if pr["n"] < 3:
                continue
            f = {"match": mid, "ts": ts, "pid": r.pid, "name": r.name, "team": r.team, "opp": r.opp,
                 "home": r.home, "pos": r.pos, "depth": r.depth, "lat": r.lat, "linesize": r.linesize,
                 "comp": comp_of.get(mid)}
            f.update({k: v for k, v in pr.items() if k != "_raw"})
            f["days_rest"] = (ts - pr["days_rest"]) / 86400 if not pd.isna(pr.get("days_rest", np.nan)) else np.nan
            me, op = (el[0], el[1]) if r.home else (el[1], el[0])
            f["elo_diff"] = me - op
            f.update(lg)
            f.update({k: v for k, v in team_feat.get((mid, r.team), {}).items()})
            f.update({"o" + k: v for k, v in team_feat.get((mid, r.opp), {}).items()})
            oc = team_concede_feat.get((mid, r.opp), {})
            for s in ("fouls", "fouled", "shots", "tackles", "sot"):
                f["oc_" + s] = oc.get(f"oc_{r.pos}_{s}", np.nan) if r.pos in "DMF" else np.nan
            # partners: same team, same line, starters
            if r.depth is not None and not pd.isna(r.depth):
                mates = pm[(pm.team == r.team) & (pm.starter == 1) & (pm.pid != r.pid) & (pm.depth == r.depth)]
                if len(mates):
                    f["mate_att"] = np.nanmean([prof[m]["att_idx"] for m in mates.pid])
                    f["mate_def"] = np.nanmean([prof[m]["def_idx"] for m in mates.pid])
                    f["mate_fouls90"] = np.nanmean([prof[m].get("fouls_p90_10", np.nan) for m in mates.pid])
                    tot = f["mate_def"] * len(mates) + pr["def_idx"]
                    f["def_share_line"] = pr["def_idx"] / tot if tot and not pd.isna(tot) and tot > 0 else np.nan
                    f["att_minus_mates"] = pr["att_idx"] - f["mate_att"]
                # opponents facing him
                opp = pm[(pm.team == r.opp) & (pm.starter == 1) & pm.depth.notna()]
                if len(opp):
                    want_d, want_l = 1 - r.depth, 1 - (r.lat if r.lat is not None and not pd.isna(r.lat) else 0.5)
                    dist = (opp.depth - want_d).abs() + 0.7 * (opp.lat.fillna(0.5) - want_l).abs()
                    near = opp.loc[dist.nsmallest(2).index]
                    for s in ("fouls", "fouled", "tackles", "dribbles", "shots"):
                        vals = [prof[q].get(f"{s}_p90_10", np.nan) for q in near.pid if q in prof]
                        f["vs_" + s] = np.nanmean(vals) if vals else np.nan
                    f["vs_att"] = np.nanmean([prof[q]["att_idx"] for q in near.pid])
                    f["vs_def"] = np.nanmean([prof[q]["def_idx"] for q in near.pid])
            # head to head: him against this opponent before
            hh = h2h[(r.pid, r.opp)]
            f["h2h_n"] = len(hh)
            for s in ("fouls", "fouled", "shots", "tackles", "sot"):
                v = [x for x in hh if x.get("cov_" + s, True)]
                f["h2h_" + s] = per90([x[s] for x in v], [x["mins"] for x in v]) if v else np.nan
            # targets and coverage
            for s in TARGETS:
                f["y_" + s] = getattr(r, s)
                f["c_" + s] = bool(getattr(r, "cov_" + s)) if s in COVER else True
            f["y_mins"] = r.mins
            rows.append(f)
        # update histories after the match
        for r in pm.itertuples(index=False):
            d = {s: getattr(r, s) for s in STATS}
            d.update({"mins": r.mins, "starter": r.starter, "ts": r.ts, "team": r.team})
            for s in COVER:
                d["cov_" + s] = bool(getattr(r, "cov_" + s))
            hist[r.pid].append(d)
            h2h[(r.pid, r.opp)].append(d)
    F = pd.DataFrame(rows)
    F.to_parquet(f"{D}/features.parquet")
    print(F.shape)


def profile(hh):
    """A player's record before this match."""
    out = {"n": sum(1 for x in hh if x["mins"] >= 45)}
    if not hh:
        return {**out, **{k: np.nan for k in ("att_idx", "def_idx", "fouls_p90_10")}, "start_rate": np.nan}
    last = hh[-38:]
    full = [x for x in last if x["mins"] >= 45]
    out["start_rate"] = np.mean([x["starter"] for x in hh[-10:]])
    out["mins_avg5"] = np.mean([x["mins"] for x in hh[-5:]])
    out["days_rest"] = (hh[-1]["ts"]) if hh else np.nan
    for s in STATS:
        for w, name in ((5, "5"), (10, "10"), (38, "38")):
            sel = [x for x in full[-w:] if x.get("cov_" + s, True)]
            out[f"{s}_p90_{name}"] = per90([x[s] for x in sel], [x["mins"] for x in sel]) if sel else np.nan
        # exponentially weighted per 90 (half-life 6 games)
        sel = [x for x in full if x.get("cov_" + s, True)]
        if sel:
            w = np.array([0.5 ** ((len(sel) - 1 - i) / 6) for i in range(len(sel))])
            v = np.array([x[s] for x in sel]); m = np.array([x["mins"] for x in sel])
            out[f"{s}_ew"] = (w * v).sum() / (w * m).sum() * 90
        else:
            out[f"{s}_ew"] = np.nan
    # raw hit rates, last 10, at the common lines (what the site shows)
    for s in TARGETS:
        sel = [x for x in full[-10:] if x.get("cov_" + s, True)]
        for k in (1, 2, 3):
            out[f"{s}_hit{k}_10"] = np.mean([x[s] >= k for x in sel]) if sel else np.nan
    a = out
    def g(k): return 0 if pd.isna(a.get(k)) else a[k]
    out["att_idx"] = g("shots_p90_10") + g("keypass_p90_10") + 3 * g("xg_p90_10")
    out["def_idx"] = g("tackles_p90_10") + g("fouls_p90_10") + g("intercepts_p90_10")
    return out


if __name__ == "__main__":
    main()
