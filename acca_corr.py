#!/usr/bin/env python3
"""
Do multiples land as often as multiplying their legs says?

    python -B acca_corr.py report     # every table, written to calib/acca_correlation.md
    python -B acca_corr.py report --no-cache    # best_bets.json only, no walk-forward

The page prices a cross-game multiple (tonight.py's ACCA_SHAPES through
weekend.best_acca, and the evens double) by multiplying its legs' fair prices,
which is a claim that the legs are independent. A same-game builder is priced
off how often the legs landed together in the team's own record, and a parlay
off that joint count per side, multiplied across the two sides. Neither claim
had ever been checked against results. This checks both, three ways:

  published   every settled multiple in best_bets.json against the chance the
              site stated for it, split by legs, same or cross game, sport and
              leg type
  pairs       every settled leg the site published, paired with every other
              leg in the same game and on the same night, so the residual
              correlation is measured on thousands of pairs rather than a
              hundred tickets
  walk        a walk forward over every match in cache/: legs priced the way
              the page prices them, from games strictly before kick-off,
              settled on the match itself, months apart so a correction can
              be fitted on the earlier ones and confirmed on the later ones

Correlation is measured against calibrated leg chances, not the stated ones.
A multiple can land more or less often than the product of its stated legs
for two different reasons: the legs themselves are mispriced (a calibration
problem, which compounds through every leg and which learner.py exists to
fix), or the legs move together (correlation, which no single-leg fix can
touch). Recalibrating each leg first, then asking whether the pair landed
together more than the product of those calibrated chances, separates the
two. The residual is what the multi pricing would have to correct.

Intervals. A leg on one night appears in many pairs and many tickets, so
nothing here is independent at the level of the pair or the ticket. Every
interval is a cluster bootstrap by night: whole nights are resampled, which
keeps everything that happened together together.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
BEST = ROOT / "best_bets.json"
CACHE = ROOT / "cache"
OUT = ROOT / "calib" / "acca_correlation.md"
LONDON = ZoneInfo("Europe/London")

MULTI = ("Pick: acca", "Pick: evens double", "Pick: builder", "Pick: parlay")
# Fixed so every number in the write-up reproduces exactly.
SEED = 20261023
BOOT = 2000

# Walk forward. The page's own numbers wherever it has one.
WINDOW = 38            # weekend._sample's games
MIN_VENUE = 6          # weekend.MIN_VENUE
MIN_SAMPLE = 10        # weekend.MIN_SAMPLE
LEG_RANGE = (1.25, 3.0)   # fair prices a multiple is built from
PLAYER_WINDOW = 10     # playerlines: a player's last ten
PLAYER_MIN_APPS = 6
PLAYER_MIN_MINUTES = 45
PLAYER_STATS = {"Shots": "totalShots", "Shots on target": "onTargetScoringAttempt",
                "Fouls": "fouls", "Fouled": "wasFouled", "Tackles": "totalTackle"}
BUILDER_POOL = 6       # weekend.BUILDER_POOL
BUILDER_MIN_JOINT = 5  # weekend.BUILDER_MIN_JOINT
BUILDER_FLOOR = 2.0    # weekend.ODDS_FLOOR
# Earlier months fit, later months confirm. 2026-04-01 leaves both sides of
# the cut with more than a season of football and an NFL season each.
CUT = "2026-04-01"

# Pair classes, finest first. Each is a set of pairs inside one group key and
# not inside the next finer one.
CLASSES = (
    ("same game, same team or player, different stat", "who", "wstat"),
    ("same game, same side, different player or team leg", "side", "who"),
    ("same game, opposite sides", "game", "side"),
    ("cross game, same night", "night", "game"),
)


# ------------------------------------------------------------------ basics

def night_of(ts: float) -> str:
    """The evening a kick-off belongs to, London time.

    Six hours back first, so a 1 a.m. NBA tip-off is the same night as the
    7.45 p.m. football it would share a page with.
    """
    when = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(LONDON) - timedelta(hours=6)
    return when.strftime("%Y-%m-%d")


def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson interval for k of n. (0, 1) when there is nothing to go on."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - spread) / denom), min(1.0, (centre + spread) / denom)


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_logistic(X, y, prior, ridge: float = 1e-3, iters: int = 50) -> np.ndarray:
    """Logistic regression by Newton, ridged towards `prior`.

    The prior is "change nothing" (for a recalibration, a=0 and b=1), so a
    group too thin to say anything comes back close to the identity rather
    than to something extreme.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    prior = np.asarray(prior, dtype=float)
    w = prior.copy()
    for _ in range(iters):
        mu = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (y - mu) - ridge * (w - prior)
        H = (X * (mu * (1 - mu))[:, None]).T @ X + ridge * np.eye(len(w))
        step = np.linalg.solve(H, g)
        w = w + step
        if np.abs(step).max() < 1e-9:
            break
    return w


def fit_recal(p, y) -> tuple[float, float]:
    """Logistic recalibration q = sigmoid(a + b * logit p).

    Two parameters per group, the same shape model.RECORD_CALIBRATION uses,
    so a leg is judged against what legs stated like it actually did.
    """
    x = _logit(p)
    y = np.asarray(y, dtype=float)
    if len(x) < 20 or y.min() == y.max():
        return 0.0, 1.0
    a, b = fit_logistic(np.column_stack([np.ones_like(x), x]), y, [0.0, 1.0])
    return float(a), float(b)


