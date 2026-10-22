#!/usr/bin/env python3
"""The backtested player model, run live: chances for every starter in the
upcoming football fixtures, written to reports/fmodel.json for the site.

    .venv/bin/python fmodel_live.py              # fixtures in the next 7 days
    .venv/bin/python fmodel_live.py --days 3

What it does:
  1. Reads every finished match in cache/ (line-ups and stats SofaScore has
     already given us; nothing is fetched here).
  2. Adds each upcoming fixture from the reports with its line-up from cache/:
     the confirmed XI once it is out, the predicted XI before that.
  3. Builds the same pre-kick-off features the backtest used, in date order,
     so an upcoming match only ever sees matches that came before it.
  4. Scores 15 lines (shots 1-3+, SOT 1-2+, fouls 1-2+, fouled 1-3+,
     tackles 1-3+, to score, to assist) with the models in fmodel/.

The models were trained in the backtest (LightGBM, January 2025 to June 2026,
tested out of sample from July 2026) and are stored as plain JSON trees, so
this needs only numpy and pandas. See USAGE.md, "Player model".

Chances assume the player starts. A player with fewer than three 45-minute
appearances in the cache gets no model chance and the site falls back to its
own number.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
MODELS = ROOT / "fmodel"
OUT = ROOT / "reports" / "fmodel.json"
sys.path.insert(0, str(MODELS))
from fmodel_trees import Model  # noqa: E402
import pagedata

PSTATS = {
    "totalShots": "shots", "onTargetScoringAttempt": "sot", "fouls": "fouls",
    "wasFouled": "fouled", "totalTackle": "tackles", "goals": "goals",
    "goalAssist": "assists", "expectedGoals": "xg", "expectedAssists": "xa",
    "keyPass": "keypass", "touches": "touches", "totalPass": "passes",
    "interceptionWon": "intercepts", "duelWon": "duelwon", "duelLost": "duellost",
    "totalContest": "dribbles", "wonContest": "dribblewon", "totalCross": "crosses",
    "ballRecovery": "recoveries", "totalClearance": "clearances",
    "dispossessed": "dispossessed", "aerialWon": "aerialwon", "aerialLost": "aeriallost",
    "challengeLost": "challengelost", "possessionLostCtrl": "possloss",
    "totalOffside": "offsides", "saves": "saves", "bigChanceMissed": "bcmissed",
}
TSTATS = ["Ball possession", "Expected goals", "Big chances", "Total shots", "Shots on target",
          "Corner kicks", "Fouls", "Passes", "Tackles", "Free kicks", "Yellow cards", "Red cards",
          "Touches in penalty area", "Fouled in final third", "Final third entries", "Long balls",
          "Crosses", "Dribbles", "Interceptions", "Recoveries", "Clearances", "Total tackles",
          "Duels", "Accurate passes", "Offsides", "Throw-ins", "Goal kicks", "Shots inside box"]
STATS = ["shots", "sot", "fouls", "fouled", "tackles", "goals", "assists", "xg", "xa", "keypass",
         "dribbles", "touches", "intercepts", "duelwon", "recoveries", "crosses", "passes",
         "dispossessed", "aerialwon", "challengelost", "clearances"]
TARGETS = ["shots", "sot", "fouls", "fouled", "tackles", "goals", "assists"]
TEAMF = ["Ball possession", "Total shots", "Shots on target", "Fouls", "Tackles", "Dribbles", "Crosses",
         "Long balls", "Final third entries", "Touches in penalty area", "Yellow cards", "Expected goals",
         "Corner kicks", "Interceptions", "Passes", "Fouled in final third"]
COVER = {"fouls": "f_Fouls", "fouled": "a_Fouls", "shots": "f_Total shots",
         "sot": "f_Shots on target", "tackles": "f_Total tackles"}
# The site's names for each stat, so the page can look a chance up directly.
SITE_NAME = {"shots": "Shots", "sot": "Shots on target", "fouls": "Fouls", "fouled": "Fouled",
             "tackles": "Tackles", "goals": "Goals", "assists": "Assists"}


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def slots(form, starters):
    """Formation slot per starter: (line, lines, lateral 0-1, line size)."""
    sizes = [int(x) for x in (form or "").split("-") if x.isdigit()]
    outf = [p for p in starters if (p.get("position") or (p.get("player") or {}).get("position")) != "G"]
    out = {}
    if sizes and sum(sizes) == len(outf):
        k = 0
        for li, s in enumerate(sizes):
            for j in range(s):
                out[outf[k]["player"]["id"]] = (li, len(sizes), j / (s - 1) if s > 1 else 0.5, s)
                k += 1
    return out


def player_row(mid, ts, team, opp, home, p, slot, stats):
    pid = p["player"]["id"]
    li, nl, lat, ls = slot.get(pid, (None, None, None, None))
    r = {"match": mid, "ts": ts, "team": team, "opp": opp, "home": home, "pid": pid,
         "name": p["player"]["name"], "pos": p.get("position") or p["player"].get("position"),
         "starter": int(not p.get("substitute")),
         "depth": (li / (nl - 1) if nl and nl > 1 else None) if li is not None else None,
         "lat": lat, "linesize": ls}
    if stats is None:            # upcoming: no numbers yet
        r["mins"] = 90
        for v in PSTATS.values():
            r[v] = np.nan
    else:
        r["mins"] = stats.get("minutesPlayed") or 0
        for k, v in PSTATS.items():
            r[v] = stats.get(k, 0) or 0
    return r


def history():
    """Every finished football match in the cache: matches, teams, players."""
    ev = {}
    for f in glob.glob(str(CACHE / "team_*_events_last_*.json")):
        for e in (load(f) or {}).get("events", []):
            ev[e["id"]] = e
    M, T, P = [], [], []
    for mid, e in ev.items():
        t = e.get("tournament") or {}
        if ((t.get("category") or {}).get("sport") or {}).get("slug") != "football":
            continue
        if (e.get("status") or {}).get("type") != "finished":
            continue
        lu, st = load(CACHE / f"event_{mid}_lineups.json"), load(CACHE / f"event_{mid}_statistics.json")
        if not lu or not st:
            continue
        per = next((p for p in st.get("statistics", []) if p.get("period") == "ALL"), None)
        if not per:
            continue
        items = {}
        for g in per.get("groups", []):
            for it in g.get("statisticsItems", []):
                items.setdefault(it["name"], (num(it.get("homeValue")), num(it.get("awayValue"))))
        ut = t.get("uniqueTournament") or {}
        hs, as_ = (e.get("homeScore") or {}).get("current"), (e.get("awayScore") or {}).get("current")
        M.append({"match": mid, "ts": e["startTimestamp"], "comp_id": ut.get("id"),
                  "home": e["homeTeam"]["id"], "away": e["awayTeam"]["id"], "hg": hs, "ag": as_})
        for side, i in (("home", 0), ("away", 1)):
            team = e[f"{side}Team"]["id"]
            opp = e["awayTeam" if side == "home" else "homeTeam"]["id"]
            row = {"match": mid, "ts": e["startTimestamp"], "team": team, "opp": opp, "home": int(side == "home")}
            for k in TSTATS:
                v = items.get(k)
                row["f_" + k] = v[i] if v else None
                row["a_" + k] = v[1 - i] if v else None
            T.append(row)
            block = lu.get(side) or {}
            players = block.get("players") or []
            sl = slots(block.get("formation"), [p for p in players if not p.get("substitute")])
            for p in players:
                P.append(player_row(mid, e["startTimestamp"], team, opp, int(side == "home"), p, sl,
                                    p.get("statistics") or {}))
    m, t, p = pd.DataFrame(M), pd.DataFrame(T), pd.DataFrame(P)
    sums = p[p.mins > 0].groupby(["match", "team"])[list(COVER)].sum()
    tt = t.set_index(["match", "team"])
    for s, col in COVER.items():
        ref = tt[col].reindex(sums.index)
        got = sums[s]
        covered = np.where(ref.isna(), got > 0, np.where(ref <= 0, True, (got / ref.where(ref > 0)) > 0.5))
        cv = pd.Series(covered, index=sums.index, name="cov_" + s)
        p = p.merge(cv.reset_index(), on=["match", "team"], how="left")
        p["cov_" + s] = p["cov_" + s].fillna(False).astype(bool)
    return m, t, p


def team_ids():
    """Event id -> (home id, away id, tournament id), from anything cached."""
    out = {}
    for pat in ("team_*_events_next_*.json", "team_*_events_last_*.json",
                "unique-tournament_*_events_next_*.json"):
        for f in glob.glob(str(CACHE / pat)):
            for e in (load(f) or {}).get("events", []):
                try:
                    out[e["id"]] = (e["homeTeam"]["id"], e["awayTeam"]["id"],
                                    ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id"))
                except (KeyError, TypeError):
                    pass
    for f in glob.glob(str(CACHE / "event_*.json")):
        if not re.search(r"event_\d+\.json$", f):
            continue
        e = (load(f) or {}).get("event") or {}
        try:
            out[e["id"]] = (e["homeTeam"]["id"], e["awayTeam"]["id"],
                            ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id"))
        except (KeyError, TypeError):
            pass
    return out


def upcoming(days, known_matches, simulate=None):
    """Fixtures in the reports kicking off in the next `days`, with a line-up.

    simulate: a list of finished match ids to treat as upcoming (testing only).
    """
    now = time.time()
    fixtures = {}
    if simulate is None:
        for f in glob.glob(str(ROOT / "reports" / "*.html")):
            if Path(f).name.startswith("pick-"):
                continue
            text = Path(f).read_text(encoding="utf-8")
            m = pagedata.search(text)
            if not m:
                continue
            for entry in json.loads(m.group(1)).get("fixtures", []):
                fx = entry.get("fixture") or {}
                if (fx.get("sport") or "football") != "football":
                    continue
                ko = fx.get("kickoff") or 0
                if now - 3 * 3600 < ko < now + days * 86400:
                    fixtures[fx["id"]] = fx
    else:
        fixtures = {mid: {"id": mid} for mid in simulate}
    ids = team_ids()
    M, T, P, meta = [], [], [], {}
    for eid, fx in fixtures.items():
        if eid in known_matches and simulate is None:
            continue                    # already played and in the history
        lu = load(CACHE / f"event_{eid}_lineups.json")
        if not lu or not (lu.get("home") or {}).get("players"):
            continue
        if eid not in ids:
            continue
        home, away, comp = ids[eid]
        comp = fx.get("tournamentId") or comp
        ko = fx.get("kickoff") or (load(CACHE / f"event_{eid}.json") or {}).get("event", {}).get("startTimestamp")
        if ko is None and simulate is not None:
            ko = simulate[eid]
        M.append({"match": eid, "ts": ko, "comp_id": comp, "home": home, "away": away, "hg": None, "ag": None})
        for side, team, opp in (("home", home, away), ("away", away, home)):
            row = {"match": eid, "ts": ko, "team": team, "opp": opp, "home": int(side == "home")}
            for k in TSTATS:
                row["f_" + k] = np.nan
                row["a_" + k] = np.nan
            T.append(row)
            block = lu.get(side) or {}
            starters = [p for p in block.get("players", []) if not p.get("substitute")]
            sl = slots(block.get("formation"), starters)
            for p in starters:
                P.append(player_row(eid, ko, team, opp, int(side == "home"), p, sl, None))
        meta[eid] = {"confirmed": bool(lu.get("confirmed")), "kickoff": ko,
                     "home": fx.get("home"), "away": fx.get("away")}
    p = pd.DataFrame(P)
    for s in COVER:
        p["cov_" + s] = False
    return pd.DataFrame(M), pd.DataFrame(T), p, meta


def per90(vals, mins):
    m = sum(mins)
    return sum(vals) / m * 90 if m > 0 else np.nan


def profile(hh):
    """A player's record before this match (identical to the backtest)."""
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
        sel = [x for x in full if x.get("cov_" + s, True)]
        if sel:
            w = np.array([0.5 ** ((len(sel) - 1 - i) / 6) for i in range(len(sel))])
            v = np.array([x[s] for x in sel]); m = np.array([x["mins"] for x in sel])
            out[f"{s}_ew"] = (w * v).sum() / (w * m).sum() * 90
        else:
            out[f"{s}_ew"] = np.nan
    for s in TARGETS:
        sel = [x for x in full[-10:] if x.get("cov_" + s, True)]
        for k in (1, 2, 3):
            out[f"{s}_hit{k}_10"] = np.mean([x[s] >= k for x in sel]) if sel else np.nan
    a = out
    def g(k): return 0 if pd.isna(a.get(k)) else a[k]
    out["att_idx"] = g("shots_p90_10") + g("keypass_p90_10") + 3 * g("xg_p90_10")
    out["def_idx"] = g("tackles_p90_10") + g("fouls_p90_10") + g("intercepts_p90_10")
    return out


