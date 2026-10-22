#!/usr/bin/env python3
"""Team lines: which markets have earned a take, and the chance the page prices them at.

    import teamlines
    teamlines.market_key("Corner kicks", "home")    # "Corner kicks|side"
    teamlines.gate()                               # teamlines_gate.json, written by teamline_backtest.py
    teamlines.verdict(key, p, price)               # "take", "ok", "long", "avoid" or None

On 21 Oct 2026, 26 of the 30 takes on the European pages were team lines with
no evidence behind them, so the page stopped calling any of them a take.
teamline_backtest.py replays every cached match and writes, per market, whether
the team model passed and the smallest edge that held up on held-out data.
This module reads that file for teamlog.py and report.py, so the page and the
record cannot disagree on what a take is. Pure Python: the Mac page has no
scipy or LightGBM.

A market is a stat and a scope: a side's own count ("side") or both sides
added together ("match"). Paddy Power's "N or more" fouls and shots on target
are side markets offered as overs only.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATE = ROOT / "teamlines_gate.json"

# stat -> scopes Paddy Power prices, and whether the under is offered
MARKETS = {
    ("Corner kicks", "side"): True,
    ("Corner kicks", "match"): True,
    ("Yellow cards", "side"): True,
    ("Yellow cards", "match"): True,
    ("Fouls", "side"): False,
    ("Shots on target", "side"): False,
    ("Total shots", "side"): False,
}
LABEL = {"Corner kicks": "corners", "Yellow cards": "cards", "Fouls": "fouls",
         "Shots on target": "shots on target", "Total shots": "shots"}
# The page's own caps, kept as they are: under 50% is a long shot, more than
# 5% short of our chance is avoid, and an edge over 30% is our number being
# off more often than the bookmaker's.
MIN_P = 0.5
AVOID = -0.05
SUSPECT = 0.30

_GATE: dict = {}


def market_key(stat: str, scope: str) -> str:
    return f"{stat}|{'match' if scope == 'match' else 'side'}"


def market_name(key: str) -> str:
    stat, scope = key.split("|")
    return f"{LABEL.get(stat, stat)} ({'match total' if scope == 'match' else 'one side'})"


def gate(path: Path | None = None) -> dict:
    """The backtest's verdict per market, {} when it has not been run."""
    if path is not None:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    if not _GATE:
        try:
            _GATE.update(json.loads(GATE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            _GATE["markets"] = {}
    return _GATE


def market_gate(key: str, g: dict | None = None) -> dict | None:
    """{pass, threshold, alpha_match, ...} for a market, or None if it never passed."""
    m = ((g if g is not None else gate()).get("markets") or {}).get(key)
    return m if m and m.get("pass") else None


def nb_at_least(k: int, mu: float, alpha: float) -> float:
    """P(X >= k), negative binomial with mean mu and var mu + alpha mu^2 (Poisson at alpha 0)."""
    if k <= 0:
        return 1.0
    if mu <= 0:
        return 0.0
    if alpha < 1e-6:
        cdf, term = 0.0, math.exp(-mu)
        for i in range(k):
            cdf += term
            term *= mu / (i + 1)
        return min(1.0, max(0.0, 1 - cdf))
    r = 1 / alpha
    q = r / (r + mu)
    cdf, term = 0.0, q ** r
    for i in range(k):
        cdf += term
        term *= (i + r) / (i + 1) * (1 - q)
    return min(1.0, max(0.0, 1 - cdf))


def p_line(line: float, over: bool, mu: float, alpha: float) -> float:
    """Chance of over (or under) a half-integer line."""
    p = nb_at_least(int(math.floor(line)) + 1, mu, alpha)
    return p if over else 1 - p


def verdict(key: str, p: float | None, price: float | None, g: dict | None = None) -> str | None:
    """The page's verdict for a team line priced by the team model.

    Take only when the market passed the backtest, the chance is at least
    50%, and the edge is at least the market's held-out threshold but not
    past the 30% cap. Everything else is at most acceptable, as before."""
    if not (price and price > 1) or not (p and p > 0):
        return None
    e = p * price - 1
    if e < AVOID:
        return "avoid"
    if p < MIN_P:
        return "long"
    m = market_gate(key, g)
    if m and e >= m["threshold"] and e <= SUSPECT:
        return "take"
    return "ok"


def page_gate(g: dict | None = None) -> dict:
    """What the page needs from the gate: the passed markets and the take shortfall."""
    g = gate() if g is None else g
    return {"markets": {k: {"threshold": m["threshold"], "alpha_match": m.get("alpha_match")}
                        for k, m in (g.get("markets") or {}).items() if m.get("pass")},
            "shortfall": g.get("take_shortfall")}


def side_models(entry: dict, stats=None) -> dict:
    """{stat: [home side, away side]} of {mu, alpha} from the team model, None where it has no number.

    The page's teams order, as context.gs_adjust() reads it: each side's id,
    home or away, and the formation from the confirmed or predicted line-up."""
    import context
    teams = entry.get("teams") or []
    if len(teams) != 2:
        return {}
    out = {}
    for s in stats or sorted({s for s, _ in MARKETS}):
        row = []
        for t in (0, 1):
            side = teams[t].get("side")
            other = "away" if side == "home" else "home"
            r = context.team_model_mu(s, teams[t].get("id"), teams[1 - t].get("id"), side == "home",
                                      (context.shape(entry, side) or {}).get("formation"),
                                      (context.shape(entry, other) or {}).get("formation"))
            row.append({"mu": round(r["mu"], 4), "alpha": round(r["alpha"], 5)} if r else None)
        if any(row):
            out[s] = row
    return out


def model_chance(models: dict, stat: str, scope: str, t: int | None, line: float, over: bool,
                 g: dict | None = None) -> tuple[float, float] | None:
    """(chance, expected count) for a line from side_models(), as the page's teamModelChance() works it."""
    sides = models.get(stat)
    if not sides:
        return None
    if scope == "match":
        m = ((g if g is not None else gate()).get("markets") or {}).get(market_key(stat, "match")) or {}
        if not sides[0] or not sides[1] or m.get("alpha_match") is None:
            return None
        mu, alpha = sides[0]["mu"] + sides[1]["mu"], m["alpha_match"]
    else:
        if t is None or not sides[t]:
            return None
        mu, alpha = sides[t]["mu"], sides[t]["alpha"]
    if not mu > 0:
        return None
    return p_line(line, over, mu, alpha), mu
