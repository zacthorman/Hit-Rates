#!/usr/bin/env python3
"""The backtested NBA and NFL player models, run live: reports/usmodel.json.

    .venv/bin/python usmodel_live.py            # games in the next 7 days, both sports
    .venv/bin/python usmodel_live.py --days 3

The NBA / NFL counterpart of fmodel_live.py. What it does:
  1. Reads every finished NBA and NFL game in cache/ (nothing is fetched).
  2. Takes the upcoming games from reports/nba.html and reports/nfl.html, and
     for each side its current squad (cache/team_{id}_players.json) less
     anyone ruled out (NFL: ESPN's Out / Doubtful / IR list).
  3. Builds the same pre-game features the backtest trained on, with the
     shared module usfeatures.py, so the two cannot drift apart.
  4. Scores each market's exported trees (usmodel/*.json.gz) with numpy for
     the player's expected number, turns it into a chance at every line with
     the spread fitted on validation, and calibrates it.

The page blends that chance with its own (weights fitted on validation, in
usmodel.json under "blend") wherever it has one. The models were trained in
the backtest: NFL 2020 to now (out-of-sample from December 2025), NBA
2025-26 (out-of-sample from April 2026). See USAGE.md, "NBA and NFL model".
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import usfeatures as U  # noqa: E402
from fmodel.fmodel_trees import Tree  # noqa: E402

CACHE = ROOT / "cache"
MODELS = ROOT / "usmodel"
OUT = ROOT / "reports" / "usmodel.json"
REPORT = {"nba": ROOT / "reports" / "nba.html", "nfl": ROOT / "reports" / "nfl.html"}
OUT_STATUS = ("out", "doubtful", "injured reserve", "suspension", "ir")
# the statuses team_news.py writes that keep a man out (the page's INJ_OUT)
import re  # noqa: E402
NEWS_OUT = re.compile(r"^(out|doubtful|suspen|injured reserve|ir\b|inactive|not in squad|pup|"
                      r"physically unable|non-football|reserve)", re.I)


def norm(s: str) -> str:
    """Same as normName() in the page."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if c.isascii() and (c.isalpha() or c == " "))
    return " ".join(s.lower().split())


class Model:
    """Exported LightGBM trees, Poisson: the expected number is exp(sum of leaves)."""

    def __init__(self, path: Path):
        with gzip.open(path, "rt") as f:
            d = json.load(f)
        self.trees = [Tree(t["tree_structure"]) for t in d["tree_info"]]

    def predict(self, X):
        X = np.asarray(X, float)
        raw = np.zeros(len(X))
        for t in self.trees:
            raw += t.predict(X)
        return np.exp(raw)


def p_over(spread, mu, line):
    if spread["type"] == "ratio":
        b = min(3, max(0, int(np.searchsorted(spread["edges"], mu)) - 1))
        q = np.asarray(spread["q"][b])
        return float(np.mean(mu * q > line))
    from math import floor
    size = spread["size"]
    k = floor(line)
    p = size / (size + mu)
    # negative binomial cdf by summation (no scipy on the Mac)
    cdf, term = 0.0, p ** size
    for i in range(int(k) + 1):
        if i > 0:
            term *= (i - 1 + size) / i * (1 - p)
        cdf += term
    return max(0.0, 1 - cdf)


def calibrate(p, ab):
    p = min(1 - 1e-4, max(1e-4, p))
    return 1 / (1 + math.exp(-(ab[0] + ab[1] * math.log(p / (1 - p)))))


def payload(path: Path) -> dict | None:
    import rerender
    return rerender.payload_of(path)


def squads() -> dict[int, set[int]]:
    out = {}
    for f in CACHE.glob("team_*_players.json"):
        try:
            tid = int(f.name.split("_")[1])
            out[tid] = {p["player"]["id"] for p in json.loads(f.read_text()).get("players", [])}
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
    return out


ESPN = {"nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries",
        "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"}


