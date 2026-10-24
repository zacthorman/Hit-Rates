#!/usr/bin/env python3
"""NBA player lines: are they calibrated, and does an early-season shrink help?

    python -B nba_check.py committed            # the basketball evidence in the repo (runs anywhere)
    python -B nba_check.py cache [--cache DIR]  # the NBA box scores in cache/ (the Mac)
    python -B nba_check.py pplog                # Paddy Power's settled basketball lines (the Mac)

How a basketball player line is priced (report.py's pricePlayer, mirrored by
model.price_player): his last ten appearances of 12 minutes or more, his rate
per minute times his median minutes in them, a count distribution around
that, then calibrate_player(), which for basketball falls back to football's
constants (PLAYER_CALIBRATION_BY_SPORT is empty since 21 Oct). Where
usmodel_live.py has a number the page uses the US model, alone or blended,
instead. The page never calls a basketball line Take on stale data (no game
for 60 days) or at an edge over 30%.

The worry. On opening night (20 Oct 2026) every record was last season's,
weighted to play-off minutes, and the model called 116 of 561 Paddy Power
lines take. A record of few games, or of games from another season, says
less than ten fresh ones. The test: on games the fit never saw, do such
records land below their stated chance, and does shrinking them help?

Two shrinks are tried, both fixed on earlier games and scored on later ones:

  rate     his rate per minute pulled towards his position's rate per
           minute (G, F, C) on the earlier games, with weight
           m / (m + K), m his minutes in the record. K is chosen on the
           earlier games from a fixed grid. Then priced as the page prices.
  logit    the page's chance pulled towards the stat's base rate at that
           rung on the earlier games, in log-odds: b * logit(p) + (1 - b) *
           logit(base), b fitted on the earlier games for each record
           group (how many of his ten games are from this season).

The rule, fixed before any number was seen: live pricing changes only if a
shrink beats the page's own price on the later games on log loss with the
95% interval of the difference wholly below zero, both on all lines and on
the early-season lines, and does not make any record group worse with an
interval wholly above zero. The cache in this repository has no NBA box
scores, so `cache` can only run on the Mac; until it has, nothing changes.

Every interval is 95%. Rates use Wilson; differences and ratios resample
whole games (BOOT draws), because the lines of one game are not independent.
"""
from __future__ import annotations

import argparse
import collections
import glob
import html
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEST_BETS = ROOT / "best_bets.json"
PP_RESULTS = ROOT / "pp-results.html"
CACHE = ROOT / "cache"
OUT = CACHE / "nba_check.json"     # cache/ is gitignored: the fit never lands in a tracked file
BOOT = 2000
SEED = 20261024
Z = 1.959964

STATS = ("Points", "Rebounds", "Assists", "Three pointers made", "Steals", "Blocks", "Turnovers",
         "Points rebounds and assists", "Points and rebounds", "Points and assists", "Rebounds and assists")
MIN_MIN = 12              # model.MIN_MINUTES_BY_SPORT["basketball"]
WINDOW = 10               # the page's last ten
LADDER = (0.75, 1.0, 1.25)  # rungs around his last-ten median, as usmodel/training does
K_GRID = (0, 30, 60, 120, 240, 480, 960)
GROUPS = ("0-2 this season", "3-5 this season", "6-9 this season", "10 this season")
EARLY_DAYS = 21           # the first three weeks of a season are "early"


# ------------------------------------------------------------------ intervals

def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def boot_ratio(sums: list[tuple[float, float]], n: int | None = None, seed: int = SEED) -> tuple[float, float]:
    """95% interval of sum(num) / sum(den), resampling whole groups.

    sums holds one (num, den) per group (a game), so the cost is draws x
    games, not draws x lines: the Mac's cache has hundreds of thousands of lines."""
    n = BOOT if n is None else n
    if not sums:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    k = len(sums)
    vals = []
    for _ in range(n):
        a = b = 0.0
        for _i in range(k):
            x, y = sums[rng.randrange(k)]
            a += x
            b += y
        if b:
            vals.append(a / b)
    vals.sort()
    if not vals:
        return (float("nan"), float("nan"))
    return vals[int(0.025 * (len(vals) - 1))], vals[int(math.ceil(0.975 * (len(vals) - 1)))]


