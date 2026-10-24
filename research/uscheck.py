#!/usr/bin/env python3
"""Score the live NBA and NFL player models on Paddy Power's settled lines.

    python3 research/uscheck.py nba|nfl      # writes research/uscheck_<sport>.csv

pplog.py logs the old last-10 chance (model.price_player) for NBA and NFL, not
the backtested models in usmodel/, so the pplog record says nothing about
them. This rebuilds, for every logged game, the chance the live model would
have given before tip-off: the same pre-game features (usfeatures.features,
strictly pre-game), the exported trees, spread and calibration, and the same
blend with the site chance the page applies. The exported models were trained
before these games (NBA to Jan 2026, NFL to Aug 2025), so this is out of sample.

One leak to know about: a past game's rows exist only for players who played,
which is what a confirmed line-up gives. A did-not-play voids at Paddy Power.

Lines that pplog has not settled yet are settled here from the cached box
score (cache/event_<id>_lineups.json), same rule as pplog: over means more
than the line, a player with no stats is void.

Reads cache/ and pplog/ only. Nothing is fetched.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pplog  # noqa: E402
import usfeatures as U  # noqa: E402
import usmodel_live as L  # noqa: E402

SITE = {"nba": "basketball", "nfl": "american-football"}
BOX = {  # pplog stat -> SofaScore box keys (for lines pplog has not settled)
    "Points": ["points"], "Rebounds": ["rebounds"], "Assists": ["assists"],
    "Three pointers made": ["threePointsMade"], "Steals": ["steals"], "Blocks": ["blocks"],
    "Turnovers": ["turnovers"], "Points and assists": ["points", "assists"],
    "Points and rebounds": ["points", "rebounds"], "Rebounds and assists": ["rebounds", "assists"],
    "Points rebounds and assists": ["points", "rebounds", "assists"],
    "Receiving yards": ["receivingYards"], "Receiving receptions": ["receivingReceptions"],
    "Rushing yards": ["rushingYards"], "Passing yards": ["passingYards"],
    "Passing touchdowns": ["passingTouchdowns"], "Passing completions": ["passingCompletions"],
    "Passing attempts": ["passingAttempts"], "Rushing attempts": ["rushingAttempts"],
    "Rushing and receiving yards": ["rushingYards", "receivingYards"],
    "Passing and rushing yards": ["passingYards", "rushingYards"],
}
lg = lambda q: math.log(min(1 - 1e-4, max(1e-4, q)) / (1 - min(1 - 1e-4, max(1e-4, q))))
sg = lambda z: 1 / (1 + math.exp(-z))


def box_result(r: dict, cache: dict):
    e = r["event_id"]
    if e not in cache:
        f = ROOT / "cache" / f"event_{e}_lineups.json"
        ev = ROOT / "cache" / f"event_{e}.json"
        d = {}
        try:
            st = json.loads(ev.read_text())
            st = (st.get("event") or st).get("status", {}).get("type")
            if st == "finished":
                lu = json.loads(f.read_text())
                for side in ("home", "away"):
                    for p in lu.get(side, {}).get("players", []):
                        d[pplog._norm(p["player"]["name"])] = p.get("statistics") or {}
        except (OSError, ValueError):
            pass
        cache[e] = d
    keys = BOX.get(r["stat"])
    s = cache[e].get(pplog._norm(r["player"]))
    if not keys or s is None or not any(k in s for k in keys):
        return None
    if "secondsPlayed" in s and (s.get("secondsPlayed") or 0) < 60:
        return None
    v = sum(s.get(k) or 0 for k in keys)
    return "win" if (v > r["line"]) == bool(r["over"]) else "lose"


def build_with(sport: str, want: set):
    """U.build, plus logged games missing from the cached team fixture lists
    (they lag a day): their own event_<id>.json is added as one more list."""
    import glob as G
    import tempfile
    extra = []
    for e in want:
        f = ROOT / "cache" / f"event_{e}.json"
        try:
            d = json.loads(f.read_text())
            extra.append(d.get("event") or d)
        except (OSError, ValueError):
            pass
    tmp = Path(tempfile.mkdtemp()) / "team_0_events_last_0.json"
    tmp.write_text(json.dumps({"events": extra}))
    real = G.glob

    def patched(pattern, *a, **k):
        out = real(pattern, *a, **k)
        return out + [str(tmp)] if "events_last" in pattern else out
    U.glob.glob = patched
    try:
        return U.build(str(ROOT / "cache"), sport)
    finally:
        U.glob.glob = real


def run(sport: str) -> pd.DataFrame:
    meta = json.loads((L.MODELS / f"{sport}_meta.json").read_text())
    by_stat = {m["page_stat"]: (t, m) for t, m in meta["targets"].items()}
    rows = [r for r in pplog.all_rows() if r.get("sport") == SITE[sport] and r["stat"] in by_stat]
    bc = {}
    for r in rows:
        if r.get("result") not in ("win", "lose"):
            res = box_result(r, bc)
            r["result"] = res if res else r.get("result")
    rows = [r for r in rows if r.get("result") in ("win", "lose")]
    if not rows:
        return pd.DataFrame()
    M, T, P = build_with(sport, {r["event_id"] for r in rows})
    if sport == "nba":
        P["pra"] = P.points + P.rebounds + P.assists
        P["pr"] = P.points + P.rebounds
        P["pa"] = P.points + P.assists
        P["ra"] = P.rebounds + P.assists
    else:
        P["rush_rec_yds"] = P.rush_yds + P.rec_yds
        P["pass_rush_yds"] = P.pass_yds + P.rush_yds
    want = {r["event_id"] for r in rows}
    F = U.features(M, T, P, sport)
    F = F[F.match.isin(want)].copy()
    pos_codes = meta.get("pos_codes")
    F["pos_c"] = F.pos.map(pos_codes).fillna(-1) if pos_codes else F.pos.astype("category").cat.codes
    mus = {}
    for tgt, m in meta["targets"].items():
        sub = F
        base = np.clip(sub[m["base"]].astype(float).fillna(0).values, 0.05, None)
        mu = base * L.Model(L.MODELS / f"{sport}_{tgt}.json.gz").predict(
            sub.reindex(columns=m["features"]).astype(float).values)
        for r, mu_i in zip(sub.itertuples(index=False), mu):
            mus[(int(r.match), L.norm(r.name), m["page_stat"])] = float(mu_i)
    out = []
    for r in rows:
        t, m = by_stat[r["stat"]]
        mu = mus.get((r["event_id"], L.norm(r["player"]), r["stat"]))
        if mu is None:
            continue
        pm = L.calibrate(L.p_over(m["spread"], mu, r["line"]), m["cal"])
        f = r["first"]
        site_over = f["chance"] if r["over"] else 1 - f["chance"]
        sf = sg(m["site_cal"][0] + m["site_cal"][1] * lg(site_over))
        pb = sg(m["blend"][0] + m["blend"][1] * lg(pm) + m["blend"][2] * lg(sf))
        side = (lambda q: q) if r["over"] else (lambda q: 1 - q)
        out.append({
            "event_id": r["event_id"], "fixture": r["fixture"], "kickoff": r["kickoff"],
            "player": r["player"], "stat": r["stat"], "line": r["line"], "over": int(bool(r["over"])),
            "price_first": f["price"], "price_last": r["last"]["price"],
            "p_model": side(pm), "p_blend": side(pb), "p_site": side(site_over), "mu": mu,
            "k10": r.get("k10"), "n10": r.get("n10"), "win": int(r["result"] == "win"),
        })
    return pd.DataFrame(out)


if __name__ == "__main__":
    sp = sys.argv[1]
    df = run(sp)
    path = ROOT / "research" / f"uscheck_{sp}.csv"
    df.to_csv(path, index=False)
    print(f"{sp}: {len(df)} settled lines scored, {df.event_id.nunique() if len(df) else 0} games -> {path.name}")