def espn_injuries(sport: str, max_age: float = 3 * 3600) -> dict:
    """ESPN's injury report, cached for three hours (one request a publish at
    most). The NFL one is also kept fresh by nfl_injuries.py. Never fatal."""
    path = CACHE / f"espn_{sport}_injuries.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age:
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    try:
        import urllib.request
        req = urllib.request.Request(ESPN[sport], headers={"User-Agent": "Mozilla/5.0 hit-rates"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        path.write_text(json.dumps(data))
        return data
    except Exception as exc:  # noqa: BLE001
        print(f"  usmodel: ESPN {sport} injuries not fetched ({type(exc).__name__}), using cache if any")
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}


def ruled_out(sport: str) -> set[str]:
    """Names on ESPN's report as out, doubtful, suspended or on injured
    reserve. They are left out of the expected players, and their absence
    counts in the team-mates' missing-usage features, as in training."""
    d = espn_injuries(sport)
    names = set()
    for team in d.get("injuries", []):
        for inj in team.get("injuries", []):
            status = str(inj.get("status") or (inj.get("type") or {}).get("description") or "").lower()
            who = (inj.get("athlete") or {}).get("displayName") or ""
            if who and any(s in status for s in OUT_STATUS):
                names.add(norm(who))
    return names


def run_sport(sport: str, days: float, now: float) -> dict:
    meta_path = MODELS / f"{sport}_meta.json"
    data = payload(REPORT[sport]) if REPORT[sport].exists() else None
    if not meta_path.exists() or not data:
        return {}
    meta = json.loads(meta_path.read_text())
    games, news_out, lineups, names = [], set(), {}, {}
    for fx in data.get("fixtures", []):
        f = fx.get("fixture") or {}
        ko = f.get("kickoff")
        teams = fx.get("teams") or []
        if not ko or not (now < ko < now + days * 86400) or len(teams) < 2:
            continue
        d = pd.Timestamp(ko, unit="s")
        names[teams[0]["id"]], names[teams[1]["id"]] = teams[0].get("name"), teams[1].get("name")
        games.append({"match": int(f["id"]), "ts": int(ko), "home": teams[0]["id"], "away": teams[1]["id"],
                      "season": d.year if d.month >= U.SPORT[sport]["season_month"] else d.year - 1})
        # team news (team_news.py): who is out, and the confirmed line-up
        for t, side in enumerate(("home", "away")):
            for row in (fx.get("injuries") or {}).get(side) or []:
                if NEWS_OUT.match(row[2] or ""):
                    news_out.add(norm(row[0]))
            c = ((fx.get("lineups") or {}).get("confirmed") or {}).get(side) or {}
            if c.get("xi"):
                xi = [p.get("name") for p in c["xi"]]
                lineups[(int(f["id"]), teams[t]["id"])] = {"xi": xi, "roster": xi + list(c.get("bench") or [])}
    if not games:
        return {}
    M, T, P = U.build(str(CACHE), sport)
    if sport == "nba":
        P["pra"] = P.points + P.rebounds + P.assists
        P["pr"] = P.points + P.rebounds
        P["pa"] = P.points + P.assists
        P["ra"] = P.rebounds + P.assists
    else:
        P["rush_rec_yds"] = P.rush_yds + P.rec_yds
        P["pass_rush_yds"] = P.pass_yds + P.rush_yds
    known = set(M.match)
    games = [g for g in games if g["match"] not in known]
    out_names = ruled_out(sport) | news_out
    out_ids = set(P[P.name.map(lambda n: norm(n) in out_names)].pid) if out_names else set()
    M2, T2, P2 = U.add_upcoming(M, T, P, games, sport, out_ids=out_ids, squads=squads(), lineups=lineups)
    wanted = {g["match"] for g in games}
    F = U.features(M2, T2, P2, sport, only=wanted)
    if F.empty:
        # No rows at all (no upcoming game, or nobody with three games behind
        # him) has no columns either, so there is no F.match to filter on.
        return {}
    F = F[F.match.isin(wanted)].copy()
    if F.empty:
        return {}
    F["pos_c"] = F.pos.astype("category").cat.codes  # same mapping as training below
    pos_codes = meta.get("pos_codes")
    if pos_codes:
        F["pos_c"] = F.pos.map(pos_codes).fillna(-1)
    events: dict = {}
    for tgt, m in meta["targets"].items():
        ok = F[f"{tgt}_med10"].astype(float) >= m["eligible"]["min_median"] if f"{tgt}_med10" in F else None
        if tgt == "td":
            ok = F["rec_m10"].astype(float) + F["rush_att_m10"].astype(float) >= 3
        if m["eligible"]["positions"]:
            ok &= F.pos.isin(m["eligible"]["positions"])
        sub = F[ok]
        if sub.empty:
            continue
        # his own weighted average times the trees' adjustment (a Poisson offset)
        base = np.clip(sub[m["base"]].astype(float).fillna(0).values, 0.05, None)
        mu = base * Model(MODELS / f"{sport}_{tgt}.json.gz").predict(sub.reindex(columns=m["features"]).astype(float).values)
        yards = m["spread"]["type"] == "ratio"
        for r, mu_i in zip(sub.itertuples(index=False), mu):
            if yards:
                ks = range(max(1, int(mu_i * 0.3)), int(mu_i * 1.9) + 6)
            else:
                ks = range(1, max(4, int(math.ceil(mu_i * 2.5)) + 3))
            lines = {str(k): round(calibrate(p_over(m["spread"], mu_i, k - 0.5), m["cal"]), 4) for k in ks}
            ev = events.setdefault(str(r.match), {"players": {},
                                                  "confirmed": any(k[0] == r.match for k in lineups)})
            pl = ev["players"].setdefault(r.name, {"lines": {}, "mu": {}})
            pl["lines"][m["page_stat"]] = lines
            pl["mu"][m["page_stat"]] = round(float(mu_i), 2)
    blend = {m["page_stat"]: {"site_cal": m["site_cal"], "blend": m["blend"]} for m in meta["targets"].values()}
    # Team stats and the game state (usgame.py, nba_team_train.py): pace,
    # ratings, expected total and margin, blowout risk, rest, and each side's
    # team numbers priced by the model chosen in the backtest. Never fatal.
    if sport == "nba" and (MODELS / "nba_team.json").exists():
        try:
            import usgame
            for mid, tv in usgame.nba_teams(T, P, games, names, MODELS).items():
                ev = events.setdefault(mid, {"players": {}, "confirmed": False})
                ev.update(tv)
        except Exception as exc:  # noqa: BLE001
            print(f"  usmodel: nba team model not scored ({type(exc).__name__}: {exc})")
    return {"events": events, "blend": blend, "trained": meta.get("trained")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=7)
    a = ap.parse_args(argv)
    t0, now = time.time(), time.time()
    out = {"generated": now, "events": {}, "blend": {}}
    for sport in ("nba", "nfl"):
        try:
            r = run_sport(sport, a.days, now)
        except Exception as e:  # noqa: BLE001 - never fatal: the page keeps its own chances
            print(f"  usmodel: {sport} not scored ({type(e).__name__}: {e})")
            continue
        out["events"].update(r.get("events", {}))
        out["blend"][{"nba": "basketball", "nfl": "american-football"}[sport]] = r.get("blend", {})
        n_pl = sum(len(e["players"]) for e in r.get("events", {}).values())
        print(f"  usmodel: {sport} {len(r.get('events', {}))} game(s), {n_pl} players")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"  usmodel.json written in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