def _by(rows: list[dict], group: str, num) -> list[tuple[float, float]]:
    acc = collections.defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        a = acc[r[group]]
        a[0] += num(r)
        a[1] += 1
    return [tuple(v) for v in acc.values()]


def _ll1(r: dict, key: str) -> float:
    p = _clip(r[key])
    return -math.log(p) if r["y"] else -math.log(1 - p)


def _clip(p: float) -> float:
    return min(1 - 1e-4, max(1e-4, p))


def logloss(rows, key="p") -> float | None:
    if not rows:
        return None
    return -sum(math.log(_clip(r[key])) if r["y"] else math.log(1 - _clip(r[key])) for r in rows) / len(rows)


def calib(rows: list[dict], group="game", key="p") -> dict:
    """n, games, said, got (Wilson), got - said (by game)."""
    n = len(rows)
    if not n:
        return {"n": 0}
    k = sum(r["y"] for r in rows)
    sums = _by(rows, group, lambda r: r["y"] - r[key])
    said = sum(r[key] for r in rows) / n
    return {"n": n, "games": len(sums), "said": said, "got": k / n, "got_ci": wilson(k, n),
            "gap": k / n - said, "gap_ci": boot_ratio(sums)}


def loss_diff(rows: list[dict], a: str, b: str, group="game") -> dict:
    """Mean log loss of b minus a, with its 95% interval by game. Negative: b better."""
    la, lb = logloss(rows, a), logloss(rows, b)
    sums = _by(rows, group, lambda r: _ll1(r, b) - _ll1(r, a))
    return {"n": len(rows), "a": la, "b": lb, "diff": lb - la if rows else None, "ci": boot_ratio(sums)}


def pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def ci(c, d=1, sign=False):
    if not c or any(isinstance(v, float) and math.isnan(v) for v in c):
        return "-"
    return f"{pct(c[0], d, sign)} to {pct(c[1], d, sign)}"


def calib_row(label: str, s: dict) -> str | None:
    """One table row, or None for a group with no lines (render() leaves it out)."""
    if not s.get("n"):
        return None
    return (f"| {label} | {s['n']} | {s['games']} | {pct(s['said'])} | {pct(s['got'])} ({ci(s['got_ci'])}) | "
            f"{pct(s['gap'], sign=True)} ({ci(s['gap_ci'], sign=True)}) |")


CALIB_HEAD = ["| Group | Lines | Games | Said | Got (95%) | Got - said (95%, by game) |", "|---|---|---|---|---|---|"]


# ------------------------------------------------------------------ 1. committed evidence

def best_bets_rows(path: Path = BEST_BETS) -> list[dict]:
    """Settled basketball player legs from best_bets.json, each line once, at its first published chance."""
    try:
        bets = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    seen = {}
    for b in bets:
        for l in b.get("legs") or []:
            if l.get("sport") != "basketball" or not l.get("player") or l.get("result") not in ("win", "lose"):
                continue
            p = l.get("chance") or (1 / l["fair"] if l.get("fair") else None)
            if not p:
                continue
            key = (l["event_id"], l["player"], l["stat"], l["line"], bool(l["over"]))
            if key in seen:
                continue
            seen[key] = {"game": l["event_id"], "night": time.strftime("%d %b", time.gmtime(l["kickoff"] - 8 * 3600)),
                         "ts": l["kickoff"], "stat": l["stat"], "line": l["line"], "over": bool(l["over"]),
                         "alt": bool(l.get("alt")), "p": float(p), "y": int(l["result"] == "win"),
                         "record": (l.get("hits"), l.get("total")), "category": b.get("category")}
    return list(seen.values())


_TAG = re.compile(r"<[^>]+>")