def apply_recal(p, ab) -> np.ndarray:
    a, b = ab
    return 1 / (1 + np.exp(-(a + b * _logit(p))))


def recalibrate(df: pd.DataFrame, train=None, by=("sport", "kind")) -> pd.Series:
    """q for every leg, fitted per group on the training rows only."""
    train = np.ones(len(df), dtype=bool) if train is None else np.asarray(train, dtype=bool)
    p, y = df["p"].to_numpy(dtype=float), df["y"].to_numpy(dtype=float)
    q = np.full(len(df), np.nan)
    for _, rows in df.groupby(list(by)).indices.items():
        fit = rows[train[rows]]
        ab = fit_recal(p[fit], y[fit]) if len(fit) else (0.0, 1.0)
        q[rows] = apply_recal(p[rows], ab)
    return pd.Series(q, index=df.index)


def boot_ratio(num: np.ndarray, den: np.ndarray, seed: int = SEED, b: int = BOOT,
               offset: float = 0.0) -> tuple[float, float, float]:
    """sum(num)/sum(den) - offset with a cluster bootstrap 95% interval.

    num and den hold one entry per cluster (a night), so resampling them
    resamples whole nights.
    """
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    if len(num) == 0 or den.sum() == 0:
        return float("nan"), float("nan"), float("nan")
    point = num.sum() / den.sum() - offset
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(num), size=(b, len(num)))
    n, d = num[idx].sum(axis=1), den[idx].sum(axis=1)
    ok = d > 0
    draws = n[ok] / d[ok] - offset
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(point), float(lo), float(hi)


# ------------------------------------------------------------ the record

def load_best(path: Path | None = None) -> list[dict]:
    path = path or BEST
    return json.loads(path.read_text()) if path.exists() else []


def leg_kind(leg: dict) -> str:
    return "player" if leg.get("player") else "team"


def multiples(items: list[dict]) -> pd.DataFrame:
    """One row per settled published multiple, voids left out.

    A ticket with a void leg is left out rather than repriced: a builder's
    joint count cannot be re-read without the leg, and dropping one leg's
    factor from a product would test a ticket nobody was shown.
    """
    rows = []
    for item in items:
        if item.get("category") not in MULTI or item.get("result") not in ("win", "lose"):
            continue
        legs = item.get("legs") or []
        if any(l.get("result") not in ("win", "lose") for l in legs):
            continue
        if not item.get("fair") or not all(l.get("fair") for l in legs):
            continue
        naive = 1.0
        for l in legs:
            naive /= l["fair"]
        kinds = {leg_kind(l) for l in legs}
        sports = {l.get("sport") or item.get("sport") for l in legs}
        rows.append({
            "category": item["category"].replace("Pick: ", ""),
            "legs": len(legs),
            "game": "same game" if len({l.get("event_id") for l in legs}) == 1 else "cross game",
            "sport": sports.pop() if len(sports) == 1 else "mixed",
            "kind": kinds.pop() if len(kinds) == 1 else "mixed",
            "said": 1 / item["fair"],
            "multiplied": naive,
            "won": 1 if item["result"] == "win" else 0,
            "night": night_of(min(l.get("kickoff") or item["snapshot_at"] for l in legs)),
            "leg_keys": [leg_key(l) for l in legs],
        })
    return pd.DataFrame(rows)


def leg_key(l: dict) -> tuple:
    return (l.get("event_id"), l.get("team"), l.get("player"), l.get("stat"),
            l.get("period"), l.get("line"), bool(l.get("over", True)),
            l.get("threshold"))


def settled_legs(items: list[dict]) -> pd.DataFrame:
    """Every distinct leg the site published and settled, priced as first shown."""
    seen = {}
    for item in sorted(items, key=lambda i: i.get("snapshot_at") or 0):
        for l in item.get("legs") or []:
            if l.get("result") not in ("win", "lose") or not l.get("fair"):
                continue
            key = leg_key(l)
            if key in seen or not (1.0 < l["fair"] < 100):
                continue
            seen[key] = {
                "key": key,
                "night": night_of(l.get("kickoff") or item["snapshot_at"]),
                "game": l.get("event_id"),
                "side": l.get("team") or "?",
                "who": l.get("player") or "TEAM",
                "stat": l.get("stat"),
                "period": l.get("period") or "ALL",
                "sport": l.get("sport") or item.get("sport"),
                "kind": leg_kind(l),
                "p": 1 / l["fair"],
                "y": 1 if l["result"] == "win" else 0,
            }
    df = pd.DataFrame(list(seen.values()))
    if len(df):
        df["wstat"] = df["stat"] + "|" + df["period"]
    return df


# ---------------------------------------------------------------- pairs

GROUP_COLS = {
    "night": ["night"],
    "game": ["night", "game"],
    "side": ["night", "game", "side"],
    "who": ["night", "game", "side", "who"],
    "wstat": ["night", "game", "side", "who", "wstat"],
}