def features(M, T, P, future):
    """Backtest features (features.py), returning rows for `future` matches only.

    Matches in `future` are scored but never written into any history, so one
    upcoming game cannot feed another.
    """
    M = M.sort_values("ts", kind="stable")
    P = P[P.mins > 0].copy()
    elo = defaultdict(lambda: 1500.0)
    pre_elo = {}
    for r in M.itertuples():
        h, a = elo[r.home], elo[r.away]
        pre_elo[r.match] = (h, a)
        if r.match in future or r.hg is None or r.ag is None or \
                (isinstance(r.hg, float) and math.isnan(r.hg)):
            continue
        exp = 1 / (1 + 10 ** ((a - h - 60) / 400))
        res = 1.0 if r.hg > r.ag else 0.5 if r.hg == r.ag else 0.0
        k = 20 * (1 + abs(r.hg - r.ag)) ** 0.5
        elo[r.home] += k * (res - exp); elo[r.away] -= k * (res - exp)

    T = T.sort_values("ts", kind="stable")
    team_hist = defaultdict(lambda: deque(maxlen=10))
    team_feat = {}
    comp_of = dict(zip(M.match, M.comp_id))
    league_hist = defaultdict(lambda: deque(maxlen=200))
    league_feat = {}
    T_by_match = {mid: g for mid, g in T.groupby("match")}
    concede = defaultdict(lambda: defaultdict(lambda: deque(maxlen=10)))
    team_concede_feat = {}
    Pm = {mid: g for mid, g in P.groupby("match")}
    ts_of = dict(zip(M.match, M.ts))
    pending_league, current_ts = [], None
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
        league_feat[mid] = {"lg_fouls": np.mean(list(lf)) if lf else np.nan}
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
            cf = {}
            for pos in "DMF":
                dq = concede[r.team][pos]
                for s in ("fouls", "fouled", "shots", "tackles", "sot"):
                    v = [x[s] for x in dq if not pd.isna(x.get(s, np.nan))]
                    cf[f"oc_{pos}_{s}"] = np.mean(v) if v else np.nan
            team_concede_feat[(mid, r.team)] = cf
        if mid in future:
            continue
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

    P = P.sort_values(["ts", "match"], kind="stable")
    hist = defaultdict(list)
    h2h = defaultdict(list)
    rows = []
    for mid, pm in P.groupby("match", sort=False):
        is_future = mid in future
        ts = pm.ts.iloc[0]
        if is_future:
            prof = {r.pid: profile(hist[r.pid]) for r in pm.itertuples(index=False)}
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
                f.update(team_feat.get((mid, r.team), {}))
                f.update({"o" + k: v for k, v in team_feat.get((mid, r.opp), {}).items()})
                oc = team_concede_feat.get((mid, r.opp), {})
                for s in ("fouls", "fouled", "shots", "tackles", "sot"):
                    f["oc_" + s] = oc.get(f"oc_{r.pos}_{s}", np.nan) if r.pos in "DMF" else np.nan
                if r.depth is not None and not pd.isna(r.depth):
                    mates = pm[(pm.team == r.team) & (pm.starter == 1) & (pm.pid != r.pid) & (pm.depth == r.depth)]
                    if len(mates):
                        f["mate_att"] = np.nanmean([prof[m]["att_idx"] for m in mates.pid])
                        f["mate_def"] = np.nanmean([prof[m]["def_idx"] for m in mates.pid])
                        f["mate_fouls90"] = np.nanmean([prof[m].get("fouls_p90_10", np.nan) for m in mates.pid])
                        tot = f["mate_def"] * len(mates) + pr["def_idx"]
                        f["def_share_line"] = pr["def_idx"] / tot if tot and not pd.isna(tot) and tot > 0 else np.nan
                        f["att_minus_mates"] = pr["att_idx"] - f["mate_att"]
                    opp = pm[(pm.team == r.opp) & (pm.starter == 1) & pm.depth.notna()]
                    if len(opp):
                        want_d = 1 - r.depth
                        want_l = 1 - (r.lat if r.lat is not None and not pd.isna(r.lat) else 0.5)
                        dist = (opp.depth - want_d).abs() + 0.7 * (opp.lat.fillna(0.5) - want_l).abs()
                        near = opp.loc[dist.nsmallest(2).index]
                        for s in ("fouls", "fouled", "tackles", "dribbles", "shots"):
                            vals = [prof[q].get(f"{s}_p90_10", np.nan) for q in near.pid if q in prof]
                            f["vs_" + s] = np.nanmean(vals) if vals else np.nan
                        f["vs_att"] = np.nanmean([prof[q]["att_idx"] for q in near.pid])
                        f["vs_def"] = np.nanmean([prof[q]["def_idx"] for q in near.pid])
                hh = h2h[(r.pid, r.opp)]
                f["h2h_n"] = len(hh)
                for s in ("fouls", "fouled", "shots", "tackles", "sot"):
                    v = [x for x in hh if x.get("cov_" + s, True)]
                    f["h2h_" + s] = per90([x[s] for x in v], [x["mins"] for x in v]) if v else np.nan
                rows.append(f)
            continue
        for r in pm.itertuples(index=False):
            d = {s: getattr(r, s) for s in STATS}
            d.update({"mins": r.mins, "starter": r.starter, "ts": r.ts, "team": r.team})
            for s in COVER:
                d["cov_" + s] = bool(getattr(r, "cov_" + s))
            hist[r.pid].append(d)
            h2h[(r.pid, r.opp)].append(d)
    return pd.DataFrame(rows)