def _cells(row_html: str) -> list[str]:
    return [html.unescape(_TAG.sub("", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]


def pp_results(path: Path = PP_RESULTS) -> dict:
    """Basketball rows of the committed pp-results.html: value bets by market, and recent value bets."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {"by_market": [], "recent": [], "updated": None}
    sections = dict((h, body) for h, body in re.findall(r"<h2>(.*?)</h2>(.*?)(?=<h2>|</main>)", text, re.S))
    by_market = []
    for r in re.findall(r"<tr>(.*?)</tr>", sections.get("Value bets by market", ""), re.S):
        c = _cells(r)
        if len(c) >= 6 and c[0].startswith("basketball"):
            n = int(c[1])
            by_market.append({"market": c[0].split("·", 1)[1].strip(), "n": n,
                              "won": round(float(c[2].rstrip("%")) / 100 * n),
                              "said": float(c[3].rstrip("%")) / 100,
                              "profit": float(c[4].rstrip("u").replace("+", ""))})
    stats = "|".join(re.escape(s) for s in sorted(STATS, key=len, reverse=True))
    recent = []
    for r in re.findall(r"<tr>(.*?)</tr>", sections.get("Recent value bets", ""), re.S):
        c = _cells(r)
        if len(c) < 8:
            continue
        m = re.match(rf"^({stats}) (Over|Under) ([\d.]+)$", c[2])
        res = re.match(r"^(win|lose)", c[7])
        if not m or not res:
            continue
        k10 = re.search(r"(\d+)/(\d+)\s*·\s*(\d+)/(\d+)", c[3])
        recent.append({"stat": m.group(1), "over": m.group(2) == "Over", "line": float(m.group(3)),
                       "p": float(c[4].rstrip("%")) / 100, "price": float(c[5]), "y": int(res.group(1) == "win"),
                       "game": c[1].split("\n")[-1].strip() or c[1], "player": c[1],
                       "k5": (int(k10.group(1)), int(k10.group(2))) if k10 else None,
                       "k10": (int(k10.group(3)), int(k10.group(4))) if k10 else None})
    m = re.search(r"Updated ([^<.]+)", text)
    return {"by_market": by_market, "recent": recent, "updated": m.group(1).strip() if m else None}


def shrink_fit(rows: list[dict], key="p") -> float:
    """b in logit(p') = b * logit(p) + (1 - b) * logit(base), base the rows' own landed rate; grid, least log loss."""
    base = _clip(sum(r["y"] for r in rows) / len(rows))
    lb = math.log(base / (1 - base))
    best = (None, 1.0)
    for i in range(0, 41):
        b = i / 40 * 1.5
        ll = 0.0
        for r in rows:
            p = _clip(r[key])
            z = b * math.log(p / (1 - p)) + (1 - b) * lb
            q = 1 / (1 + math.exp(-z))
            ll -= math.log(q) if r["y"] else math.log(1 - q)
        if best[0] is None or ll < best[0]:
            best = (ll, b)
    return best[1], base


def apply_logit(p: float, b: float, base: float) -> float:
    p, base = _clip(p), _clip(base)
    z = b * math.log(p / (1 - p)) + (1 - b) * math.log(base / (1 - base))
    return 1 / (1 + math.exp(-z))


def committed_report() -> list[str]:
    out = []
    bb = best_bets_rows()
    pr = pp_results()

    out += ["### Paddy Power value bets by market (pp-results.html)", "",
            f"Settled Paddy Power basketball lines the log called value (ours 50%+ and 5%+ over Paddy Power's price), "
            f"page updated {pr['updated'] or '?'}. Won is rebuilt from the page's rounded hit rate.", "",
            "| Market | Bets | Said | Won | Got (95%) | Profit |", "|---|---|---|---|---|---|"]
    tot_n = tot_k = 0
    tot_said = tot_pl = 0.0
    for m in pr["by_market"]:
        lo, hi = wilson(m["won"], m["n"])
        out.append(f"| {m['market']} | {m['n']} | {pct(m['said'], 0)} | {m['won']} | {pct(m['won'] / m['n'], 0)} "
                   f"({pct(lo, 0)} to {pct(hi, 0)}) | {m['profit']:+.1f}u |")
        tot_n += m["n"]
        tot_k += m["won"]
        tot_said += m["said"] * m["n"]
        tot_pl += m["profit"]
    if tot_n:
        lo, hi = wilson(tot_k, tot_n)
        out.append(f"| **all basketball** | {tot_n} | {pct(tot_said / tot_n, 0)} | {tot_k} | "
                   f"{pct(tot_k / tot_n, 0)} ({pct(lo, 0)} to {pct(hi, 0)}) | {tot_pl:+.1f}u ({tot_pl / tot_n:+.0%} a bet) |")

    rec = pr["recent"]
    if rec:
        out += ["", "### The settled basketball value bets listed one by one (pp-results.html, Recent value bets)", "",
                "Grouped by how much of his last ten the page's record rests on. These rows are a subset of the table "
                "above; the intervals resample nothing (one row each), so they are Wilson only.", "",
                "| Group | Bets | Said | Got (95%) |", "|---|---|---|---|"]
        for label, sel in (("all", rec), ("last 5 hit 4 or 5", [r for r in rec if r["k5"] and r["k5"][0] >= 4]),
                           ("last 5 hit 3 or fewer", [r for r in rec if r["k5"] and r["k5"][0] <= 3])):
            if not sel:
                continue
            k = sum(r["y"] for r in sel)
            lo, hi = wilson(k, len(sel))
            out.append(f"| {label} | {len(sel)} | {pct(sum(r['p'] for r in sel) / len(sel))} | "
                       f"{pct(k / len(sel))} ({pct(lo)} to {pct(hi)}) |")

    out += ["", "### Published basketball player legs (best_bets.json)", "",
            f"{len(bb)} settled lines the site published (player-line singles, parlays, doubles), all overs, "
            f"each counted once, at the chance first shown.", "", *CALIB_HEAD]
    out.append(calib_row("all", calib(bb)))
    for night in sorted({r["night"] for r in bb}, key=lambda n: min(r["ts"] for r in bb if r["night"] == n)):
        out.append(calib_row(f"night of {night}", calib([r for r in bb if r["night"] == night])))
    for s in sorted({r["stat"] for r in bb}, key=lambda s: -sum(1 for r in bb if r["stat"] == s)):
        out.append(calib_row(s, calib([r for r in bb if r["stat"] == s])))
    for label, sel in (("main line", [r for r in bb if not r["alt"]]), ("alternative line", [r for r in bb if r["alt"]])):
        out.append(calib_row(label, calib(sel)))
    for lo, hi in ((0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)):
        out.append(calib_row(f"said {int(lo * 100)}-{min(100, int(hi * 100))}%",
                             calib([r for r in bb if lo <= r["p"] < hi])))
    for lo, hi in ((0, 15), (15, 18), (18, 21)):
        out.append(calib_row(f"record of {lo} to {hi - 1} games",
                             calib([r for r in bb if (r["record"][1] or 0) >= lo and (r["record"][1] or 0) < hi])))

    # The only held-out check the committed data allows: the logit shrink
    # fitted on the earlier nights, scored on the last one.
    nights = sorted({r["night"] for r in bb}, key=lambda n: min(r["ts"] for r in bb if r["night"] == n))
    if len(nights) >= 2:
        early = [r for r in bb if r["night"] != nights[-1]]
        late = [dict(r) for r in bb if r["night"] == nights[-1]]
        b, base = shrink_fit(early)
        for r in late:
            r["q"] = apply_logit(r["p"], b, base)
        d = loss_diff(late, "p", "q")
        out += ["", "### A shrink fitted on the earlier nights, scored on the last", "",
                f"Fitted on {len(early)} lines from {', '.join(nights[:-1])}: b = {b:.2f} towards {pct(base)}. "
                f"Scored on the {len(late)} lines of {nights[-1]}: log loss {d['a']:.4f} as published, "
                f"{d['b']:.4f} shrunk, difference {d['diff']:+.4f} (95% {d['ci'][0]:+.4f} to {d['ci'][1]:+.4f}). "
                "Far too few lines to decide anything; shown because it is the only split the repo allows."]
    return out


# ------------------------------------------------------------------ 2. the NBA cache (the Mac)

def season_of(ts: float) -> int:
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return d.year if d.month >= 8 else d.year - 1


def load_games(cache: Path) -> list[dict]:
    """Finished NBA games (regular season, NBA Cup, play-offs) with player box scores, oldest first.

    Each is {id, ts, season, start (first game of its season), players: [{pid, name, team, pos,
    minutes, stats}]}. Summer league and pre-season are left out, as the page leaves them out."""
    import hitrates
    import markets
    fill = markets.ZERO_FILL_BY_SPORT.get("basketball", hitrates.PLAYER_ZERO_FILL) or hitrates.PLAYER_ZERO_FILL
    ev = {}
    for f in glob.glob(str(Path(cache) / "team_*_events_last_*.json")):
        try:
            d = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        for e in (d or {}).get("events") or []:
            t = e.get("tournament") or {}
            if (((t.get("category") or {}).get("sport") or {}).get("slug") != "basketball"
                    or (e.get("status") or {}).get("type") != "finished"):
                continue
            name = (t.get("name") or "")
            if not name.startswith("NBA") or any(w in name for w in ("Summer", "Preseason", "Pre-season")):
                continue
            ev[e["id"]] = e
    games = []
    for eid, e in ev.items():
        lf = Path(cache) / f"event_{eid}_lineups.json"
        try:
            lu = json.loads(lf.read_text())
        except (OSError, ValueError):
            continue
        players = []
        for side in ("home", "away"):
            team = ((e.get(f"{side}Team") or {}).get("name"))
            for p in ((lu.get(side) or {}).get("players") or []):
                st = p.get("statistics") or {}
                if not st.get("secondsPlayed"):
                    continue
                vals = hitrates._player_stat_values(st, zero_fill=fill)
                players.append({"pid": (p.get("player") or {}).get("id"), "name": (p.get("player") or {}).get("name"),
                                "team": team, "pos": (p.get("position") or (p.get("player") or {}).get("position") or "?")[:1],
                                "minutes": vals.get("Minutes", 0.0), "stats": {s: vals.get(s, 0.0) for s in STATS}})
        if players:
            games.append({"id": eid, "ts": e["startTimestamp"], "season": season_of(e["startTimestamp"]),
                          "players": players})
    games.sort(key=lambda g: (g["ts"], g["id"]))
    first = {}
    for g in games:
        first.setdefault(g["season"], g["ts"])
    for g in games:
        g["start"] = first[g["season"]]
    return games


def _rungs(values: list[float]) -> list[float]:
    vals = sorted(values)
    med = vals[len(vals) // 2]
    out = []
    for f in LADDER:
        line = math.floor(med * f) + 0.5
        if line >= 0.5 and line not in out:
            out.append(line)
    return out


def priced_lines(games: list[dict], stats=STATS) -> list[dict]:
    """Every rung of every player-game, priced as the page prices it, from earlier games only.

    One row: game, ts, season, early (inside EARLY_DAYS of the season's first game), stat, pos,
    line, y (over landed), p (the page's model.price_player over his last ten), and what the
    shrinks need: his minutes and stat total in the ten, his median minutes, the group (how many
    of the ten are this season's) and the days since his last game."""
    import model
    hist = collections.defaultdict(list)          # pid -> [(ts, season, minutes, stats)]
    out = []
    for g in games:
        for p in g["players"]:
            past = [h for h in hist[p["pid"]] if h[2] >= MIN_MIN][-WINDOW:]
            if len(past) >= 3:
                this = sum(1 for h in past if h[1] == g["season"])
                group = GROUPS[0 if this <= 2 else 1 if this <= 5 else 2 if this < WINDOW else 3]
                for s in stats:
                    apps = [{"value": h[3][s], "minutes": h[2]} for h in past]
                    vals = [a["value"] for a in apps]
                    if sum(vals) <= 0:
                        continue
                    for line in _rungs(vals):
                        pr = model.price_player(apps, line, True, 1.0, None, "basketball")
                        out.append({"game": g["id"], "ts": g["ts"], "season": g["season"],
                                    "early": g["ts"] - g["start"] < EARLY_DAYS * 86400, "stat": s, "pos": p["pos"],
                                    "line": line, "y": int(p["stats"][s] > line), "p": pr["p"],
                                    "mins": sum(a["minutes"] for a in apps), "total": sum(vals),
                                    "med_min": sorted(a["minutes"] for a in apps)[len(apps) // 2],
                                    "vals": vals, "group": group,
                                    "rest": (g["ts"] - past[-1][0]) / 86400})
        for p in g["players"]:
            hist[p["pid"]].append((g["ts"], g["season"], p["minutes"], p["stats"]))
    return out


def pos_rates(rows: list[dict]) -> dict:
    """(stat, position) -> rate per minute over the rows' records (the earlier games)."""
    acc = collections.defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        a = acc[(r["stat"], r["pos"])]
        a[0] += r["total"]
        a[1] += r["mins"]
    return {k: v[0] / v[1] for k, v in acc.items() if v[1] > 0}


def rate_shrunk(r: dict, rates: dict, K: float) -> float:
    """The page's model path with his rate per minute pulled towards his position's."""
    import model
    own = r["total"] / r["mins"]
    prior = rates.get((r["stat"], r["pos"]), own)
    w = r["mins"] / (r["mins"] + K) if K > 0 else 1.0
    expected = (w * own + (1 - w) * prior) * min(90, r["med_min"])
    if expected <= 0:
        return r["p"]
    return model.calibrate_player(model.prob_over(r["line"], expected, r["vals"]), "basketball")


def fit_shrinks(train: list[dict]) -> dict:
    """K for the rate shrink and b per group for the logit shrink, on the earlier games only."""
    rates = pos_rates(train)
    best = None
    sample = train if len(train) <= 40000 else random.Random(SEED).sample(train, 40000)
    for K in K_GRID:
        ll = logloss([dict(r, q=rate_shrunk(r, rates, K)) for r in sample], "q")
        if best is None or ll < best[0]:
            best = (ll, K)
    base = {}
    for s in {r["stat"] for r in train}:
        sel = [r for r in train if r["stat"] == s]
        base[s] = sum(r["y"] for r in sel) / len(sel)
    bs = {}
    for g in GROUPS:
        sel = [r for r in train if r["group"] == g]
        if len(sel) < 200:
            bs[g] = 1.0
            continue
        if len(sel) > 40000:
            sel = random.Random(SEED).sample(sel, 40000)
        # one b per group, towards each stat's own base rate
        grid = [i / 40 * 1.5 for i in range(41)]
        scores = []
        for b in grid:
            scores.append((logloss([dict(r, q=apply_logit(r["p"], b, base[r["stat"]])) for r in sel], "q"), b))
        bs[g] = min(scores)[1]
    return {"K": best[1], "rates": {f"{k[0]}|{k[1]}": v for k, v in rates.items()}, "base": base, "b": bs}


def score_shrinks(test: list[dict], fit: dict) -> list[dict]:
    rates = {tuple(k.split("|")): v for k, v in fit["rates"].items()}
    out = []
    for r in test:
        out.append(dict(r, rate=rate_shrunk(r, rates, fit["K"]),
                        logit=apply_logit(r["p"], fit["b"].get(r["group"], 1.0),
                                          fit["base"].get(r["stat"], 0.5))))
    return out


def decide(scored: list[dict]) -> dict:
    """The fixed rule: which shrink, if any, earns a change to live pricing."""
    early = [r for r in scored if r["early"]]
    res = {}
    for name in ("rate", "logit"):
        allp, ear = loss_diff(scored, "p", name), loss_diff(early, "p", name) if early else None
        worse = []
        for g in GROUPS:
            sel = [r for r in scored if r["group"] == g]
            if len(sel) >= 50:
                d = loss_diff(sel, "p", name)
                if d["ci"][0] > 0:
                    worse.append(g)
        ok = (allp["ci"][1] < 0 and ear is not None and ear["ci"][1] < 0 and not worse)
        res[name] = {"all": allp, "early": ear, "worse_groups": worse, "holds": ok}
    return res


def cache_report(cache: Path, cut: str | None) -> list[str]:
    games = load_games(cache)
    if not games:
        return [f"No NBA games with box scores in {cache}. This needs the Mac's cache/ (backfill.py fetches the seasons)."]
    rows = priced_lines(games)
    seasons = sorted({g["season"] for g in games})
    if cut:
        cut_ts = datetime.fromisoformat(cut).replace(tzinfo=timezone.utc).timestamp()
    else:
        # the latest season's first game: fit on everything before it, score the season so far
        cut_ts = max(g["start"] for g in games)
    train = [r for r in rows if r["ts"] < cut_ts]
    test = [r for r in rows if r["ts"] >= cut_ts]
    out = [f"{len(games)} NBA games ({', '.join(f'{s}-{(s + 1) % 100:02d}' for s in seasons)}), "
           f"{len(rows)} priced rungs; fitted before {datetime.fromtimestamp(cut_ts, tz=timezone.utc):%d %b %Y} "
           f"({len(train)} rungs), scored from then on ({len(test)} rungs).", ""]
    if not train or not test:
        return out + ["Not enough games on one side of the cut to fit and score."]
    out += ["### The page's price on the later games", "", *CALIB_HEAD]
    out.append(calib_row("all", calib(test)))
    out.append(calib_row(f"first {EARLY_DAYS} days of the season", calib([r for r in test if r["early"]])))
    out.append(calib_row("after that", calib([r for r in test if not r["early"]])))
    for g in GROUPS:
        out.append(calib_row(f"record: {g}", calib([r for r in test if r["group"] == g])))
    out.append(calib_row("last game 60+ days before", calib([r for r in test if r["rest"] >= 60])))
    for s in STATS:
        out.append(calib_row(s, calib([r for r in test if r["stat"] == s])))
    for lo, hi in ((0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)):
        out.append(calib_row(f"said {int(lo * 100)}-{min(100, int(hi * 100))}%",
                             calib([r for r in test if lo <= r["p"] < hi])))
    out += ["", "### The page's price on the earlier games, for comparison", "", *CALIB_HEAD]
    out.append(calib_row("all", calib(train)))
    out.append(calib_row(f"first {EARLY_DAYS} days of a season", calib([r for r in train if r["early"]])))
    for g in GROUPS:
        out.append(calib_row(f"record: {g}", calib([r for r in train if r["group"] == g])))

    fit = fit_shrinks(train)
    scored = score_shrinks(test, fit)
    res = decide(scored)
    out += ["", "### The two shrinks, fitted on the earlier games", "",
            f"Rate: K = {fit['K']} minutes (weight on his own rate m / (m + K)). Logit: b by record group "
            + ", ".join(f"{g} {b:.2f}" for g, b in fit["b"].items()) + ".", "",
            "| Shrink | Lines | Log loss, page | Shrunk | Difference (95%, by game) | Early lines | Difference (95%) | Holds |",
            "|---|---|---|---|---|---|---|---|"]
    for name, r in res.items():
        e = r["early"] or {"n": 0, "diff": None, "ci": (float("nan"), float("nan"))}
        out.append(f"| {name} | {r['all']['n']} | {r['all']['a']:.4f} | {r['all']['b']:.4f} | {r['all']['diff']:+.4f} "
                   f"({r['all']['ci'][0]:+.4f} to {r['all']['ci'][1]:+.4f}) | {e['n']} | "
                   + (f"{e['diff']:+.4f} ({e['ci'][0]:+.4f} to {e['ci'][1]:+.4f})" if e["n"] else "-")
                   + f" | {'yes' if r['holds'] else 'no'}{' (worse on ' + ', '.join(r['worse_groups']) + ')' if r['worse_groups'] else ''} |")
    for name in ("rate", "logit"):
        out += ["", f"Calibration with the {name} shrink, later games:", "", *CALIB_HEAD]
        out.append(calib_row("all", calib(scored, key=name)))
        out.append(calib_row(f"first {EARLY_DAYS} days", calib([r for r in scored if r["early"]], key=name)))
        for g in GROUPS:
            out.append(calib_row(f"record: {g}", calib([r for r in scored if r["group"] == g], key=name)))
    held = [n for n, r in res.items() if r["holds"]]
    out += ["", "**Verdict under the fixed rule:** " + (
        (f"the {held[0]} shrink holds" if len(held) == 1 else "both shrinks hold")
        + " out of sample; a candidate for live pricing (NBA-CHECK.md says what to do next)."
        if held else "neither shrink holds out of sample; live pricing stays as it is.")]
    try:
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps({"generated": int(time.time()), "cut": cut_ts, **fit,
                                   "holds": {n: r["holds"] for n, r in res.items()}}, indent=1))
        out.append(f"\nFit saved to {OUT} (gitignored), for `nba_check.py pplog`.")
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ 3. Paddy Power's settled lines (the Mac)

def pplog_rows(rows: list[dict] | None = None) -> list[dict]:
    if rows is None:
        import pplog
        rows = pplog.all_rows()
    out = []
    for r in rows:
        if r.get("sport") != "basketball" or r.get("result") not in ("win", "lose"):
            continue
        f = r.get("first") or {}
        out.append({"game": r["event_id"], "ts": r["kickoff"], "stat": r["stat"], "line": r["line"],
                    "over": bool(r["over"]), "p": f.get("chance"), "price": f.get("price"),
                    "y": int(r["result"] == "win"), "n10": r.get("n10") or 0,
                    "value": _is_value(r)})
    return [r for r in out if r["p"] is not None]


def _is_value(r: dict) -> bool:
    try:
        import pplog
        return pplog.is_value(r)
    except Exception:  # noqa: BLE001
        return False


def pplog_report(rows: list[dict] | None = None) -> list[str]:
    rows = pplog_rows(rows)
    if not rows:
        return ["No settled Paddy Power basketball lines in pplog/ on this machine."]
    start = min(r["ts"] for r in rows)
    for r in rows:
        r["week"] = int((r["ts"] - start) // (7 * 86400)) + 1
    out = [f"{len(rows)} settled Paddy Power basketball lines from {datetime.fromtimestamp(start, tz=timezone.utc):%d %b %Y}, "
           "at the chance and price first seen.", "", *CALIB_HEAD]
    out.append(calib_row("every line", calib(rows)))
    out.append(calib_row("value bets (pplog.is_value)", calib([r for r in rows if r["value"]])))
    out.append(calib_row("overs", calib([r for r in rows if r["over"]])))
    out.append(calib_row("unders", calib([r for r in rows if not r["over"]])))
    for w in sorted({r["week"] for r in rows}):
        out.append(calib_row(f"week {w} of the log", calib([r for r in rows if r["week"] == w])))
    for s in STATS:
        sel = [r for r in rows if r["stat"] == s]
        if sel:
            out.append(calib_row(s, calib(sel)))
    for lo, hi in ((0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
        out.append(calib_row(f"said {int(lo * 100)}-{min(100, int(hi * 100))}%",
                             calib([r for r in rows if lo <= r["p"] < hi])))
    val = [r for r in rows if r["value"] and r["price"]]
    if val:
        ret = sum(r["y"] * r["price"] - 1 for r in val) / len(val)
        lo, hi = boot_ratio(_by(val, "game", lambda r: r["y"] * r["price"] - 1))
        out += ["", f"Value bets at Paddy Power's first price: {len(val)} bets, return {pct(ret, sign=True)} "
                f"a bet (95% {pct(lo, sign=True)} to {pct(hi, sign=True)}, by game)."]
    try:
        fit = json.loads(OUT.read_text())
    except (OSError, ValueError):
        fit = None
    if fit:
        sc = [dict(r, logit=apply_logit(r["p"], 1.0 if r["n10"] >= WINDOW else min(fit["b"].values()),
                                        fit["base"].get(r["stat"], 0.5))) for r in rows if r["over"]]
        d = loss_diff(sc, "p", "logit")
        out += ["", f"The cache's logit shrink (strongest group b = {min(fit['b'].values()):.2f}) on the Paddy Power "
                f"overs with fewer than ten games: log loss {d['a']:.4f} as logged, {d['b']:.4f} shrunk, difference "
                f"{d['diff']:+.4f} (95% {d['ci'][0]:+.4f} to {d['ci'][1]:+.4f}). A check at real lines, not a refit."]
    return out


def render(lines: list[str]) -> str:
    """The report as text, without the rows of groups that had no lines."""
    return "\n".join(l for l in lines if l is not None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("part", choices=["committed", "cache", "pplog"])
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--cut", help="fit before this date (YYYY-MM-DD); default the latest season's first game")
    a = ap.parse_args(argv)
    lines = (committed_report() if a.part == "committed" else cache_report(Path(a.cache), a.cut)
             if a.part == "cache" else pplog_report())
    print(render(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