def _sym(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Per night: sums over unordered pairs of legs sharing the group key.

    For any array a, the sum over pairs i<j in one group of a_i*a_j is
    ((sum a)^2 - sum a^2) / 2, so every pair statistic is a groupby away and
    nothing is enumerated.
    """
    cols = GROUP_COLS[level]
    w = df[cols].copy()
    w["one"] = 1.0
    w["y"] = df["y"].astype(float)
    w["p"] = df["p"]
    w["q"] = df["q"]
    w["r"] = df["y"] - df["q"]
    w["s"] = np.sqrt(df["q"] * (1 - df["q"]))
    arrays = ["one", "y", "p", "q", "r", "s"]
    for a in arrays:
        w[a + "2"] = w[a] ** 2
    g = w.groupby(cols)[arrays + [a + "2" for a in arrays]].sum()
    out = pd.DataFrame(index=g.index)
    for a in arrays:
        out[a] = (g[a] ** 2 - g[a + "2"]) / 2
    return out.groupby(level="night").sum()


def pair_sums(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per night and pair class: pairs, both landed, both said, both calibrated."""
    if df.empty:
        return {}
    levels = {lvl: _sym(df, lvl) for lvl in GROUP_COLS}
    out = {}
    for name, coarse, fine in CLASSES:
        diff = levels[coarse].subtract(levels[fine], fill_value=0)
        out[name] = diff.rename(columns={"one": "pairs", "y": "both", "p": "said",
                                         "q": "cal", "r": "resid", "s": "scale"})
    return out


def kind_pairs(df: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame]]:
    """pair_sums split by the two legs' kinds: team-team, player-player, mixed."""
    team = df[df["kind"] == "team"]
    player = df[df["kind"] == "player"]
    whole, tt, pp = pair_sums(df), pair_sums(team), pair_sums(player)
    out = {"team + team": tt, "player + player": pp, "team + player": {}}
    for name in whole:
        mixed = whole[name]
        for part in (tt, pp):
            if name in part:
                mixed = mixed.subtract(part[name], fill_value=0)
        out["team + player"][name] = mixed
    return out


def summarise_pairs(sums: pd.DataFrame, seed: int = SEED) -> dict:
    """One pair class: counts, both-landed against both multiplied, and rho."""
    if sums is None or sums.empty or sums["pairs"].sum() < 1:
        return {}
    n = float(sums["pairs"].sum())
    both = float(sums["both"].sum())
    said = boot_ratio(sums["both"], sums["said"], seed)
    cal = boot_ratio(sums["both"], sums["cal"], seed)
    rho = boot_ratio(sums["resid"], sums["scale"], seed)
    return {"pairs": n, "both": both, "said": float(sums["said"].sum()),
            "cal": float(sums["cal"].sum()), "vs_said": said, "vs_cal": cal,
            "rho": rho, "nights": int((sums["pairs"] > 0).sum())}


# The pair classes the page prices by multiplying. best_acca takes one leg
# per fixture; best_double allows two legs in one fixture only on opposite
# sides. Same-side legs only ever meet in a builder or parlay, which are
# priced off joint counts, not by multiplying.
MULTIPLIED = ("cross game, same night", "same game, opposite sides")


# ------------------------------------------------------------ correction

def corrected_joint(qs: list[float], rho: float) -> float:
    """Chance every leg lands with each pair carrying residual correlation rho.

    Pairwise: P(i and j) = q_i q_j + rho * s_i s_j, s = sqrt(q(1-q)). For
    more legs the pairwise lifts are multiplied on, the usual first-order
    approximation, clipped to a probability and to the smallest leg.
    """
    joint = 1.0
    for q in qs:
        joint *= q
    for a, b in itertools.combinations(qs, 2):
        lift = 1 + rho * math.sqrt((1 - a) * (1 - b) / (a * b))
        joint *= max(lift, 0.0)
    return min(max(joint, 0.0), min(qs) if qs else 1.0)


# ------------------------------------------------------------ walk forward

def _stats_file(eid: int, cache: Path) -> dict | None:
    try:
        return json.loads((cache / f"event_{eid}_statistics.json").read_text())
    except (OSError, ValueError):
        return None


