#!/usr/bin/env python3
"""The models learning from every settled bet: learn/learned.json.

    python learn.py fit       # nightly, after pplog settle (update.py / publish.sh)
    python learn.py report    # print what is adopted and how it tested

Why (26 Oct 2026): the NBA, NFL and football player models were trained once
and never saw how their chances fared against Paddy Power. The log now holds
thousands of settled lines with the model's chance, Paddy's price and the
result, so each night this fits, per sport and side (over / under), and per
stat where there is enough, a correction of the form

    learned = sigmoid(a + b * logit(model) + c * logit(market))

where market is Paddy's margin-free chance (both sides of the line when Paddy
offers both, else the price less the average margin). b and c say how much to
trust the model and the market; a corrects a lean such as NBA overs coming in
short. With c near 1 and b near 0 the model is adding nothing and its "edges"
fade to zero; with b high it is earning its keep.

The rule that stops it learning noise: every correction is fitted on the
older games and scored on the newest 30% of games, which it never saw. It is
adopted only if it beats the current chance (the raw model) on those games,
in at least 80% of resamples by game. Otherwise it stays off, and the
model's own chance is used as before. Adopted corrections are refitted on all
games for live use. Coefficients are pulled towards "no change" (a=0, b=1,
c=0), harder the fewer games there are.

Football uses only rows scored by the player model (fmodel), which are the
predicted or confirmed starters; the blind football rows include substitutes
and would teach it the wrong thing.

Reads pplog/ and research/uscheck_*.csv. Writes learn/learned.json and
LEARNING.md. Nothing is fetched. Never changes a past record.
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pplog  # noqa: E402

OUT = ROOT / "learn" / "learned.json"
DOC = ROOT / "LEARNING.md"
HOLDOUT = 0.30          # newest share of games kept unseen
MIN_ROWS = 300          # a segment needs this many settled lines
MIN_GAMES = 8           # and this many games
STAT_ROWS = 400         # a stat inside a segment needs this many to get its own fit
WIN_SHARE = 0.80        # holdout gain must hold in this share of resamples
EPS = 1e-4
PRIOR = np.array([0.0, 1.0, 0.0])
SPORTS = ("basketball", "american-football", "football")

lg = lambda p: np.log(np.clip(p, EPS, 1 - EPS) / (1 - np.clip(p, EPS, 1 - EPS)))
sg = lambda z: 1 / (1 + np.exp(-z))


# ------------------------------------------------------------------ data

def _hist() -> dict:
    out = {}
    for sp in ("nba", "nfl"):
        f = ROOT / "research" / f"uscheck_{sp}.csv"
        if f.exists():
            with f.open() as fh:
                for r in csv.DictReader(fh):
                    out[(int(r["event_id"]), pplog._norm(r["player"]), r["stat"], float(r["line"]),
                         bool(int(r["over"])))] = float(r["p_model"])
    return out


def model_side(r: dict, hist: dict):
    """The model's own chance for this side, before kick-off, or None."""
    s = r.get("first") or {}
    if r["sport"] == "football":
        return s.get("chance") if s.get("source") == "fmodel" else None
    if s.get("model_chance") is not None:
        return s["model_chance"]
    return hist.get((r["event_id"], pplog._norm(r["player"]), r["stat"], r["line"], bool(r["over"])))


def rows(settled_only: bool = True) -> list[dict]:
    hist = _hist()
    allr = [r for r in pplog.all_rows() if r.get("sport") in SPORTS]
    price = defaultdict(dict)
    for r in allr:
        p = (r.get("first") or {}).get("price")
        if p:
            price[(r["event_id"], r["player"], r["stat"], r["line"])][bool(r["over"])] = p
    out = []
    for r in allr:
        if settled_only and r.get("result") not in ("win", "lose"):
            continue
        pm = model_side(r, hist)
        p = (r.get("first") or {}).get("price")
        if pm is None or not p or p <= 1.0:
            continue
        both = price[(r["event_id"], r["player"], r["stat"], r["line"])]
        fair = None
        if len(both) == 2:
            a, b = 1 / both[bool(r["over"])], 1 / both[not bool(r["over"])]
            fair = a / (a + b)
        out.append({"sport": r["sport"], "stat": r["stat"], "over": bool(r["over"]), "pm": float(pm),
                    "price": float(p), "fair": fair, "game": r["event_id"], "t": r["kickoff"],
                    "y": 1 if r.get("result") == "win" else 0, "row": r})
    return out


def overrounds(rs: list[dict]) -> dict:
    """Average margin per sport on lines with both sides: used to take the
    margin off a price with only one side shown."""
    acc = defaultdict(list)
    for x in rs:
        if x["fair"] is not None:
            acc[x["sport"]].append((1 / x["price"]) / x["fair"])
    return {k: float(np.mean(v)) for k, v in acc.items() if len(v) >= 50}


