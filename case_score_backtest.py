"""
Walk-forward test of The case's predicted score and home, draw and away chances.

    python case_score_backtest.py              # run, print the tables, write case_score_results.json
    python case_score_backtest.py --quick      # two windows, a smaller tuning grid
    python case_score_backtest.py --snapshots DIR   # add Betfair rows from old market_prices.json files
    python case_score_backtest.py --report     # the tables again from the saved results

Why this exists. context.score() has printed a scoreline and 1X2 chances on
every fixture since The case went in, and none of it had been checked. This
replays it over the cache and puts four alternatives (scoremodels.py) next to
it on the same matches, with the same rules. Since this test, context.score()
uses the winner and keeps the old route as legacy_score() for unseen sides.

  * WALK-FORWARD. Test matches are the last 40% of eligible dates, cut into
    four windows by count. Every prediction uses only matches played before
    the UTC day of kick-off; the team-rating models, refitted weekly, only
    matches before the start of that week.
  * TUNING ON TRAINING ONLY. Each window's hyperparameters (half-life, ridge)
    are chosen on the 60 days before the window opens, fitted on everything
    before those 60 days. Nothing from the window, or after it, is seen.
  * THE CURRENT METHOD IS RUN, NOT RE-WRITTEN. context.legacy_score(), the
    whole of context.score() before this test, is called on an entry built
    the way run.py builds one: the goals projection
    from hitrates.league_ratings and project_fixture where run.py would have
    one (league competitions, --adjust, last 38 in the competition), and
    otherwise the entry's records, so context falls back to recent xG and
    the Elo re-split exactly as on the page.

Eligible: a competitive match (no friendlies) with a full-time score, where
both clubs have their own match pages in the cache, which is what a report
fixture has. Scored on the 90-minute result, which is what a 1X2 settles on.

One known leak, stated rather than hidden: strength.py's Elo constants (K,
home edge) were tuned once on the whole cache. The ratings themselves are as
of kick-off, but the constants saw the test period. It touches the current
method's fallback and the Elo-Poisson model, not the team-rating models.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import context
import hitrates
import scoremodels as sm
import strength

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT = HERE / "case_score_results.json"
DAY = 86400

# Competitions The case is actually built for (update.json, plus the
# European and Nations League steps in update.py).
REPORT_TIDS = {17, 18, 8, 23, 35, 34, 242, 325, 7, 679, 10783}
CROSS_LEAGUE = {7, 679, 10783}          # run.py CROSS_LEAGUE_COMPETITIONS
NO_ADJUST = {10783}                     # the Nations League step runs without --adjust
GAMES = 38                              # update.json "games"
NATIONS_GAMES, NATIONS_DAYS = 20, 400   # update.py's Nations League step

TEST_SHARE = 0.4
N_WINDOWS = 4
VALID_DAYS = 60
GRID_HALF_LIFE = (90, 180, 365, 730, 1460)
GRID_RIDGE = (0.1, 0.5, 2.0, 8.0)


def _day(ts: float) -> int:
    return int(ts // DAY) * DAY


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ loading

def load(cache: Path = CACHE):
    """Every finished men's match once, the clubs with pages, and per-match stats."""
    events: dict[int, dict] = {}
    paged: set[int] = set()
    for path in glob.glob(str(cache / "team_*_events_last_*.json")):
        paged.add(int(Path(path).name.split("_")[1]))
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in data.get("events") or []:
            if (e.get("status") or {}).get("type") != "finished":
                continue
            home, away = e.get("homeTeam") or {}, e.get("awayTeam") or {}
            if (home.get("sport") or {}).get("slug") != "football":
                continue
            if home.get("gender") == "F" or away.get("gender") == "F":
                continue
            hs, as_ = e.get("homeScore") or {}, e.get("awayScore") or {}
            if hs.get("current") is None or as_.get("current") is None or not e.get("startTimestamp"):
                continue
            ut = (e.get("tournament") or {}).get("uniqueTournament") or {}
            events[e["id"]] = {
                "id": e["id"], "ts": e["startTimestamp"], "home": home.get("id"), "away": away.get("id"),
                "home_name": home.get("name"), "away_name": away.get("name"),
                "hg": int(hs.get("normaltime", hs["current"])), "ag": int(as_.get("normaltime", as_["current"])),
                "hc": int(hs["current"]), "ac": int(as_["current"]),
                "tid": ut.get("id"), "comp": ut.get("name") or (e.get("tournament") or {}).get("name"),
                "friendly": hitrates._is_friendly(e),
            }
    stats: dict[int, dict] = {}
    for eid in events:
        path = cache / f"event_{eid}_statistics.json"
        if not path.exists():
            continue
        try:
            ms = hitrates.extract_match_stats(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if not ms:
            continue
        xg = (ms.get("ALL") or {}).get("Expected goals")
        stats[eid] = {"xg": tuple(xg) if xg else None}
    return sorted(events.values(), key=lambda e: (e["ts"], e["id"])), paged, stats


class History:
    """Each club's competitive matches, and records shaped like team_form's."""

    def __init__(self, events, stats):
        self.stats = stats
        self.by_team: dict[int, list[dict]] = defaultdict(list)
        self.by_tid: dict = defaultdict(list)
        for e in events:
            if e["friendly"]:
                continue
            self.by_team[e["home"]].append(e)
            self.by_team[e["away"]].append(e)
            self.by_tid[e["tid"]].append(e)

    def record(self, e, team):
        home = e["home"] == team
        gf, ga = (e["hc"], e["ac"]) if home else (e["ac"], e["hc"])
        s = {"Goals": float(gf)}
        o = {"Goals": float(ga)}
        xg = self.stats[e["id"]]["xg"]
        if xg:
            s["Expected goals"], o["Expected goals"] = (xg[0], xg[1]) if home else (xg[1], xg[0])
        return {"id": e["id"], "date": _date(e["ts"]), "competition": e["comp"],
                "tournament_id": e["tid"], "opponent": e["away_name"] if home else e["home_name"],
                "opponent_id": e["away"] if home else e["home"], "venue": "home" if home else "away",
                "goals_for": gf, "goals_against": ga,
                "result": "W" if gf > ga else "L" if gf < ga else "D",
                "stats": {"ALL": s}, "against": {"ALL": o}}

    def form(self, team, tid, before, limit=GAMES, max_age_days=None):
        """hitrates.collect_events then team_form, from the cache."""
        fin = [e for e in self.by_team.get(team, []) if e["ts"] < before]
        if max_age_days is not None:
            fin = [e for e in fin if e["ts"] >= before - max_age_days * DAY]
        if tid is not None:
            inc = [e for e in fin if e["tid"] == tid]
            if len(inc) >= 5:
                fin = inc
        return [self.record(e, team) for e in fin[-limit:] if e["id"] in self.stats]


# ------------------------------------------------------- the current method

class Current:
    """context.legacy_score() on an entry built the way run.py builds one."""

    NAMES = {"ALL": ["Goals"]}

    def __init__(self, hist: History, paged: set[int]):
        self.hist = hist
        self.paged = paged
        self.fits: dict = {}
        self.source = Counter()

    def _fit(self, tid, day):
        key = (tid, day)
        if key in self.fits:
            return self.fits[key]
        # api.tournament_team_ids: the clubs in this season's table. Taken as
        # the paged clubs that played in the competition in the last 240 days.
        ids = sorted({t for e in self.hist.by_tid.get(tid, []) if day - 240 * DAY <= e["ts"] < day
                      for t in (e["home"], e["away"]) if t in self.paged})
        out = None
        if len(ids) >= 4:
            by_team = {}
            for t in ids:
                recs = self.hist.form(t, tid, day)
                if recs:
                    by_team[t] = recs
            if len(by_team) >= 4:
                out = hitrates.league_ratings(by_team, self.NAMES)
        self.fits[key] = out
        return out

    @staticmethod
    def _in_pool(ratings, *ids):
        return any(str(t) in (ratings.get("attack") or {}) for t in ids)

    def predict(self, e):
        day = _day(e["ts"])
        tid = e["tid"]
        nations = tid in NO_ADJUST
        cross = tid in CROSS_LEAGUE
        limit, age = (NATIONS_GAMES, NATIONS_DAYS) if nations else (GAMES, None)
        recs = [self.hist.form(t, None if cross else tid, day, limit, age) for t in (e["home"], e["away"])]
        if not any(recs):
            return None
        entry = {"fixture": {"kickoff": e["ts"], "tournamentId": tid},
                 "teams": [{"id": e["home"], "name": e["home_name"], "side": "home"},
                           {"id": e["away"], "name": e["away_name"], "side": "away"}],
                 "records": recs}
        if not cross and not nations:
            fitted = self._fit(tid, day)
            if fitted and not self._in_pool(fitted, e["home"], e["away"]):
                counts = Counter(r["tournament_id"] for rs in recs for r in rs
                                 if isinstance(r.get("tournament_id"), int))
                own = max(counts, key=counts.get) if counts else None
                if own is not None and own != tid:
                    refit = self._fit(own, day)
                    if refit and self._in_pool(refit, e["home"], e["away"]):
                        fitted = refit
            if fitted:
                proj = hitrates.project_fixture(fitted, e["home"], e["away"], self.NAMES)
                if proj:
                    entry["projection"] = proj
        hrecs = context.records(entry, 0, e["ts"])
        arecs = context.records(entry, 1, e["ts"])
        sc = context.legacy_score(entry, hrecs, arecs)
        if not sc:
            return None
        self.source[sc["source"]] += 1
        tot = sc["ph"] + sc["pd"] + sc["pa"]
        return {"p": (sc["ph"] / tot, sc["pd"] / tot, sc["pa"] / tot),
                "score": (sc["home"], sc["away"]), "source": sc["source"],
                "grid": sm.poisson_grid(sc["lh"], sc["la"])}


# ------------------------------------------------------------- alternatives

def comp_level(hist: History, tid, day, overall: float, k: float = 20.0) -> float:
    """log goals per side in this competition over the previous year, shrunk."""
    rows = [e for e in hist.by_tid.get(tid, []) if day - 365 * DAY <= e["ts"] < day]
    goals = sum(e["hg"] + e["ag"] for e in rows)
    return math.log((goals + k * overall) / (2 * len(rows) + k))


def overall_level(matches, day) -> float:
    rows = [m for m in matches if day - 365 * DAY <= m["ts"] < day]
    return sum(m["hg"] + m["ag"] for m in rows) / max(1, 2 * len(rows))


def elo_gap(r: strength.Ratings, home, away, ts):
    rh, ra = r.rating_at(home, ts), r.rating_at(away, ts)
    if rh is None or ra is None:
        return None
    return (rh + r.params["home_adv"] - ra) / 400.0


def score_rows(preds, outcomes):
    """Mean RPS, Brier, log loss and outcome accuracy over parallel lists."""
    n = len(preds)
    if not n:
        return None
    return {"n": n,
            "rps": sum(sm.rps(p, o) for p, o in zip(preds, outcomes)) / n,
            "brier": sum(sm.brier(p, o) for p, o in zip(preds, outcomes)) / n,
            "logloss": sum(sm.log_loss(p, o) for p, o in zip(preds, outcomes)) / n,
            "acc": sum(1 for p, o in zip(preds, outcomes) if int(np.argmax(p)) == o) / n}


def tune(kind, matches, valid, start):
    """Pick half-life and ridge on the VALID_DAYS before `start`."""
    fit_at = start - VALID_DAYS * DAY
    best = None
    table = []
    for hl in GRID_HALF_LIFE:
        for rg in GRID_RIDGE:
            m = sm.TeamGoals(kind, hl, rg).fit(matches, fit_at)
            ps, os_ = [], []
            for e in valid:
                ps.append(sm.outcome_probs(m.grid(e["home"], e["away"])))
                os_.append(sm.outcome_index(e["hg"], e["ag"]))
            s = score_rows(ps, os_)
            table.append((hl, rg, s["logloss"], s["rps"]))
            if best is None or s["logloss"] < best[2]:
                best = (hl, rg, s["logloss"])
    return best[0], best[1], table


# ------------------------------------------------------------- bookmaker

def bookmaker(snap_dir: Path | None):
    """Betfair match odds per event, the last snapshot before kick-off."""
    out: dict[int, dict] = {}
    if snap_dir is None or not snap_dir.exists():
        return out
    for path in sorted(snap_dir.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fetched = d.get("fetched")
        for eid, ev in (d.get("events") or {}).items():
            if ev.get("sport") not in (None, "football"):
                continue
            mo = next((m for m in ev.get("markets") or [] if m.get("type") == "MATCH_ODDS"), None)
            if not mo or len(mo.get("runners") or []) != 3:
                continue
            ps = [r.get("p") for r in mo["runners"]]
            if any(p is None for p in ps):
                continue
            h, a, d_ = ps
            if ev.get("swapped"):
                h, a = a, h
            tot = h + d_ + a
            try:
                start = datetime.strptime(ev["start"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
                    tzinfo=timezone.utc).timestamp()
            except (KeyError, ValueError):
                start = None
            if start is not None and fetched is not None and fetched >= start:
                continue
            cs = None
            csm = next((m for m in ev.get("markets") or [] if m.get("type") == "CORRECT_SCORE"), None)
            if csm:
                cs = {}
                for r in csm.get("runners") or []:
                    try:
                        x, y = (int(v) for v in r["name"].replace(" ", "").split("-"))
                    except (KeyError, ValueError):
                        continue
                    if r.get("p") is not None:
                        cs[(y, x) if ev.get("swapped") else (x, y)] = r["p"]
            prev = out.get(int(eid))
            if prev is None or (fetched or 0) > prev["fetched"]:
                out[int(eid)] = {"p": (h / tot, d_ / tot, a / tot), "cs": cs, "fetched": fetched or 0}
    return out


# ------------------------------------------------------------------- main

def run(quick=False, snap_dir: Path | None = None, log=print):
    t0 = time.time()
    events, paged, stats = load()
    hist = History(events, stats)
    competitive = [e for e in events if not e["friendly"] and e["home"] and e["away"]]
    # The same results the live model is fitted on (context.score_matches).
    matches = context.score_matches()
    eligible = [e for e in competitive if e["home"] in paged and e["away"] in paged]
    log(f"{len(events)} matches loaded, {len(competitive)} competitive, {len(eligible)} eligible, "
        f"{len(stats)} with statistics ({time.time() - t0:.0f}s)")

    elo = strength.ratings()
    cur = Current(hist, paged)
    book = bookmaker(snap_dir)

    n_test = int(len(eligible) * TEST_SHARE)
    test = eligible[-n_test:]
    n_win = 2 if quick else N_WINDOWS
    size = math.ceil(len(test) / n_win)
    windows = [test[i:i + size] for i in range(0, len(test), size)]
    grid_hl, grid_rg = (GRID_HALF_LIFE, GRID_RIDGE)
    if quick:
        globals()["GRID_HALF_LIFE"], globals()["GRID_RIDGE"] = (180, 365), (2.0,)

    rows = []           # one per test match, every method's forecast
    tuning = []
    for w, win in enumerate(windows):
        start = _day(win[0]["ts"])
        end = win[-1]["ts"]
        valid = [e for e in eligible if start - VALID_DAYS * DAY <= e["ts"] < start]
        chosen = {}
        for kind in ("poisson", "dc", "bivariate"):
            hl, rg, table = tune(kind, matches, valid, start)
            chosen[kind] = (hl, rg)
            at_start = sm.TeamGoals(kind, hl, rg).fit(matches, start)
            tuning.append({"window": w + 1, "kind": kind, "half_life": hl, "ridge": rg,
                           "grid": table, "valid_n": len(valid), "rho": at_start.rho, "l3": at_start.l3,
                           "home": at_start.home, "teams": len(at_start.index)})
            log(f"  window {w + 1} {kind}: half-life {hl}, ridge {rg}")

        # Elo-Poisson: fitted on the two years before the window.
        train = [e for e in competitive if start - 730 * DAY <= e["ts"] < start]
        ov = overall_level(matches, start)
        gl = []
        for e in train:
            g = elo_gap(elo, e["home"], e["away"], e["ts"])
            if g is not None:
                gl.append((g, comp_level(hist, e["tid"], _day(e["ts"]), ov), e["hg"], e["ag"]))
        eg = sm.EloGoals().fit(*map(np.array, zip(*gl)))

        # Base rates: the year before the window, eligible matches.
        base = [e for e in eligible if start - 365 * DAY <= e["ts"] < start]
        oc = Counter(sm.outcome_index(e["hg"], e["ag"]) for e in base)
        base_p = tuple(oc[k] / len(base) for k in range(3))
        base_score = Counter((e["hg"], e["ag"]) for e in base).most_common(1)[0][0]

        # Weekly refits through the window.
        models = {}
        week = None
        for e in win:
            wk = start + ((_day(e["ts"]) - start) // (7 * DAY)) * 7 * DAY
            if wk != week:
                week = wk
                for kind, (hl, rg) in chosen.items():
                    models[kind] = sm.TeamGoals(kind, hl, rg).fit(matches, wk)
                models["shipped"] = sm.TeamGoals(context.SCORE_KIND, context.SCORE_HALF_LIFE,
                                                 context.SCORE_RIDGE).fit(matches, wk)
            o = sm.outcome_index(e["hg"], e["ag"])
            row = {"id": e["id"], "window": w + 1, "ts": e["ts"], "tid": e["tid"],
                   "report": e["tid"] in REPORT_TIDS, "hg": e["hg"], "ag": e["ag"], "o": o, "f": {}}
            c = cur.predict(e)
            if c:
                row["f"]["current"] = {"p": c["p"], "score": c["score"],
                                       "modal": sm.modal_score(c["grid"]), "source": c["source"],
                                       "pscore": float(c["grid"][min(e["hg"], 10), min(e["ag"], 10)]
                                                       / c["grid"].sum())}
            for kind, m in models.items():
                if not (m.knows(e["home"]) and m.knows(e["away"])):
                    continue
                g = m.grid(e["home"], e["away"])
                row["f"][kind] = {"p": sm.outcome_probs(g), "score": sm.pick_score(g)[:2],
                                  "modal": sm.modal_score(g),
                                  "pscore": float(g[min(e["hg"], 10), min(e["ag"], 10)] / g.sum())}
            gap = elo_gap(elo, e["home"], e["away"], e["ts"])
            if gap is not None:
                g = eg.grid(gap, comp_level(hist, e["tid"], _day(e["ts"]), ov))
                row["f"]["elo"] = {"p": sm.outcome_probs(g), "score": sm.pick_score(g)[:2],
                                   "modal": sm.modal_score(g),
                                   "pscore": float(g[min(e["hg"], 10), min(e["ag"], 10)] / g.sum())}
                wdl = elo.win_draw_loss(e["home"], e["away"], e["ts"])
                if wdl:
                    t = sum(wdl)
                    row["f"]["elo_1x2"] = {"p": tuple(x / t for x in wdl), "score": None}
            row["f"]["base"] = {"p": base_p, "score": base_score, "modal": base_score, "pscore": None}
            if e["id"] in book:
                b = book[e["id"]]
                bs = None
                if b["cs"]:
                    want = int(np.argmax(b["p"]))
                    keep = [(k, v) for k, v in b["cs"].items()
                            if sm.outcome_index(*k) == want]
                    if keep:
                        bs = max(keep, key=lambda kv: kv[1])[0]
                row["f"]["book"] = {"p": b["p"], "score": bs}
            rows.append(row)
        log(f"  window {w + 1}: {_date(start)} to {_date(end)}, {len(win)} matches "
            f"({time.time() - t0:.0f}s)")
    globals()["GRID_HALF_LIFE"], globals()["GRID_RIDGE"] = grid_hl, grid_rg
    return {"rows": rows, "tuning": tuning, "windows": [(_date(w[0]["ts"]), _date(w[-1]["ts"]), len(w))
                                                         for w in windows],
            "sources": dict(cur.source), "eligible": len(eligible), "test": len(test),
            "competitive": len(competitive), "with_stats": len(stats)}


METHODS = ["current", "poisson", "dc", "bivariate", "elo", "elo_1x2", "base", "book"]
LABEL = {"current": "Current (The case as built)", "poisson": "Independent Poisson (fitted attack and defence)",
         "dc": "Dixon-Coles", "bivariate": "Bivariate Poisson", "elo": "Independent Poisson (existing Elo ratings)",
         "elo_1x2": "Elo 1X2 (strength.py, reference)", "base": "Base rates",
         "book": "Betfair implied",
         "shipped": "Shipped constants (hindsight check)"}


def summarise(rows, methods, need=("current",)):
    """Every method scored on the matches where all of `need` have a forecast."""
    keep = [r for r in rows if all(m in r["f"] for m in need)]
    out = {}
    for m in methods:
        rs = [r for r in keep if m in r["f"]]
        if not rs or len(rs) < len(keep):
            continue
        s = score_rows([r["f"][m]["p"] for r in rs], [r["o"] for r in rs])
        sc = [r for r in rs if r["f"][m].get("score") is not None]
        s["exact"] = (sum(1 for r in sc if tuple(r["f"][m]["score"]) == (r["hg"], r["ag"])) / len(sc)
                      if sc else None)
        md = [r for r in rs if r["f"][m].get("modal") is not None]
        s["exact_modal"] = (sum(1 for r in md if tuple(r["f"][m]["modal"]) == (r["hg"], r["ag"])) / len(md)
                            if md else None)
        ps = [r["f"][m]["pscore"] for r in rs if r["f"][m].get("pscore") is not None]
        s["score_ll"] = (sum(-math.log(max(p, 1e-6)) for p in ps) / len(ps)) if ps else None
        out[m] = s
    return out, len(keep)


def paired(rows, a, b="current"):
    """Mean of (a - b) per match for RPS and log loss, with a 95% interval."""
    rs = [r for r in rows if a in r["f"] and b in r["f"]]
    out = {"n": len(rs)}
    for name, fn in (("rps", sm.rps), ("logloss", sm.log_loss)):
        d = np.array([fn(r["f"][a]["p"], r["o"]) - fn(r["f"][b]["p"], r["o"]) for r in rs])
        se = d.std(ddof=1) / math.sqrt(len(d)) if len(d) > 1 else float("nan")
        out[name] = (float(d.mean()), float(d.mean() - 1.96 * se), float(d.mean() + 1.96 * se))
    return out


def _f(x, d=4):
    return "" if x is None else f"{x:.{d}f}"


def _pct(x):
    return "" if x is None else f"{100 * x:.1f}%"


def report(res) -> str:
    """Every table for CASE-SCORE.md, as markdown."""
    rows = res["rows"]
    models = ("current", "poisson", "dc", "bivariate", "elo")
    common = [r for r in rows if all(m in r["f"] for m in models)]
    out = []

    def table(rs, methods, title):
        s, n = summarise(rs, methods, need=())
        out.append(f"\n### {title} ({n} matches)\n")
        out.append("| Method | Exact score (page pick) | Exact score (modal) | Score log loss "
                   "| Outcome accuracy | RPS | Brier | Log loss |")
        out.append("|---|---|---|---|---|---|---|---|")
        for m in methods:
            if m not in s:
                continue
            v = s[m]
            out.append(f"| {LABEL[m]} | {_pct(v['exact'])} | {_pct(v['exact_modal'])} | {_f(v['score_ll'])} "
                       f"| {_pct(v['acc'])} | {_f(v['rps'])} | {_f(v['brier'])} | {_f(v['logloss'])} |")

    out.append("## Windows\n")
    out.append("| Window | From | To | Test matches | Current method forecasts |")
    out.append("|---|---|---|---|---|")
    for i, (a, b, n) in enumerate(res["windows"], 1):
        k = sum(1 for r in rows if r["window"] == i and "current" in r["f"])
        out.append(f"| {i} | {a} | {b} | {n} | {k} |")

    allm = ["current", "poisson", "dc", "bivariate", "elo", "elo_1x2", "base", "shipped"]
    table(common, allm, "All test matches with every model")
    table([r for r in common if r["report"]], allm, "Report competitions only")

    out.append("\n### Paired difference against the current method (negative is better)\n")
    out.append("| Method | n | RPS diff | 95% interval | Log loss diff | 95% interval | Windows better on both |")
    out.append("|---|---|---|---|---|---|---|")
    for m in ("poisson", "dc", "bivariate", "elo", "elo_1x2", "base", "shipped"):
        d = paired(common, m)
        wins = 0
        for w in range(1, len(res["windows"]) + 1):
            dw = paired([r for r in common if r["window"] == w], m)
            wins += dw["rps"][0] < 0 and dw["logloss"][0] < 0
        out.append(f"| {LABEL[m]} | {d['n']} | {d['rps'][0]:+.4f} | {d['rps'][1]:+.4f} to {d['rps'][2]:+.4f} "
                   f"| {d['logloss'][0]:+.4f} | {d['logloss'][1]:+.4f} to {d['logloss'][2]:+.4f} "
                   f"| {wins} of {len(res['windows'])} |")

    out.append("\n### By window (RPS / log loss)\n")
    head = ["current", "poisson", "dc", "bivariate", "elo", "base"]
    out.append("| Window | n | " + " | ".join(LABEL[m] for m in head) + " |")
    out.append("|---|---|" + "---|" * len(head))
    for w in range(1, len(res["windows"]) + 1):
        rs = [r for r in common if r["window"] == w]
        s, n = summarise(rs, head, need=())
        out.append(f"| {w} | {n} | " + " | ".join(f"{s[m]['rps']:.4f} / {s[m]['logloss']:.4f}" for m in head) + " |")

    out.append("\n### By the current method's source\n")
    out.append("| Source | n | Current RPS | Adopted model RPS | Current log loss | Adopted model log loss |")
    out.append("|---|---|---|---|---|---|")
    for src in sorted({r["f"]["current"]["source"] for r in common}):
        rs = [r for r in common if r["f"]["current"]["source"] == src]
        s, n = summarise(rs, ["current", "shipped"], need=())
        out.append(f"| {src} | {n} | {s['current']['rps']:.4f} | {s['shipped']['rps']:.4f} "
                   f"| {s['current']['logloss']:.4f} | {s['shipped']['logloss']:.4f} |")

    out.append("\n### Draws: mean forecast against what happened\n")
    out.append("| Method | Mean home | Mean draw | Mean away | Draw called (page pick) |")
    out.append("|---|---|---|---|---|")
    n = len(common)
    act = [sum(1 for r in common if r["o"] == k) / n for k in range(3)]
    out.append(f"| Actual | {_pct(act[0])} | {_pct(act[1])} | {_pct(act[2])} | {_pct(act[1])} |")
    for m in ("current", "poisson", "dc", "bivariate", "elo", "elo_1x2"):
        mp = [sum(r["f"][m]["p"][k] for r in common) / n for k in range(3)]
        sc = [r for r in common if r["f"][m].get("score") is not None]
        called = (sum(1 for r in sc if r["f"][m]["score"][0] == r["f"][m]["score"][1]) / len(sc)) if sc else None
        out.append(f"| {LABEL[m]} | {_pct(mp[0])} | {_pct(mp[1])} | {_pct(mp[2])} | {_pct(called)} |")

    book = [r for r in common if "book" in r["f"]]
    out.append(f"\n### Against Betfair's implied chances ({len(book)} matches)\n")
    if book:
        bm = ["book", "current", "poisson", "dc", "bivariate", "elo", "base"]
        s, n = summarise(book, bm, need=())
        cs = sum(1 for r in book if r["f"]["book"].get("score") is not None)
        out.append(f"Betfair's exact score is the same pick rule run on its correct-score market, "
                   f"which only {cs} of these matches had.\n")
        out.append("| Method | Exact score (page pick) | Outcome accuracy | RPS | Brier | Log loss |")
        out.append("|---|---|---|---|---|---|")
        for m in bm:
            if m in s:
                v = s[m]
                out.append(f"| {LABEL[m]} | {_pct(v['exact'])} | {_pct(v['acc'])} | {_f(v['rps'])} "
                           f"| {_f(v['brier'])} | {_f(v['logloss'])} |")

    rest = [r for r in rows if "current" not in r["f"] and all(m in r["f"] for m in models[1:])]
    if rest:
        table(rest, ["poisson", "dc", "bivariate", "elo", "base"],
              "Test matches the current method cannot forecast")

    out.append("\n### Tuning (chosen on the 60 days before each window)\n")
    out.append("| Window | Model | Half-life (days) | Ridge | Validation matches | Home edge | rho | lambda3 | Teams |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for t in res["tuning"]:
        out.append(f"| {t['window']} | {LABEL[t['kind']]} | {t['half_life']} | {t['ridge']} | {t['valid_n']} "
                   f"| {t['home']:.3f} | {t['rho']:+.3f} | {t['l3']:.4f} | {t['teams']} |")

    out.append("\n### Validation log loss pooled over the four tuning periods (training data only)\n")
    out.append("| Model | Best half-life | Best ridge | Pooled validation log loss |")
    out.append("|---|---|---|---|")
    for kind in ("poisson", "dc", "bivariate"):
        agg, n = defaultdict(float), 0
        for t in res["tuning"]:
            if t["kind"] != kind:
                continue
            n += t["valid_n"]
            for hl, rg, ll, _ in t["grid"]:
                agg[(hl, rg)] += ll * t["valid_n"]
        (hl, rg), v = min(agg.items(), key=lambda kv: kv[1])
        out.append(f"| {LABEL[kind]} | {hl} | {rg} | {v / n:.4f} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--snapshots", type=Path, default=None,
                    help="folder of market_prices.json snapshots (from git history) for the bookmaker rows")
    ap.add_argument("--report", action="store_true", help="print the tables from the last run's results")
    args = ap.parse_args()
    if args.report:
        print(report(json.loads(OUT.read_text())))
        return
    res = run(args.quick, args.snapshots)
    for m in res["rows"]:
        for f in m["f"].values():
            for k in ("p", "score", "modal"):
                if isinstance(f.get(k), tuple):
                    f[k] = list(f[k])
    OUT.write_text(json.dumps(res))
    print(report(res))


if __name__ == "__main__":
    main()