def load_matches(cache: Path = CACHE) -> list[dict]:
    """Every finished match in the cache with full-match statistics, oldest first."""
    import hitrates
    events = {}
    for path in cache.glob("team_*_events_last_*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for e in data.get("events") or []:
            if (e.get("status") or {}).get("type") != "finished" or not e.get("startTimestamp"):
                continue
            home, away = e.get("homeTeam") or {}, e.get("awayTeam") or {}
            if home.get("gender") == "F" or away.get("gender") == "F":
                continue
            events[e["id"]] = e
    out = []
    for eid, e in events.items():
        raw = _stats_file(eid, cache)
        if not raw:
            continue
        stats = hitrates.extract_match_stats(raw).get("ALL")
        if not stats:
            continue
        sport = ((e.get("homeTeam") or {}).get("sport") or {}).get("slug") or "football"
        ut = (e.get("tournament") or {}).get("uniqueTournament") or {}
        out.append({"id": eid, "ts": e["startTimestamp"], "sport": sport,
                    "comp": ut.get("name") or "",
                    "home": e["homeTeam"]["id"], "away": e["awayTeam"]["id"],
                    "home_name": e["homeTeam"].get("name"),
                    "away_name": e["awayTeam"].get("name"),
                    "stats": stats})
    out.sort(key=lambda m: (m["ts"], m["id"]))
    return out


def _price(line, over, values, hits, sport):
    import model
    got = model.price(line, over, None, values, hits, len(values), sport=sport)
    return got["p"]


def _team_sample(history, venue):
    recent = history[-WINDOW:]
    same = [h for h in recent if h["venue"] == venue]
    return same if len(same) >= MIN_VENUE else recent


def team_legs(matches: list[dict]) -> tuple[list[dict], list[dict]]:
    """Team legs and same-team builders, each priced from games before kick-off.

    Legs: one per team per stat the competition's board sells, at the
    fixture's shared line (hitrates.suggest_lines: the median of both sides'
    recent games, rounded, minus a half), in whichever direction the side's
    own sample favours, priced by model.price on the record exactly as a team
    leg without a projection is. Builders: from each side's six
    best-evidenced legs, every three-leg combination priced off the joint
    count in the same sample, and the one weekend.py would have shown (the
    best Wilson lower bound).
    """
    import markets
    import model
    history: dict[int, list[dict]] = defaultdict(list)
    legs, builders = [], []
    for m in matches:
        sellable = markets.stats_for_competition(m["sport"], m["comp"])
        night = night_of(m["ts"])
        sides = ((m["home"], "home"), (m["away"], "away"))
        samples = [_team_sample(history[tid], venue) for tid, venue in sides]
        recent = [history[tid][-WINDOW:] for tid, _ in sides]
        for idx, (tid, venue) in enumerate(sides):
            sample = samples[idx]
            if len(sample) < MIN_SAMPLE:
                continue
            side_legs = []
            for stat, pair in m["stats"].items():
                if stat not in sellable:
                    continue
                values = [h["stats"][stat] for h in sample if stat in h["stats"]]
                if len(values) < MIN_SAMPLE:
                    continue
                both = [h["stats"][stat] for r in recent for h in r if stat in h["stats"]]
                line = max(0.5, round(float(np.median(both))) - 0.5)
                over_hits = sum(1 for v in values if v > line)
                over = over_hits * 2 >= len(values)
                hits = over_hits if over else len(values) - over_hits
                if hits == 0:
                    continue
                try:
                    p = _price(line, over, values, hits, m["sport"])
                except Exception:
                    continue
                if not p or not (0.05 < p < 0.99):
                    continue
                truth = pair[idx]
                leg = {"night": night, "ts": m["ts"], "game": m["id"],
                       "side": f"{m['id']}:{idx}", "who": "TEAM", "stat": stat,
                       "wstat": stat + "|ALL", "sport": m["sport"], "kind": "team",
                       "p": p, "y": 1 if (truth > line) == over else 0,
                       "line": line, "over": over, "hits": hits, "total": len(values)}
                legs.append(leg)
                side_legs.append((leg, [h["stats"].get(stat) for h in sample]))
            builders.extend(_builders(side_legs, m, idx, night, model))
        for idx, (tid, venue) in enumerate(sides):
            own = {k: v[idx] for k, v in m["stats"].items()}
            history[tid].append({"venue": venue, "stats": own})
    return legs, builders


def priced_in_range(df: pd.DataFrame) -> pd.DataFrame:
    """Legs at a price a multiple is actually built from."""
    fair = 1 / df["p"]
    return df[(fair >= LEG_RANGE[0]) & (fair <= LEG_RANGE[1])]


def _builders(side_legs, m, idx, night, model) -> list[dict]:
    pool = sorted(side_legs, key=lambda lv: -model.wilson_low(lv[0]["hits"], lv[0]["total"]))
    pool = pool[:BUILDER_POOL]
    found = []
    for combo in itertools.combinations(pool, 3):
        hits = total = 0
        for row in zip(*[vals for _, vals in combo]):
            if any(v is None for v in row):
                continue
            total += 1
            if all((v > l["line"]) == l["over"] for v, (l, _) in zip(row, combo)):
                hits += 1
        if total < MIN_SAMPLE or hits < BUILDER_MIN_JOINT or total / hits < BUILDER_FLOOR:
            continue
        naive = 1.0
        for l, _ in combo:
            naive *= l["p"]
        found.append({"night": night, "ts": m["ts"], "game": m["id"], "sport": m["sport"],
                      "side": f"{m['id']}:{idx}", "said": hits / total, "multiplied": naive,
                      "qs": [l["p"] for l, _ in combo],
                      "won": int(all(l["y"] for l, _ in combo)),
                      "evidence": model.wilson_low(hits, total)})
    if found:
        best = max(found, key=lambda b: (b["evidence"], 1 / b["said"]))
        for b in found:
            b["shown"] = b is best
    return found


def player_legs(matches: list[dict], cache: Path = CACHE) -> list[dict]:
    """Football player legs off each player's last ten appearances.

    One leg per player and stat: the rung (1+ or 2+) whose record is nearest
    65%, parlay.LEG_FLOOR, priced at the smoothed record. Only players who
    appear are settled, which is a bookmaker's void rule, and only appearances
    of 45 minutes or more count towards the record, the page's own bar.
    """
    import model
    history: dict[int, list[dict]] = defaultdict(list)
    out = []
    for m in matches:
        if m["sport"] != "football":
            continue
        try:
            lineups = json.loads((cache / f"event_{m['id']}_lineups.json").read_text())
        except (OSError, ValueError):
            continue
        night = night_of(m["ts"])
        played = []
        for idx, key in enumerate(("home", "away")):
            for pl in (lineups.get(key) or {}).get("players") or []:
                pid = (pl.get("player") or {}).get("id")
                st = pl.get("statistics") or {}
                mins = st.get("minutesPlayed") or 0
                if not pid or mins <= 0 or pl.get("position") == "G":
                    continue
                played.append((idx, pid, mins, st))
        for idx, pid, mins, st in played:
            past = history[pid][-PLAYER_WINDOW:]
            if len(past) >= PLAYER_MIN_APPS and not pl_is_sub(st):
                for stat, src in PLAYER_STATS.items():
                    values = [h.get(src) or 0 for h in past]
                    best = None
                    for line in (0.5, 1.5):
                        hits = sum(1 for v in values if v > line)
                        p = model.smooth_rate(hits, len(values))
                        if best is None or abs(p - 0.65) < abs(best[1] - 0.65):
                            best = (line, p)
                    line, p = best
                    if not (LEG_RANGE[0] <= 1 / p <= LEG_RANGE[1]):
                        continue
                    out.append({"night": night, "ts": m["ts"], "game": m["id"],
                                "side": f"{m['id']}:{idx}", "who": str(pid), "stat": stat,
                                "wstat": stat + "|ALL", "sport": "football", "kind": "player",
                                "p": p, "y": 1 if (st.get(src) or 0) > line else 0})
        for idx, pid, mins, st in played:
            if mins >= PLAYER_MIN_MINUTES:
                history[pid].append({src: st.get(src) or 0 for src in PLAYER_STATS.values()})
    return out


def pl_is_sub(st: dict) -> bool:
    """A substitute's few minutes are not the line the record was built on.

    The page prices starters; a sub who came on for ten minutes would be
    settled on a different bet. Under 45 minutes counts as not the bet, the
    same bar the record uses.
    """
    return (st.get("minutesPlayed") or 0) < PLAYER_MIN_MINUTES


def synthetic_accas(df: pd.DataFrame, sizes=(2, 3, 4, 5), per_night: int = 40,
                    seed: int = SEED) -> pd.DataFrame:
    """Cross-game tickets drawn at random from each night's legs, one per game."""
    rng = random.Random(seed)
    rows = []
    for night, legs in df.groupby("night"):
        games = list(legs.groupby("game").indices.values())
        if len(games) < 2:
            continue
        p, q, y = legs["p"].to_numpy(), legs["q"].to_numpy(), legs["y"].to_numpy()
        for k in sizes:
            if len(games) < k:
                continue
            for _ in range(per_night):
                picks = [int(rng.choice(list(g))) for g in rng.sample(games, k)]
                rows.append({"night": night, "legs": k,
                             "said": float(np.prod(p[picks])),
                             "cal": float(np.prod(q[picks])),
                             "qs": [float(q[i]) for i in picks],
                             "won": int(all(y[picks]))})
    return pd.DataFrame(rows)


# ------------------------------------------------------------- lead log

LEAD_LOG = ROOT / "lead_log.json"
LEAD_KEY = ("event_id", "team", "player", "stat", "period", "line", "over")


def lead_legs(items: list[dict], log: dict) -> pd.DataFrame:
    """tonight.py's one lead per game, settled the way its results block does.

    The leads on one night are the page's own cross-game shortlist, so their
    pairs are the closest thing in the record to the acca a reader builds by
    hand from the page. The chance is the one the page printed.
    """
    settled = {}
    for item in items:
        for l in item.get("legs") or []:
            if l.get("result") in ("win", "lose"):
                settled[tuple(l.get(k) for k in LEAD_KEY)] = l["result"]
    rows = []
    for r in log.values():
        res = settled.get(tuple(r.get(k) for k in LEAD_KEY))
        if not res or not r.get("chance"):
            continue
        rows.append({"night": night_of(r["kickoff"]), "game": r["event_id"],
                     "side": r.get("team") or "?", "who": r.get("player") or "TEAM",
                     "stat": r.get("stat"), "wstat": f"{r.get('stat')}|{r.get('period')}",
                     "sport": "all", "kind": "player" if r.get("player") else "team",
                     "p": r["chance"], "q": r["chance"], "y": 1 if res == "win" else 0})
    return pd.DataFrame(rows)


# ------------------------------------------------------- builder check

BUILDER_PRIOR = (0.0, 1.0, 0.0)


def builder_features(said, multiplied) -> np.ndarray:
    """Intercept, the joint count's logit and the multiplied legs' logit."""
    said, multiplied = np.asarray(said, dtype=float), np.asarray(multiplied, dtype=float)
    return np.column_stack([np.ones_like(said), _logit(said), _logit(multiplied)])


def fit_builder(df: pd.DataFrame) -> np.ndarray:
    """A builder's chance from its joint count, pulled towards its legs' product.

    logit P = a + b logit(joint) + c logit(product of legs). The prior is
    the page as it stands (a=0, b=1, c=0): the joint count, untouched.
    """
    return fit_logistic(builder_features(df["said"], df["multiplied"]),
                        df["won"], BUILDER_PRIOR)


def builder_chance(w, said, multiplied) -> np.ndarray:
    return 1 / (1 + np.exp(-(builder_features(said, multiplied) @ np.asarray(w))))


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def builder_check(walk_builders: pd.DataFrame, published: pd.DataFrame, cut: str):
    """Fit the builder correction on earlier months, test it twice.

    Once on the walk forward's later months, once on the builders the site
    actually published. It only holds if it improves both: the walk forward
    rebuilds a builder from record-only legs, the page's legs also carry
    team strength and come from its own line ladder, so a correction that
    helps the copy and hurts the original is a fact about the copy.
    """
    shown = walk_builders[walk_builders["shown"]]
    train, test = shown[shown["night"] < cut], shown[shown["night"] >= cut]
    w = fit_builder(train)
    rows = []
    for label, df in (("walk forward, later months", test), ("published builders", published)):
        if df.empty:
            continue
        corr = builder_chance(w, df["said"], df["multiplied"])
        per = df.assign(corr=corr).groupby("night")[["won", "said", "corr"]].sum()
        rows.append({"set": label, "tickets": len(df), "landed": float(df["won"].mean()),
                     "said": float(df["said"].mean()), "corrected": float(corr.mean()),
                     "vs_said": boot_ratio(per["won"], per["said"]),
                     "vs_corrected": boot_ratio(per["won"], per["corr"]),
                     "ll_said": log_loss(df["said"], df["won"]),
                     "ll_corrected": log_loss(corr, df["won"])})
    holds = len(rows) == 2 and all(r["ll_corrected"] < r["ll_said"] for r in rows)
    return w, rows, holds


# --------------------------------------------------------------- tables

def _pct(x):
    return "n/a" if x is None or not np.isfinite(x) else f"{x * 100:.1f}%"


def _ratio(t):
    point, lo, hi = t
    if not np.isfinite(point):
        return "n/a"
    return f"{point:.2f} ({lo:.2f} to {hi:.2f})"


def _rho(t):
    point, lo, hi = t
    if not np.isfinite(point):
        return "n/a"
    return f"{point:+.3f} ({lo:+.3f} to {hi:+.3f})"


def ticket_table(df: pd.DataFrame, by: list[str], said_col="said", extra=None) -> list[str]:
    """Landed against said, per group, Wilson on the rate and a by-night
    bootstrap on landed / said."""
    head = "| " + " | ".join(by) + " | tickets | landed | rate (95% Wilson) | said | landed / said (95% by night) |"
    cols = ["multiplied"] if extra else []
    if extra:
        head += " multiplied | landed / multiplied |"
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for key, g in df.groupby(by):
        key = key if isinstance(key, tuple) else (key,)
        n, k = len(g), int(g["won"].sum())
        lo, hi = wilson(k, n)
        per = g.groupby("night")[["won", said_col] + cols].sum()
        row = (f"| {' | '.join(str(x) for x in key)} | {n} | {k} | "
               f"{_pct(k / n)} ({_pct(lo)} to {_pct(hi)}) | {_pct(g[said_col].mean())} | "
               f"{_ratio(boot_ratio(per['won'], per[said_col]))} |")
        if extra:
            row += (f" {_pct(g['multiplied'].mean())} | "
                    f"{_ratio(boot_ratio(per['won'], per['multiplied']))} |")
        lines.append(row)
    return lines


def pair_table(groups: dict[str, dict[str, pd.DataFrame]]) -> list[str]:
    head = ("| split | pair class | pairs | nights | both landed | both said | both calibrated | "
            "landed / said | landed / calibrated | residual rho |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for split, classes in groups.items():
        for name, _, _ in CLASSES:
            s = summarise_pairs(classes.get(name))
            if not s or s["pairs"] < 30 or s["nights"] < 3:
                continue
            lines.append(f"| {split} | {name} | {s['pairs']:.0f} | {s['nights']} | {s['both']:.0f} | "
                         f"{s['said']:.0f} | {s['cal']:.0f} | {_ratio(s['vs_said'])} | "
                         f"{_ratio(s['vs_cal'])} | {_rho(s['rho'])} |")
    return lines


def leg_table(df: pd.DataFrame, by: list[str]) -> list[str]:
    head = "| " + " | ".join(by) + " | legs | landed | rate (95% Wilson) | said | landed / said (95% by night) |"
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for key, g in df.groupby(by):
        key = key if isinstance(key, tuple) else (key,)
        n, k = len(g), int(g["y"].sum())
        lo, hi = wilson(k, n)
        per = g.groupby("night")[["y", "p"]].sum()
        lines.append(f"| {' | '.join(str(x) for x in key)} | {n} | {k} | {_pct(k / n)} "
                     f"({_pct(lo)} to {_pct(hi)}) | {_pct(g['p'].mean())} | "
                     f"{_ratio(boot_ratio(per['y'], per['p']))} |")
    return lines


def splits(df: pd.DataFrame, cols=("sport",)) -> dict[str, dict]:
    out = {"all": kind_pairs(df)}
    for col in cols:
        for value, g in df.groupby(col):
            out[f"{col} = {value}"] = {"all kinds": pair_sums(g)}
    return out


def flatten(groups: dict) -> dict[str, dict[str, pd.DataFrame]]:
    flat = {}
    for split, inner in groups.items():
        for kinds, classes in inner.items():
            label = split if kinds == "all kinds" else f"{split}, {kinds}"
            if split == "all":
                label = kinds
            flat[label] = classes
    return flat


# ----------------------------------------------------------- the report

def month(night: str) -> str:
    return night[:7]


def fit_and_confirm(df: pd.DataFrame, cut: str) -> tuple[list[str], dict]:
    """rho per pair class on nights before `cut`, judged on the nights after.

    q is refitted on the training nights only, so the test months see
    nothing of themselves. A correction holds if, out of sample, the
    corrected joint chance sits nearer what landed than the plain product of
    calibrated legs, and the plain product is off by more than its interval.
    """
    train = (df["night"] < cut).to_numpy()
    work = df.copy()
    work["q"] = recalibrate(work, train)
    tr, te = work[train], work[~train]
    sums_tr, sums_te = pair_sums(tr), pair_sums(te)
    head = ("| pair class | multiplied by the page | rho fitted (earlier) | pairs (later) | "
            "landed / calibrated (later) | landed / corrected (later) | holds |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    fitted = {}
    for name, _, _ in CLASSES:
        a, b = summarise_pairs(sums_tr.get(name)), sums_te.get(name)
        if not a or b is None or b.empty:
            continue
        rho = a["rho"][0]
        plain = boot_ratio(b["both"], b["cal"])
        corr = boot_ratio(b["both"], b["cal"] + rho * b["scale"])
        holds = (not (a["rho"][1] <= 0 <= a["rho"][2])
                 and not (plain[1] <= 1 <= plain[2])
                 and abs(corr[0] - 1) < abs(plain[0] - 1))
        fitted[name] = {"rho": rho, "ci": (a["rho"][1], a["rho"][2]), "holds": holds,
                        "plain": plain, "corrected": corr}
        lines.append(f"| {name} | {'yes' if name in MULTIPLIED else 'no'} | {_rho(a['rho'])} | "
                     f"{b['pairs'].sum():.0f} | {_ratio(plain)} | "
                     f"{_ratio(corr)} | {'yes' if holds else 'no'} |")
    return lines, fitted


def report(use_cache: bool = True) -> str:
    items = load_best()
    out = ["# Acca correlation: generated tables", "",
           f"Generated by `python -B acca_corr.py report` on "
           f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Bootstrap intervals resample "
           f"whole nights, {BOOT} draws, seed {SEED}.", ""]

    # 1. published multiples
    multi = multiples(items)
    out += ["## 1. Published multiples", "",
            f"{len(multi)} settled multiples with no void leg, "
            f"{multi['night'].nunique() if len(multi) else 0} nights. 'said' is the chance the "
            f"site stated (one over its fair price); 'multiplied' is the product of the legs' "
            f"own chances, which for an acca or double is the same number.", ""]
    if len(multi):
        for by in (["category", "legs", "game"], ["legs"], ["game"], ["sport"], ["kind"]):
            out += [f"### By {', '.join(by)}", ""] + ticket_table(multi, by, extra=True) + [""]

    # 2. legs, and the multiples against calibrated legs
    legs = settled_legs(items)
    out += ["## 2. Published legs", "",
            f"{len(legs)} distinct settled legs, each priced at its first sighting.", ""]
    if len(legs):
        legs["q"] = recalibrate(legs)
        out += leg_table(legs, ["sport", "kind"]) + [""]
        cal = dict(zip(legs["key"], legs["q"]))
        if len(multi):
            multi["cal"] = [float(np.prod([cal.get(k, np.nan) for k in ks]))
                            for ks in multi["leg_keys"]]
            cross = multi[(multi["game"] == "cross game") & multi["cal"].notna()]
            out += ["### Cross-game multiples against calibrated legs", "",
                    "The same tickets, 'said' now the product of each leg recalibrated on "
                    "every published leg of its sport and kind. What is left is correlation "
                    "and noise.", ""]
            if len(cross):
                out += ticket_table(cross, ["category", "legs"], said_col="cal") + [""]
        out += ["## 3. Pairs from the published legs", ""]
        out += pair_table(flatten(splits(legs, ("sport",)))) + [""]

    try:
        log = json.loads(LEAD_LOG.read_text())
    except (OSError, ValueError):
        log = {}
    leads = lead_legs(items, log)
    if len(leads):
        n, k = len(leads), int(leads["y"].sum())
        lo, hi = wilson(k, n)
        out += ["### tonight.py's leads", "",
                f"{n} settled leads over {leads['night'].nunique()} night(s): {k} landed "
                f"({_pct(k / n)}, {_pct(lo)} to {_pct(hi)}), the page said {_pct(leads['p'].mean())}. "
                "Cross-game pairs among them, against the page's own chances:", ""]
        s = summarise_pairs(pair_sums(leads).get("cross game, same night"))
        if s:
            spread = (_ratio(s["vs_said"]) if s["nights"] >= 3 else
                      f"{s['vs_said'][0]:.2f}, too few nights for an interval")
            out += [f"{s['pairs']:.0f} pairs, {s['both']:.0f} both landed against {s['said']:.0f} "
                    f"multiplied: {spread}. The log was started on 21 October 2026, so it "
                    "holds very few settled nights so far.", ""]

    if not use_cache:
        return "\n".join(out) + "\n"

    # 4. walk forward
    matches = load_matches()
    tl, builders = team_legs(matches)
    pl = player_legs(matches)
    walk = priced_in_range(pd.DataFrame(tl + pl)).reset_index(drop=True)
    walk["q"] = recalibrate(walk)
    walk["month"] = walk["night"].map(month)
    out += ["## 4. Walk forward over the cache", "",
            f"{len(matches)} matches, {len(tl)} team legs and {len(pl)} football player legs, "
            f"{len(walk)} of them priced {LEG_RANGE[0]} to {LEG_RANGE[1]} (the range used for "
            f"legs and pairs below), {walk['night'].nunique()} nights, "
            f"{walk['night'].min()} to {walk['night'].max()}.", ""]
    out += ["### Legs", ""] + leg_table(walk, ["sport", "kind"]) + [""]
    out += ["### Pairs", ""] + pair_table(flatten(splits(walk, ("sport",)))) + [""]

    football = walk[(walk["sport"] == "football") & (walk["kind"] == "team")]
    out += ["### Football team legs by stat pair, same team", "",
            "The twenty most common pairs. Builders are made of these.", ""]
    out += stat_pair_table(football) + [""]

    acc = synthetic_accas(walk[walk["kind"] == "team"])
    out += ["### Random cross-game tickets, team legs, one leg per game", "",
            "Forty tickets a night at each size, drawn with a fixed seed. First against the "
            "product of the legs' own prices, then against the product of calibrated legs, "
            "which leaves only correlation.", ""]
    out += ticket_table(acc, ["legs"]) + [""]
    out += ticket_table(acc, ["legs"], said_col="cal") + [""]

    b = pd.DataFrame(builders)
    if len(b):
        b["kind"] = np.where(b["shown"], "shown", "every combination")
        out += ["### Same-team builders priced by co-occurrence", "",
                "Every qualifying three-leg combination, and the one weekend.py would have "
                "shown per side ('shown'). 'said' is the joint count in the sample; "
                "'multiplied' is the product of the three legs.", ""]
        out += ticket_table(b, ["sport", "kind"], extra=True) + [""]

    # 5. fit on earlier months, confirm on later
    cut = CUT
    lines, fitted = fit_and_confirm(walk, cut)
    out += [f"## 5. Corrections fitted before {cut}, confirmed after", "",
            "### Residual correlation by pair class", "",
            "rho fitted on nights before the cut, leg calibration refitted on those nights "
            "only, then applied to the later nights.", ""]
    out += lines + [""]
    train = (walk["night"] < cut).to_numpy()
    w2 = walk.copy()
    w2["q"] = recalibrate(w2, train)
    later = synthetic_accas(w2[(~train) & (w2["kind"] == "team").to_numpy()])
    rho = fitted.get("cross game, same night", {}).get("rho", 0.0)
    later["corrected"] = [corrected_joint(qs, rho) for qs in later["qs"]]
    out += ["Later-month random cross-game tickets, against the calibrated product and then "
            f"with the fitted cross-game rho ({rho:+.4f}) applied:", ""]
    out += ticket_table(later, ["legs"], said_col="cal") + [""]
    out += ticket_table(later, ["legs"], said_col="corrected") + [""]

    if len(b):
        pub = multi[multi["category"] == "builder"] if len(multi) else pd.DataFrame()
        w, rows, holds = builder_check(b, pub, cut)
        out += ["### Builder correction", "",
                "logit P = a + b logit(joint count) + c logit(product of legs), fitted on the "
                f"walk forward's shown builders before the cut: a={w[0]:+.3f}, b={w[1]:.3f}, "
                f"c={w[2]:.3f}. Holds only if it beats the joint count on both test sets.", ""]
        out += ["| test set | tickets | landed | said | corrected | landed / said | "
                "landed / corrected | log loss said | log loss corrected |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| {r['set']} | {r['tickets']} | {_pct(r['landed'])} | {_pct(r['said'])} | "
                       f"{_pct(r['corrected'])} | {_ratio(r['vs_said'])} | "
                       f"{_ratio(r['vs_corrected'])} | {r['ll_said']:.4f} | {r['ll_corrected']:.4f} |")
        out += ["", f"Holds: {'yes' if holds else 'no'}.", ""]

    out += ["### Cross-game pairs by month", "",
            "| month | pairs | landed / calibrated | residual rho |", "|---|---|---|---|"]
    for mth, g in walk.groupby("month"):
        s = summarise_pairs(pair_sums(g).get("cross game, same night"))
        if s and s["pairs"] >= 1000:
            out.append(f"| {mth} | {s['pairs']:.0f} | {_ratio(s['vs_cal'])} | {_rho(s['rho'])} |")
    out += [""]
    return "\n".join(out) + "\n"


def stat_pair_table(df: pd.DataFrame, top: int = 20) -> list[str]:
    """Same-team pairs by the two stats, the biggest classes first."""
    rows = []
    for (game, side), g in df.groupby(["game", "side"]):
        recs = g[["stat", "y", "q"]].to_numpy()
        for (s1, y1, q1), (s2, y2, q2) in itertools.combinations(recs, 2):
            a, b = sorted((s1, s2))
            rows.append((a + " + " + b, g["night"].iat[0], y1 * y2, q1 * q2,
                         (y1 - q1) * (y2 - q2), math.sqrt(q1 * (1 - q1) * q2 * (1 - q2))))
    if not rows:
        return []
    pr = pd.DataFrame(rows, columns=["pair", "night", "both", "cal", "resid", "scale"])
    head = "| stats | pairs | landed / calibrated | residual rho |"
    lines = [head, "|---|---|---|---|"]
    for name, g in sorted(pr.groupby("pair"), key=lambda kv: -len(kv[1]))[:top]:
        per = g.groupby("night")[["both", "cal", "resid", "scale"]].sum()
        lines.append(f"| {name} | {len(g)} | {_ratio(boot_ratio(per['both'], per['cal']))} | "
                     f"{_rho(boot_ratio(per['resid'], per['scale']))} |")
    return lines


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["report"])
    ap.add_argument("--no-cache", action="store_true", help="best_bets.json only")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    text = report(use_cache=not args.no_cache)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