def score(F):
    meta = json.loads((MODELS / "meta.json").read_text())
    cats = meta["comp_categories"]
    F = F.copy()
    F["pos_c"] = F.pos.map({"G": 0, "D": 1, "M": 2, "F": 3})
    F["comp_c"] = [float(cats.index(int(c))) if c is not None and not pd.isna(c) and int(c) in cats
                   else np.nan for c in F["comp"]]
    out = {}
    for name, m in meta["lines"].items():
        X = F.reindex(columns=m["features"]).astype(float).values
        out[name] = Model(MODELS / f"{name}.json").predict(X)
    return out


def add_cards(events: dict, live=None) -> None:
    """To be booked from the cards model (cards_model.py) for every starter
    already in `events`: lines["Card"]["1"], and each side's expected cards
    under ev["cards"]. Same XI as the rest of the file."""
    import cards_model
    live = live or cards_model.Live(CACHE)
    ids = team_ids()
    for eid, ev in events.items():
        lu = load(CACHE / f"event_{eid}_lineups.json")
        if not lu or int(eid) not in ids:
            continue
        home, away, comp = ids[int(eid)]
        by_pid = {pl["pid"]: pl for pl in ev["players"].values()}
        cards = {}
        for side, team, opp in (("home", home, away), ("away", away, home)):
            xi = [{"pid": (p.get("player") or {}).get("id"), "pos": p.get("position")}
                  for p in (lu.get(side) or {}).get("players", []) if not p.get("substitute")]
            m = live.side_mu(team, opp, side == "home", comp)
            if m:
                cards[side] = round(m["mu"], 3)
            for pid, p in live.player_chances(team, opp, side == "home", comp, xi).items():
                if pid in by_pid:
                    by_pid[pid]["lines"]["Card"] = {"1": round(p, 4)}
        if cards:
            ev["cards"] = cards


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=float, default=7)
    args = ap.parse_args(argv)
    t0 = time.time()
    M, T, P = history()
    UM, UT, UP, meta = upcoming(args.days, set(M.match))
    if UM.empty:
        print("fmodel: no upcoming football fixtures with a line-up in the cache")
        OUT.write_text(json.dumps({"generated": int(time.time()), "events": {}}), encoding="utf-8")
        return
    F = features(pd.concat([M, UM], ignore_index=True), pd.concat([T, UT], ignore_index=True),
                 pd.concat([P, UP], ignore_index=True), set(UM.match))
    probs = score(F) if len(F) else {}
    events = {}
    for i, r in enumerate(F.itertuples(index=False)):
        ev = events.setdefault(str(r.match), {**meta[r.match], "players": {}})
        lines = {}
        for name, p in probs.items():
            s, k = name.rsplit("_", 1)
            lines.setdefault(SITE_NAME[s], {})[k] = round(float(p[i]), 4)
        ev["players"][r.name] = {"pid": int(r.pid), "team": int(r.team), "pos": r.pos, "lines": lines}
    try:
        add_cards(events)
    except Exception as exc:              # never cost the page its other chances
        print(f"fmodel: card chances skipped ({exc})")
    OUT.write_text(json.dumps({"generated": int(time.time()), "model": "fmodel v1 (backtest 2026-10-20)",
                               "events": events}), encoding="utf-8")
    n = sum(len(e["players"]) for e in events.values())
    print(f"fmodel: {n} players in {len(events)} fixtures scored in {time.time() - t0:.0f}s -> {OUT.name}")


if __name__ == "__main__":
    main()