def market(x: dict, ovr: dict) -> float:
    if x["fair"] is not None:
        return x["fair"]
    return min(0.98, (1 / x["price"]) / ovr.get(x["sport"], 1.08))


# ------------------------------------------------------------------ fitting

def design(xs, ovr):
    return np.c_[np.ones(len(xs)), lg(np.array([x["pm"] for x in xs])),
                 lg(np.array([market(x, ovr) for x in xs]))]


def fit(X, y, prior=PRIOR, lam=None):
    """Logistic regression pulled towards `prior` (ridge on the difference)."""
    n = len(y)
    lam = lam if lam is not None else 25.0 + 2000.0 / max(n, 1) * 10
    w = prior.astype(float).copy()
    for _ in range(60):
        p = sg(X @ w)
        g = X.T @ (y - p) - lam * (w - prior)
        H = X.T @ (X * (p * (1 - p))[:, None]) + lam * np.eye(3)
        step = np.linalg.solve(H, g)
        w += step
        if np.abs(step).max() < 1e-7:
            break
    return w


def logloss(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def gate(xs, ovr, prior=PRIOR):
    """Fit on the older games, score on the newest. Returns (coef_all, report)."""
    games = sorted({x["game"]: x["t"] for x in xs}.items(), key=lambda kv: kv[1])
    k = max(1, int(round(len(games) * HOLDOUT)))
    newest = {g for g, _ in games[-k:]}
    tr = [x for x in xs if x["game"] not in newest]
    te = [x for x in xs if x["game"] in newest]
    rep = {"rows": len(xs), "games": len(games), "test_games": k, "test_rows": len(te)}
    if len(tr) < MIN_ROWS // 2 or len(te) < 50:
        rep["adopted"] = False
        rep["why"] = "too few lines"
        return None, rep
    Xtr, ytr = design(tr, ovr), np.array([x["y"] for x in tr])
    Xte, yte = design(te, ovr), np.array([x["y"] for x in te])
    w = fit(Xtr, ytr, prior)
    p_new, p_old = sg(Xte @ w), np.array([x["pm"] for x in te])
    p_mkt = sg(Xte[:, 2])
    rep.update({"ll_model": logloss(yte, p_old), "ll_learned": logloss(yte, p_new),
                "ll_market": logloss(yte, p_mkt), "coef_train": [round(float(v), 3) for v in w]})
    # resample by game: how often is learned better than the model?
    by = defaultdict(list)
    for i, x in enumerate(te):
        by[x["game"]].append(i)
    gl = list(by.values())
    rng = random.Random(11)
    wins = 0
    for _ in range(500):
        idx = [i for g in (rng.choice(gl) for _ in gl) for i in g]
        wins += logloss(yte[idx], p_new[idx]) < logloss(yte[idx], p_old[idx])
    rep["win_share"] = wins / 500
    # what betting the learned edges would have done on the unseen games
    for name, pp in (("model", p_old), ("learned", p_new)):
        e = pp * np.array([x["price"] for x in te]) - 1
        sel = (e >= 0.03) & (e <= 0.25)
        if sel.sum():
            pr = np.where(yte[sel] == 1, np.array([x["price"] for x in te])[sel] - 1, -1.0)
            rep[f"bets_{name}"] = int(sel.sum())
            rep[f"roi_{name}"] = round(float(pr.mean()), 4)
    rep["adopted"] = bool(rep["ll_learned"] < rep["ll_model"] - 0.001 and rep["win_share"] >= WIN_SHARE)
    if not rep["adopted"]:
        rep["why"] = "did not beat the model on the newest games"
        return None, rep
    w_all = fit(design(xs, ovr), np.array([x["y"] for x in xs]), prior)
    rep["coef"] = [round(float(v), 4) for v in w_all]
    return w_all, rep


def run_fit() -> dict:
    rs = rows()
    ovr = overrounds(rs)
    segs = defaultdict(list)
    for x in rs:
        segs[(x["sport"], "over" if x["over"] else "under")].append(x)
    out = {"generated": time.time(), "overround": ovr, "segments": {}, "stats": {}}
    for (sport, side), xs in sorted(segs.items()):
        key = f"{sport}|{side}"
        if len(xs) < MIN_ROWS or len({x["game"] for x in xs}) < MIN_GAMES:
            out["segments"][key] = {"adopted": False, "why": "too few lines", "rows": len(xs)}
            continue
        w, rep = gate(xs, ovr)
        out["segments"][key] = rep
        base = np.array(w) if w is not None else PRIOR
        # a stat gets its own correction only if it beats the segment's on its newest games
        by = defaultdict(list)
        for x in xs:
            by[x["stat"]].append(x)
        for stat, sx in by.items():
            if len(sx) < STAT_ROWS or len({x["game"] for x in sx}) < MIN_GAMES:
                continue
            ws, srep = gate(sx, ovr, prior=base)
            if ws is not None:
                # compare against the segment correction, not only the raw model
                te_games = sorted({x["game"]: x["t"] for x in sx}.items(), key=lambda kv: kv[1])
                newest = {g for g, _ in te_games[-max(1, int(round(len(te_games) * HOLDOUT))):]}
                te = [x for x in sx if x["game"] in newest]
                X, y = design(te, ovr), np.array([x["y"] for x in te])
                if logloss(y, sg(X @ ws)) >= logloss(y, sg(X @ base)) - 0.001:
                    srep["adopted"], srep["why"] = False, "no better than the side-wide correction"
                    srep.pop("coef", None)
            out["stats"][f"{key}|{stat}"] = srep
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    write_doc(out)
    return out


# ------------------------------------------------------------------ using it

_L = None


def _load():
    global _L
    if _L is None:
        try:
            _L = json.loads(OUT.read_text())
        except (OSError, ValueError):
            _L = {}
    return _L


def adjust(sport: str, stat: str, over: bool, p_model: float, price: float | None,
           fair: float | None = None):
    """The learned chance for one side, and where it came from. Falls back to
    the model's own chance wherever nothing has been adopted."""
    L = _load()
    side = "over" if over else "under"
    for key in (f"{sport}|{side}|{stat}", f"{sport}|{side}"):
        seg = (L.get("stats") or {}).get(key) or (L.get("segments") or {}).get(key)
        if seg and seg.get("adopted") and seg.get("coef"):
            if fair is None:
                if not price:
                    return p_model, "model"
                fair = min(0.98, (1 / price) / (L.get("overround") or {}).get(sport, 1.08))
            a, b, c = seg["coef"]
            return float(sg(a + b * lg(p_model) + c * lg(fair))), key
    return p_model, "model"


# ------------------------------------------------------------------ record

def write_doc(out: dict) -> None:
    lines = ["# What the models have learned", "",
             f"Regenerated by `learn.py fit`, {time.strftime('%d %b %Y %H:%M')}. Each correction is fitted on the "
             "older games and tested on the newest 30% it never saw; it is used only if it beats the model's own "
             f"chance there in {WIN_SHARE:.0%}+ of resamples by game. learned = sigmoid(a + b x model + c x market), "
             "all on the log-odds scale; b is trust in the model, c trust in Paddy's margin-free price.", "",
             "| Segment | Lines | Games | Log loss: model / learned / market | Wins | Bets 3-25% edge, ROI: model / learned | Used? | a, b, c |",
             "|---|---|---|---|---|---|---|---|"]
    allsegs = list((out.get("segments") or {}).items()) + list((out.get("stats") or {}).items())
    for k, r in allsegs:
        if "ll_model" not in r:
            lines.append(f"| {k} | {r.get('rows', '')} | | | | | no ({r.get('why', '')}) | |")
            continue
        bets = (f"{r.get('bets_model', 0)} {r.get('roi_model', 0):+.0%} / "
                f"{r.get('bets_learned', 0)} {r.get('roi_learned', 0):+.0%}")
        coef = ", ".join(f"{v:.2f}" for v in (r.get("coef") or r.get("coef_train") or []))
        lines.append(f"| {k} | {r['rows']} | {r['games']} | {r['ll_model']:.4f} / {r['ll_learned']:.4f} / "
                     f"{r['ll_market']:.4f} | {r['win_share']:.0%} | {bets} | "
                     f"{'**yes**' if r['adopted'] else 'no'} | {coef} |")
    lines += ["", "Bets and ROI are on the unseen newest games only, £1 at Paddy's first price, edge between 3% "
              "and 25%. A segment that is not used falls back to the model's own chance."]
    log = ROOT / "usmodel" / "CHANGELOG.md"
    if log.exists():
        lines += ["", "## NBA/NFL model weekly steps (usmodel_weekly.py)", "",
                  "Small Poisson tree corrections on top of the player models, adopted only if better on the "
                  "latest 21 days. Full history in `usmodel/CHANGELOG.md`; latest entries:", ""]
        lines += [l for l in log.read_text().splitlines() if l.startswith("- ")][-23:]
    DOC.write_text("\n".join(lines) + "\n")


def report() -> None:
    print(DOC.read_text() if DOC.exists() else "No LEARNING.md yet: run python learn.py fit")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "fit":
        o = run_fit()
        n = sum(1 for r in list(o["segments"].values()) + list(o["stats"].values()) if r.get("adopted"))
        print(f"learn: {n} correction(s) adopted, LEARNING.md written")
    else:
        report()
