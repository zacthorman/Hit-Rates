#!/usr/bin/env python3
"""
Walk-forward check of the Paddy Power verdict tiers, chiefly "Acceptable".

    python -B acceptable_check.py fmodel [--cache DIR]   # fmodel over the cache (about 12 minutes)
    python -B acceptable_check.py build [--cache DIR]    # cache -> cache/acceptable_rows.json.gz
    python -B acceptable_check.py report                 # the tables in ACCEPTABLE-CHECK.md

pplog/ (the record of every Paddy Power line the site priced) is not
committed, so "Acceptable" (ours 50%+, the price within 5% of fair) could not
be measured from it. This replays it on the cache instead. Every football
player in every cached match is priced before kick-off the way pplog.snapshot
prices a Paddy Power line, using only what was known before the match:

  * model.appearances over his rows for his team in its last 38 matches, then
    model.price_player on the last ten, as pplog does for every stat but to
    score; to score is pplog._score_chance (scoreCase: 60% xG, 40% goals);
  * the opponent adjustment is pplog._adjustment itself, on an entry rebuilt
    the way run.py builds one: team records from the cache and the projection
    from hitrates.league_ratings and project_fixture, fitted only on matches
    before that day (case_score_backtest.Current does the same for goals);
  * fmodel, where pplog would use it (football starters, to score, shots 1+ to
    3+, shots on target 1+ and 2+), replayed from the cache through
    fmodel_live.features. fmodel was trained on data to the end of June 2026,
    so a line it would have priced before July is dropped, not scored on an
    in-sample number.

The lines are Paddy Power's football menu (pplog.PP_PATTERNS): shots 1+ to
3+, shots on target 1+ and 2+, fouls 1+ and 2+, fouled 1+ to 3+, tackles 1+
and 2+, assists 1+ and to score, all overs. Cards are left out: the estimate
is heuristic, the verdict never calls it acceptable, and the cache has no card
incidents to settle it. Only lines that would have stood are kept: a player
who did not play is void at Paddy Power. A line is settled only where the
match's player statistics cover that stat (the players' total is more than
half the team's), so a match whose feed left a stat out is not read as zeros.

There is no Paddy Power price history in the repo. The verdict at a price is
then a statement about our chance: "acceptable" is a line we make 50% or more
priced within 5% of fair, so what it returns is landed / said, times 0.95 to
1.05, minus one. Lines are therefore reported against their fair price (one
over our chance): landed against said, and the return at the fair price with
the 5% either way the tier allows. Where a committed Betfair snapshot
(market_prices.json, every commit) has a back price for the same player line,
that price is used and the verdict is the page's own (rule_review.pp_verdict).

Every choice of a change is made on matches before CONFIRM_FROM and checked on
the matches from it. The verdict changes only if the change holds there.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
ROWS = CACHE / "acceptable_rows.json.gz"     # gitignored with the rest of cache/
FM_ROWS = CACHE / "acceptable_fmodel.pkl"     # fmodel replayed over the cache (the fmodel command)

FMODEL_FROM = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())    # fmodel out of sample
CONFIRM_FROM = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())   # fit before, confirm after
WINDOW = 38          # update.json "games": the team matches a player's record is taken from
RECENT = 10          # pplog: price_player on the last ten appearances
MIN_APPS = 3         # pplog: fewer recent appearances and the line is not priced
SEED = 20261023
BOOT = 1000

# Paddy Power's football player menu (pplog.PP_PATTERNS and PP_STAT), overs.
MENU = {"Shots": (0.5, 1.5, 2.5), "Shots on target": (0.5, 1.5), "Fouls": (0.5, 1.5),
        "Fouled": (0.5, 1.5, 2.5), "Tackles": (0.5, 1.5), "Assists": (0.5,), "Goals": (0.5,)}
# The team statistic each player stat is covered by: (whose, name). "own" is
# the player's side, "opp" the other side (being fouled is the opponent's foul).
COVER = {"Shots": ("own", "Total shots"), "Shots on target": ("own", "Shots on target"),
         "Fouls": ("own", "Fouls"), "Fouled": ("opp", "Fouls"), "Tackles": ("own", "Tackles")}
# fmodel's columns for the lines it prices (fmodel_live, scorer_audit.score_fast).
FMODEL = {("Goals", 0.5): "fm_goals_1", ("Shots", 0.5): "fm_shots_1", ("Shots", 1.5): "fm_shots_2",
          ("Shots", 2.5): "fm_shots_3", ("Shots on target", 0.5): "fm_sot_1",
          ("Shots on target", 1.5): "fm_sot_2"}
# The team statistics the opponent adjustment borrows (model.FOOTBALL_STAT_TO_TEAM).
TEAM_STATS = ["Total shots", "Shots on target", "Fouls", "Tackles", "Goals"]
FAIR_BANDS = ((1.0, 1.25), (1.25, 1.5), (1.5, 1.75), (1.75, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 1e9))
TIERS = ("acceptable band (ours 50%+)", "long shot (under 50%)")
# Competitions the site builds reports for, so the ones pplog prices
# (case_score_backtest.REPORT_TIDS).
REPORT_TIDS = {17, 18, 8, 23, 35, 34, 242, 325, 7, 679, 10783}


def month(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


def fair_band(p: float) -> str:
    f = 1 / p
    for lo, hi in FAIR_BANDS:
        if lo <= f < hi:
            return f"{lo:.2f}-{hi:.2f}" if hi < 1e8 else f"{lo:.2f}+"
    return "?"


# ===================================================================== build

class Teams:
    """case_score_backtest's History with every team statistic the player
    adjustment needs, so pplog._adjustment reads a real projection."""

    def __init__(self, events, stats):
        import case_score_backtest as cbt
        self.cbt = cbt
        self.stats = stats
        self.by_team = defaultdict(list)
        self.by_tid = defaultdict(list)
        for e in events:
            if e["friendly"]:
                continue
            self.by_team[e["home"]].append(e)
            self.by_team[e["away"]].append(e)
            self.by_tid[e["tid"]].append(e)

    def record(self, e, team):
        home = e["home"] == team
        gf, ga = (e["hc"], e["ac"]) if home else (e["ac"], e["hc"])
        s, o = {"Goals": float(gf)}, {"Goals": float(ga)}
        for name, (h, a) in (self.stats.get(e["id"]) or {}).items():
            s[name], o[name] = (h, a) if home else (a, h)
        return {"id": e["id"], "date": self.cbt._date(e["ts"]), "tournament_id": e["tid"],
                "opponent_id": e["away"] if home else e["home"], "venue": "home" if home else "away",
                "stats": {"ALL": s}, "against": {"ALL": o}}

    def form(self, team, tid, before, limit=WINDOW):
        fin = [e for e in self.by_team.get(team, []) if e["ts"] < before]
        if tid is not None:
            inc = [e for e in fin if e["tid"] == tid]
            if len(inc) >= 5:
                fin = inc
        return [self.record(e, team) for e in fin[-limit:] if e["id"] in self.stats]


class Projector:
    """The entry run.py builds for a fixture: records and, for a league
    match, the opponent-adjusted projection, fitted weekly on earlier
    matches only (run.py refits daily; a week keeps this to minutes)."""

    NAMES = {"ALL": TEAM_STATS}

    def __init__(self, teams: Teams, paged: set):
        self.t = teams
        self.paged = paged
        self.fits = {}

    def _fit(self, tid, week):
        import hitrates
        key = (tid, week)
        if key not in self.fits:
            day = week * 7 * 86400
            ids = sorted({x for e in self.t.by_tid.get(tid, []) if day - 240 * 86400 <= e["ts"] < day
                          for x in (e["home"], e["away"]) if x in self.paged})
            out = None
            if len(ids) >= 4:
                by = {x: r for x in ids if (r := self.t.form(x, tid, day))}
                if len(by) >= 4:
                    out = hitrates.league_ratings(by, self.NAMES)
            self.fits[key] = out
        return self.fits[key]

    def entry(self, e):
        import case_score_backtest as cbt
        import hitrates
        tid = e["tid"]
        cross = tid in cbt.CROSS_LEAGUE or tid in cbt.NO_ADJUST
        recs = [self.t.form(x, None if cross else tid, e["ts"]) for x in (e["home"], e["away"])]
        entry = {"records": recs}
        if not cross:
            fitted = self._fit(tid, int(e["ts"] // (7 * 86400)))
            if fitted and any(str(x) in (fitted.get("attack") or {}) for x in (e["home"], e["away"])):
                proj = hitrates.project_fixture(fitted, e["home"], e["away"], self.NAMES)
                if proj:
                    entry["projection"] = proj
        return entry


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def coverage(ms: dict, sides: list, t: int) -> dict:
    """{stat: whether side t's player statistics cover it}: the players'
    total is more than half the team's (or both are nought). A stat with no
    team figure to check against is taken as not covered."""
    players = {t2: here for _, t2, _, here in sides}
    out = {}
    for stat, (whose, name) in COVER.items():
        idx = t if whose == "own" else 1 - t
        pair = ms.get(name)
        if not pair or pair[idx] is None:
            out[stat] = False
            continue
        team_total = pair[idx]
        got = sum((x["stats"] or {}).get(stat, 0) for x in players.get(t, []) if x["minutes"])
        out[stat] = got > 0.5 * team_total if team_total > 0 else True
    return out


def build(cache: Path, fmodel_pkl: Path | None, out: Path = ROWS, log=print) -> int:
    import case_score_backtest as cbt
    import hitrates
    import model
    import pplog

    events, paged, _ = cbt.load(cache)
    stats = {}
    for e in events:
        ms = hitrates.extract_match_stats(_load_json(cache / f"event_{e['id']}_statistics.json"))
        if ms and ms.get("ALL"):
            stats[e["id"]] = dict(ms["ALL"])
    teams = Teams(events, stats)
    proj = Projector(teams, paged)
    fm = {}
    if fmodel_pkl and Path(fmodel_pkl).exists():
        import pandas as pd
        D = pd.read_pickle(fmodel_pkl)
        cols = sorted(set(FMODEL.values()))
        for r in D[["match", "pid"] + cols].itertuples(index=False):
            fm[(int(r[0]), int(r[1]))] = dict(zip(cols, r[2:]))
    log(f"{len(events)} matches, {len(stats)} with statistics, fmodel rows {len(fm)}")

    mins = model.min_minutes_for("football")
    fill = hitrates.PLAYER_ZERO_FILL
    team_matches = defaultdict(list)          # team -> match ids in date order
    rows_by = defaultdict(list)               # (team, player id) -> his rows for that team
    out_rows = []
    done = 0
    for e in events:
        lu = _load_json(cache / f"event_{e['id']}_lineups.json")
        if not lu or e["friendly"]:
            continue
        sides = []
        for side, t, team in (("home", 0, e["home"]), ("away", 1, e["away"])):
            here = []
            for p in (lu.get(side) or {}).get("players") or []:
                raw = p.get("statistics") or {}
                vals = hitrates._player_stat_values(raw, zero_fill=fill) if raw else {}
                person = p.get("player") or {}
                here.append({"player": person.get("name"), "player_id": person.get("id"),
                             "position": p.get("position"), "started": not p.get("substitute", False),
                             "minutes": vals.get("Minutes", 0), "stats": vals, "match_id": e["id"]})
            sides.append((side, t, team, here))
        if not any(any(r["minutes"] for r in here) for *_, here in sides):
            continue                         # a pre-match copy: nobody has minutes
        ms = stats.get(e["id"]) or {}
        priced = e["id"] in stats
        entry = proj.entry(e) if priced else None
        covered = {t: coverage(ms, sides, t) for _, t, _, _ in sides}
        for side, t, team, here in sides:
            last = set(team_matches[team][-WINDOW:])
            for r in here:
                if not r["minutes"] or not r["player_id"]:
                    continue                 # did not play: void at Paddy Power
                if not priced:
                    continue
                played = [x for x in rows_by[(team, r["player_id"])] if x["match_id"] in last]
                for stat, lines in MENU.items():
                    if not covered[t].get(stat, True):
                        continue             # the feed left this stat out for these players
                    value = (r["stats"] or {}).get(stat)
                    if value is None:
                        continue
                    apps = model.appearances(played, stat, fill, mins)
                    recent = apps[-RECENT:]
                    if len(recent) < MIN_APPS:
                        continue
                    adj = pplog._adjustment(entry, t, stat)
                    for line in lines:
                        if stat == "Goals":
                            site = pplog._score_chance(played, adj, mins)
                        else:
                            site = model.price_player(recent, line, True, adj, None, "football")["p"]
                        if site is None:
                            continue
                        p, source = site, "site"
                        col = FMODEL.get((stat, line))
                        f = fm.get((e["id"], r["player_id"]))
                        if col and r["started"] and f is not None and f.get(col) == f.get(col):
                            if e["ts"] < FMODEL_FROM:
                                continue     # fmodel would have priced it, in its training years
                            p, source = float(f[col]), "fmodel"
                        k10 = sum(1 for a in recent if a["value"] > line)
                        out_rows.append({
                            "event_id": e["id"], "ts": e["ts"], "tid": e["tid"], "comp": e["comp"],
                            "team": team, "player": r["player"], "pid": r["player_id"],
                            "pos": r["position"], "started": r["started"], "sport": "football",
                            "stat": stat, "line": line, "p": round(p, 5), "site": round(site, 5),
                            "source": source, "n10": len(recent), "k10": k10, "adj": round(adj, 3),
                            "value": value, "won": value > line})
        for side, t, team, here in sides:
            team_matches[team].append(e["id"])
            for r in here:
                if r["minutes"] and r["player_id"]:
                    rows_by[(team, r["player_id"])].append(r)
        done += 1
        if done % 500 == 0:
            log(f"  {done} matches, {len(out_rows)} lines")
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(out_rows, fh, separators=(",", ":"))
    log(f"{len(out_rows)} lines from {done} matches -> {out}")
    return len(out_rows)


# ============================================================ prices on file

def snapshot_prices(path: str = "market_prices.json") -> dict:
    """(event id, normalised player, stat, line) -> back price, from every
    committed copy of the Betfair snapshot, first sighting kept. Back-only
    player lists (to score, shots on target 1+ and 2+) are priced like a
    bookmaker's list, which is as close to Paddy Power as the repo holds."""
    import pplog
    kinds = {"TO_SCORE": ("Goals", 0.5), "SHOTS_ON_TARGET_P1": ("Shots on target", 0.5),
             "SHOTS_ON_TARGET_P2": ("Shots on target", 1.5)}
    try:
        shas = subprocess.run(["git", "log", "--reverse", "--format=%H", "--", path], cwd=HERE,
                              capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        shas = []
    out = {}
    for sha in shas:
        try:
            d = json.loads(subprocess.run(["git", "show", f"{sha}:{path}"], cwd=HERE, capture_output=True,
                                          text=True, check=True).stdout)
        except (OSError, ValueError, subprocess.CalledProcessError):
            continue
        for eid, ev in (d.get("events") or {}).items():
            for m in ev.get("markets") or []:
                k = kinds.get(m.get("type"))
                if not k:
                    continue
                for r in m.get("runners") or []:
                    if r.get("back") and r["back"] > 1.01:
                        out.setdefault((int(eid), pplog._norm(r.get("name") or ""), *k), r["back"])
    return out


# ================================================================== scoring

def load_rows(path: Path = ROWS):
    """The replayed lines as a DataFrame."""
    import pandas as pd
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        D = pd.DataFrame(json.load(fh))
    D["won"] = D["won"].astype(bool)
    # A chance under 1% is a fair price over 100: not a line anyone offers.
    D = D[D["p"] >= 0.01].reset_index(drop=True)
    D["report"] = D["tid"].isin(REPORT_TIDS)
    D["period"] = ["fit" if t < CONFIRM_FROM else "confirm" for t in D["ts"]]
    D["month"] = [month(t) for t in D["ts"]]
    D["band"] = [fair_band(p) for p in D["p"]]
    D["tier"] = [TIERS[0] if p >= 0.5 else TIERS[1] for p in D["p"]]
    return D


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def _per_match(D):
    """Per match: lines, wins, sum of chances, and the fair-price return
    sum (won / p): every statistic below is a ratio of these sums, so a
    bootstrap over matches only has to resample four columns."""
    g = D.assign(w=D["won"].astype(float), r=D["won"].astype(float) / D["p"]) \
         .groupby("event_id")[["w", "p", "r"]].agg(["sum", "count"])
    return (g[("w", "count")].to_numpy(float), g[("w", "sum")].to_numpy(float),
            g[("p", "sum")].to_numpy(float), g[("r", "sum")].to_numpy(float))


def summary(D, intervals=True, n_boot=BOOT, seed=SEED) -> dict:
    """Landed against said and the return at the fair price, with 95%
    intervals resampling whole matches."""
    import numpy as np
    out = {"n": int(len(D)), "matches": int(D["event_id"].nunique()) if len(D) else 0}
    if not len(D):
        return out
    n, w, p, r = _per_match(D)
    N = n.sum()
    out["said"], out["landed"] = p.sum() / N, w.sum() / N
    out["gap"] = out["landed"] - out["said"]
    out["roi"] = r.sum() / N - 1
    out["roi_lo5"], out["roi_hi5"] = 0.95 * r.sum() / N - 1, 1.05 * r.sum() / N - 1
    if intervals and len(n) >= 2:
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(n), size=(n_boot, len(n)))
        Nb = n[idx].sum(1)
        gaps = (w[idx].sum(1) - p[idx].sum(1)) / Nb
        rois = r[idx].sum(1) / Nb - 1
        out["gap_lo"], out["gap_hi"] = np.percentile(gaps, [2.5, 97.5])
        out["roi_ci_lo"], out["roi_ci_hi"] = np.percentile(rois, [2.5, 97.5])
    return out


# ------------------------------------------------------- candidate changes

def calib_fit(D):
    """Platt map of our chance on these lines: P(win) = sig(a + b logit p)."""
    import numpy as np
    x = np.log(np.clip(D["p"].to_numpy(), 1e-4, 1 - 1e-4) / (1 - np.clip(D["p"].to_numpy(), 1e-4, 1 - 1e-4)))
    y = D["won"].to_numpy(float)
    a, b = 0.0, 1.0
    for _ in range(50):
        q = 1 / (1 + np.exp(-(a + b * x)))
        g = np.array([(y - q).sum(), ((y - q) * x).sum()])
        wq = q * (1 - q)
        H = np.array([[wq.sum(), (wq * x).sum()], [(wq * x).sum(), (wq * x * x).sum()]])
        H += np.eye(2) * 1e-6 * len(x)        # a whisker of ridge: one distinct chance is still solvable
        step = np.linalg.solve(H, g)
        a, b = a + step[0], b + step[1]
        if abs(step).sum() < 1e-9:
            break
    return float(a), float(b)


def calib_apply(p, ab):
    import numpy as np
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return 1 / (1 + np.exp(-(ab[0] + ab[1] * np.log(p / (1 - p)))))


def candidates(fit):
    """Ways to tighten acceptable, each fitted on the fit months only. Each
    is a mask: which lines would still be called acceptable at a fair price."""
    acc = fit[fit["p"] >= 0.5]
    out = [("As now: ours 50%+", lambda D: D["p"] >= 0.5)]
    # A higher floor on our chance: the lowest that left the fit months'
    # acceptable lines landing at least as often as said.
    floor = None
    for t in (0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
        s = acc[acc["p"] >= t]
        if len(s) >= 1000 and s["won"].mean() >= s["p"].mean():
            floor = t
            break
    if floor:
        out.append((f"Ours {floor:.0%}+ (floor fitted)", lambda D, t=floor: D["p"] >= t))
    # Per stat and line: drop those the fit months say ran high, the whole
    # interval for landed minus said below zero.
    bad = []
    for k, s in acc.groupby(["stat", "line"]):
        if len(s) >= 500:
            m = summary(s, n_boot=300)
            if m.get("gap_hi") is not None and m["gap_hi"] < 0:
                bad.append(k)
    if bad:
        keys = set(bad)
        out.append((f"Without the {len(bad)} stat-line(s) that ran high (fitted)",
                    lambda D, b=keys: (D["p"] >= 0.5) & ~D.apply(lambda r: (r["stat"], r["line"]) in b, axis=1)))
    # Our chance through one Platt map before the 50% test.
    ab = calib_fit(fit)
    out.append((f"Recalibrated chance 50%+ (Platt a {ab[0]:+.2f}, b {ab[1]:.2f}, fitted)",
                lambda D, ab=ab: calib_apply(D["p"], ab) >= 0.5))
    return out, {"floor": floor, "bad": bad, "platt": ab}


def held_out(D):
    """Choose a tightening on the fit months, confirm it on the later ones.

    The candidate with the best return at the fair price on the fit months
    is the one tried. It is adopted only if, on the confirm months, the lines
    it takes out of acceptable still ran high (the 95% interval for landed
    minus said wholly below zero) and the lines it keeps returned at least as
    much as acceptable as it stands. Nothing about the confirm months enters
    the choice."""
    fit, conf = D[D["period"] == "fit"], D[D["period"] == "confirm"]
    cands, fitted = candidates(fit)
    now_fit, now_conf = cands[0][1](fit), cands[0][1](conf)
    rows = []
    for name, keep in cands:
        kf, kc = keep(fit), keep(conf)
        rows.append({"rule": name, "fit": summary(fit[kf]), "confirm": summary(conf[kc]),
                     "removed_fit": summary(fit[now_fit & ~kf]), "removed_confirm": summary(conf[now_conf & ~kc])})
    tried = max(rows[1:], key=lambda x: x["fit"].get("roi", -1)) if len(rows) > 1 else None
    adopt = None
    if tried:
        rc, kc, nc = tried["removed_confirm"], tried["confirm"], rows[0]["confirm"]
        if rc.get("gap_hi") is not None and rc["gap_hi"] < 0 and kc.get("roi", -1) >= nc.get("roi", 0):
            adopt = tried["rule"]
    return {"table": rows, "fitted": fitted, "tried": tried["rule"] if tried else None, "adopt": adopt}


def priced(D, prices):
    """Lines with a committed Betfair back price, with the page's verdict."""
    import pplog
    import rule_review as R
    out = []
    for r in D.itertuples(index=False):
        b = prices.get((int(r.event_id), pplog._norm(r.player or ""), r.stat, float(r.line)))
        if b:
            out.append({"event_id": r.event_id, "p": r.p, "won": bool(r.won), "price": b,
                        "verdict": R.pp_verdict(r.p, b, r.n10)})
    return out


# ================================================================ printing

def pct(x, sign=False, nd=1):
    if x is None:
        return "-"
    return f"{x * 100:+.{nd}f}%" if sign else f"{x * 100:.{nd}f}%"


def iv(lo, hi, sign=True, nd=1):
    return "-" if lo is None else f"{pct(lo, sign, nd)} to {pct(hi, sign, nd)}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] + ["---:"] * (len(head) - 1)) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


HEAD = ["Lines", "Matches", "Said", "Landed", "Landed minus said", "95%", "Return at fair", "95%",
        "At fair -5% / +5%"]


def cells(s):
    if not s.get("n"):
        return [0, 0] + ["-"] * 7
    return [f"{s['n']:,}", f"{s['matches']:,}", pct(s["said"]), pct(s["landed"]), pct(s["gap"], True),
            iv(s.get("gap_lo"), s.get("gap_hi")), pct(s["roi"], True), iv(s.get("roi_ci_lo"), s.get("roi_ci_hi")),
            f"{pct(s['roi_lo5'], True)} / {pct(s['roi_hi5'], True)}"]


def report(D, prices=None) -> tuple[str, dict]:
    out = []
    p = out.append
    R = D[D["report"]]
    S = R[R["started"]]                       # starters: the main case
    p(f"{len(D):,} replayed lines from {D['event_id'].nunique():,} matches, "
      f"{datetime.fromtimestamp(D['ts'].min(), timezone.utc):%d %b %Y} to "
      f"{datetime.fromtimestamp(D['ts'].max(), timezone.utc):%d %b %Y}. "
      f"{len(R):,} lines from {R['event_id'].nunique():,} matches are in the competitions the site reports on, "
      f"{len(S):,} of them for starters; the tables use those unless they say otherwise. "
      f"Fit: matches before {datetime.fromtimestamp(CONFIRM_FROM, timezone.utc):%d %b %Y}; "
      f"confirm: from that date.\n")

    p("### A. Each tier, starters and substitutes who came on\n")
    rows = []
    for name, X in (("Report competitions", R), ("Every competition", D)):
        for who, st in (("started", True), ("came on", False)):
            for t in TIERS:
                for per in ("fit", "confirm"):
                    rows.append([name, who, t, per] + cells(summary(
                        X[(X["started"] == st) & (X["tier"] == t) & (X["period"] == per)])))
    p(table(["Competitions", "Player", "Tier", "Period"] + HEAD, rows))

    acc = S[S["p"] >= 0.5]
    p("\n### B. The acceptable band by stat and line (starters)\n")
    keys = acc.groupby(["stat", "line"]).size().sort_values(ascending=False).index
    rows = []
    for st, ln in keys:
        for per in ("fit", "confirm"):
            x = acc[(acc["stat"] == st) & (acc["line"] == ln) & (acc["period"] == per)]
            rows.append([st, f"{ln + 0.5:.0f}+", per] + cells(summary(x)))
    p(table(["Stat", "Line", "Period"] + HEAD, rows))

    p("\n### C. Every starter line by fair price (one over our chance)\n")
    order = [fair_band(2 / (lo + min(hi, 9))) for lo, hi in FAIR_BANDS]
    p(table(["Fair price", "Period"] + HEAD,
            [[b, per] + cells(summary(S[(S["band"] == b) & (S["period"] == per)]))
             for b in order for per in ("fit", "confirm")]))

    p("\n### D. The acceptable band by where the chance came from\n")
    rows = []
    for src in ("fmodel", "site"):
        for st in (True, False):
            for per in ("fit", "confirm"):
                x = R[(R["p"] >= 0.5) & (R["source"] == src) & (R["started"] == st) & (R["period"] == per)]
                if len(x):
                    rows.append([src, "started" if st else "came on", per] + cells(summary(x)))
    p(table(["Chance from", "Player", "Period"] + HEAD, rows))

    p("\n### E. The acceptable band by month (starters)\n")
    p(table(["Month"] + HEAD, [[m] + cells(summary(acc[acc["month"] == m]))
                               for m in sorted(acc["month"].unique())]))

    h = held_out(S)
    p("\n### F. Tightening acceptable (starters): fitted before the confirm months, checked on them\n")
    p(table(["Rule", "Lines", "Period"] + HEAD,
            [[x["rule"], what, per] + cells(x[key + per if key else per]) for x in h["table"]
             for what, key in (("kept", ""), ("taken out", "removed_")) if x["rule"] != h["table"][0]["rule"] or not key
             for per in ("fit", "confirm")]))
    p(f"\nTried (best return on the fit months): {h['tried']}.")
    if h["fitted"]["bad"]:
        p("\nStat-lines dropped by the per-stat rule: " +
          ", ".join(f"{s} {l + 0.5:.0f}+" for s, l in h["fitted"]["bad"]) + ".")
    p(f"\nAdopted: {h['adopt'] or 'nothing; the verdict is unchanged'}.")

    if prices is not None:
        p("\n### G. Lines with a committed Betfair back price (every competition)\n")
        rows = []
        for who, st in (("started", True), ("came on", False)):
            pr = priced(D[D["started"] == st], prices)
            for v in ("ok", "long", "avoid"):
                x = [r for r in pr if r["verdict"] == v]
                if not x:
                    continue
                k = sum(r["won"] for r in x)
                ret = sum((r["price"] - 1) if r["won"] else -1 for r in x)
                lo, hi = wilson(k, len(x))
                rows.append([who, {"ok": "acceptable", "long": "long shot", "avoid": "avoid"}[v], len(x), k,
                             pct(sum(r["p"] for r in x) / len(x)), pct(k / len(x)), iv(lo, hi, False),
                             f"{ret:+.2f}u", pct(ret / len(x), True)])
        p(table(["Player", "Verdict", "Lines", "Won", "Said", "Landed", "95%", "Profit", "ROI"], rows)
          if rows else "No replayed line has a committed price.")
    return "\n".join(out), h


def fmodel_replay(cache: Path, out: Path = FM_ROWS, log=print) -> int:
    """fmodel's chance for every starter in the cache, as scorer_audit.build
    works it out: (match, pid, fm_* columns) to a pickle."""
    import fmodel_live as FL
    import scorer_audit as SA
    FL.CACHE = Path(cache)
    M, T, P = FL.history()
    log(f"history: {len(M)} matches, {len(P)} player rows")
    F = FL.features(M, T, P, set(), emit=set(M.match))
    probs = SA.score_fast(F)
    D = F[["match", "ts", "pid", "name", "team"]].copy()
    for k in ("goals_1", "shots_1", "shots_2", "shots_3", "sot_1", "sot_2"):
        D["fm_" + k] = probs[k]
    D.to_pickle(out)
    log(f"{len(D)} starter rows -> {out}")
    return len(D)


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("cmd", choices=("fmodel", "build", "report"))
    a.add_argument("--cache", default=str(CACHE))
    a.add_argument("--fmodel", default=str(FM_ROWS), help="fmodel replay pickle (the fmodel command writes it)")
    a.add_argument("--rows", default=str(ROWS))
    args = a.parse_args(argv)
    if args.cmd == "fmodel":
        fmodel_replay(Path(args.cache), Path(args.fmodel))
    elif args.cmd == "build":
        fm = Path(args.fmodel)
        if not fm.exists():
            print(f"no fmodel replay at {fm}: run the fmodel command first, or every line is priced without it")
        build(Path(args.cache), fm if fm.exists() else None, Path(args.rows))
    else:
        text, _ = report(load_rows(Path(args.rows)), snapshot_prices())
        print(text)


if __name__ == "__main__":
    main()
