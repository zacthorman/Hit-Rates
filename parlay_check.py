"""
Do same-game parlays land as often as their joint counts say?

    python -B parlay_check.py walk --cache DIR      # rebuild every parlay the page would have shown
    python -B parlay_check.py report                # the tables in PARLAY-CHECK.md

`walk` replays the cache in date order and, for every finished match with
lineups, builds the fixture the way run.py does (each side's player records
from hitrates.player_form, strictly before kick-off), then calls the live
code: parlay.parlays_for for every candidate and parlay.best_parlay for the
one a sport's slate would have published. Parlays are priced off the record
alone, with no strength adjustment, so unlike the builders in
ACCA-CORRELATION.md this is the page's own code on the page's own inputs, not
a copy. Each candidate is settled from the match's own lineup, which is read
only to settle. A player who did not appear voids the ticket, the rule
besttrack.py settles the published record by. The rows go to calib/parlay_walk.json.

`report` reads that file and best_bets.json, measures landed against said,
fits two corrections on the earlier months and confirms them on the later
months and on the published parlays. Nothing is fetched and nothing live is
changed.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "calib" / "parlay_walk.json"
CUT = "2026-04-01"            # fitted before, confirmed on and after
SPORTS = {"football": 38, "american-football": 20, "baseball": 20}   # form window, as update.py
CROSS_LEAGUE = {7, 679, 10783}  # run.CROSS_LEAGUE_COMPETITIONS
SEED = 20261023
BOOT = 2000
EPS = 1e-6


def night_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------ walk forward

def _install_cache(cache: Path):
    """Point sofascore_api at an unpacked cache and forbid fetching. Reads
    are memoised, because every fixture re-reads its sides' last 20 to 38
    lineups."""
    import backtest
    import sofascore_api as api
    api.CACHE_DIR = Path(cache)

    @functools.lru_cache(maxsize=60000)
    def _read(path):
        return backtest.cache_only_get_json(path)

    def get_json(path, max_age_hours=None, verbose=True, **_):
        got = _read(path)
        return json.loads(json.dumps(got)) if isinstance(got, (dict, list)) else got

    api.get_json = get_json
    return api


def load_events(cache: Path) -> list[dict]:
    events = {}
    for path in Path(cache).glob("team_*_events_last_*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for e in data.get("events") or []:
            if (e.get("status") or {}).get("type") != "finished" or not e.get("startTimestamp"):
                continue
            sport = ((e.get("homeTeam") or {}).get("sport") or {}).get("slug")
            if sport not in SPORTS:
                continue
            if (e.get("homeTeam") or {}).get("gender") == "F":
                continue
            if not (Path(cache) / f"event_{e['id']}_lineups.json").exists():
                continue
            events[e["id"]] = e
    return sorted(events.values(), key=lambda e: (e["startTimestamp"], e["id"]))


def build_entry(event: dict) -> tuple[dict, dict]:
    """The fixture as run.py builds it, with every player record from
    before kick-off."""
    import hitrates
    sport = event["homeTeam"]["sport"]["slug"]
    ut = (event.get("tournament") or {}).get("uniqueTournament") or {}
    cross = ut.get("id") in CROSS_LEAGUE
    ts = event["startTimestamp"]
    teams = [{"id": event["homeTeam"]["id"], "name": event["homeTeam"].get("name"), "side": "home"},
             {"id": event["awayTeam"]["id"], "name": event["awayTeam"].get("name"), "side": "away"}]
    players = [hitrates.player_form(team_id=t["id"], team_name=t["name"] or "",
                                    tournament_id=None if cross else ut.get("id"),
                                    limit=SPORTS[sport], verbose=False,
                                    current_squad_only=False, before=ts, sport=sport)
               for t in teams]
    players = [recent_squad(recs) for recs in players]
    meta = {"id": event["id"], "home": teams[0]["name"], "away": teams[1]["name"],
            "kickoff": ts, "competition": ut.get("name")}
    entry = {"fixture": {"sport": sport, "competition": ut.get("name"), "crossLeague": cross,
                         "kickoff": ts, "id": event["id"]},
             "teams": teams, "players": players}
    return entry, meta


RECENT = 3


def recent_squad(records: list[dict], last: int = RECENT) -> list[dict]:
    """Records of players who appeared in one of the side's last `last`
    matches before kick-off.

    The live build keeps today's squad only (current_squad_only), which in
    the past would be a look-ahead. Without some filter a replay keeps every
    man who played for the side in 38 games, including the ones who have
    since left, and a parlay on them comes back void. Recent appearances are
    the nearest thing to the squad that was knowable on the morning."""
    order = []
    for r in sorted(records, key=lambda r: (r.get("date") or "", r.get("match_id") or 0)):
        if r["match_id"] not in order:
            order.append(r["match_id"])
    keep_matches = set(order[-last:])
    keep = {r["player"] for r in records if r["match_id"] in keep_matches}
    return [r for r in records if r["player"] in keep]


def settle(lineups: dict, team_index: int, player: str, stat: str, threshold: float, sport: str):
    """1 or 0, or None for a void, by besttrack's own rule: a player with no
    statistics, or (football, basketball) no minutes, did not play; anyone
    else is graded on his zero-filled number, however short his game."""
    import hitrates
    import markets
    fill = markets.ZERO_FILL_BY_SPORT.get(sport, hitrates.PLAYER_ZERO_FILL) or hitrates.PLAYER_ZERO_FILL
    side = ("home", "away")[team_index]
    for e in (lineups.get(side) or {}).get("players") or []:
        if (e.get("player") or {}).get("name") != player:
            continue
        st = e.get("statistics") or {}
        if not st:
            return None
        mins_key = {"football": "minutesPlayed", "basketball": "secondsPlayed"}.get(sport)
        if mins_key and not st.get(mins_key):
            return None
        values = hitrates._player_stat_values(st, zero_fill=fill)
        if not values:
            return None
        return int(values.get(stat, 0.0) > threshold - 0.5)
    return None


def _key(leg):
    return (leg["player"], leg["stat"], leg["threshold"])


def walk(cache: Path, out: Path = OUT, limit: int | None = None) -> list[dict]:
    api = _install_cache(cache)
    import parlay
    events = load_events(cache)
    if limit:
        events = events[-limit:]
    rows = []
    slates: dict = {}
    for i, e in enumerate(events, 1):
        try:
            entry, meta = build_entry(e)
        except Exception as exc:          # a broken cache file costs one fixture
            print(f"  {e['id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        sport = entry["fixture"]["sport"]
        cands = parlay.parlays_for(entry, meta)
        if not cands:
            continue
        lineups = api.get_json(f"event/{e['id']}/lineups") or {}
        team_of = {t["name"]: k for k, t in enumerate(entry["teams"])}
        night = night_of(e["startTimestamp"])
        # Which candidate is this fixture's best, by best_parlay's own rule
        # applied to this fixture alone.
        alone = parlay.best_parlay([(entry, meta)])
        for c in cands:
            legs = []
            for l in c["legs"]:
                y = settle(lineups, team_of[l["team"]], l["player"], l["stat"], l["threshold"], sport)
                legs.append({"team": team_of[l["team"]], "player": l["player"], "stat": l["stat"],
                             "threshold": l["threshold"], "hits": l["hits"], "total": l["total"], "y": y})
            sides = []
            for k, s in enumerate(c["sides"]):
                idx = team_of[s["team"]]
                ys = [l["y"] for l in legs if l["team"] == idx]
                sides.append({"team": idx, "hits": s["hits"], "total": s["total"],
                              "y": None if any(v is None for v in ys) else int(all(ys)),
                              "legs": [j for j, l in enumerate(legs) if l["team"] == idx]})
            void = any(l["y"] is None for l in legs)
            rows.append({"game": e["id"], "ts": e["startTimestamp"], "night": night, "sport": sport,
                         "comp": meta["competition"], "fair": c["fair"], "said": 1 / c["fair"],
                         "legs": legs, "sides": sides, "void": void,
                         "won": None if void else int(all(l["y"] for l in legs)),
                         "keys": sorted(_key(l) for l in c["legs"]),
                         "fixture_best": bool(alone) and sorted(map(_key, alone["legs"]))
                         == sorted(_key(l) for l in c["legs"]),
                         "adjusted_alone": None})
        slates.setdefault((sport, night), []).append((entry, meta))
        if i % 250 == 0:
            print(f"  {i}/{len(events)} fixtures, {len(rows)} candidates", file=sys.stderr, flush=True)
    # The slate pick: best_parlay over every fixture of one sport on one night.
    by_game = {}
    for r in rows:
        by_game.setdefault(r["game"], []).append(r)
    for (sport, night), group in slates.items():
        win = parlay.best_parlay(group)
        if not win:
            continue
        gid = win["fixture"]["id"]
        keys = sorted(map(_key, win["legs"]))
        for r in by_game.get(gid, []):
            r["slate_best"] = r["keys"] == keys
            if r["slate_best"]:
                r["z"] = win.get("z")
    for r in rows:
        r.setdefault("slate_best", False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows))
    print(f"{len(rows)} candidate parlays over {len(by_game)} fixtures -> {out}", file=sys.stderr)
    return rows


# ------------------------------------------------------------ corrections

def _logit(p):
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def _sig(z):
    return 1 / (1 + math.exp(-z))


def leg_rate(hits, total):
    """A leg's own record rate, the number the page shows beside it."""
    return hits / total


def multiplied(row) -> float:
    q = 1.0
    for l in row["legs"]:
        q *= leg_rate(l["hits"], l["total"])
    return q


def shrunk(row, k: float) -> float:
    """Each side's joint count pulled towards the product of its own legs'
    rates, by k pseudo-matches, then multiplied across sides.

    k = 0 is the page as it stands. The product of the legs is the price the
    page would quote if the legs were independent; the joint count's job is
    to say how far they are not, and with 10 to 38 matches behind it, picked
    as the best of a few hundred combinations, it says it noisily."""
    p = 1.0
    for s in row["sides"]:
        q = 1.0
        for j in s["legs"]:
            l = row["legs"][j]
            q *= leg_rate(l["hits"], l["total"])
        p *= (s["hits"] + k * q) / (s["total"] + k)
    return p


def recal(row, w) -> float:
    """logit P = a + b logit(said) + c logit(multiplied), the shape the
    builder correction used."""
    a, b, c = w
    return _sig(a + b * _logit(row["said"]) + c * _logit(multiplied(row)))


def log_loss(ps, ys) -> float:
    return -sum(math.log(min(max(p, EPS), 1 - EPS)) if y else math.log(1 - min(max(p, EPS), 1 - EPS))
                for p, y in zip(ps, ys)) / max(len(ys), 1)


def fit_k(rows, grid=(0, 1, 2, 3, 5, 8, 12, 20, 30, 50, 80, 130, 200, 400, 1000, 1e6)) -> float:
    ys = [r["won"] for r in rows]
    return min(grid, key=lambda k: log_loss([shrunk(r, k) for r in rows], ys))


def fit_recal(rows, iters=60, ridge=1e-3):
    """Newton steps on the log loss, starting from the page as it is (0, 1, 0)."""
    import numpy as np
    X = np.array([[1.0, _logit(r["said"]), _logit(multiplied(r))] for r in rows])
    y = np.array([r["won"] for r in rows], dtype=float)
    prior = np.array([0.0, 1.0, 0.0])
    w = prior.copy()
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + ridge * (w - prior) * len(y)
        H = (X.T * (p * (1 - p))) @ X + ridge * len(y) * np.eye(3)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return tuple(float(x) for x in w)


# ------------------------------------------------------------ intervals

def boot_ratio(rows, num, den, seed=SEED, reps=BOOT):
    """sum(num) / sum(den), with a 95% interval resampling whole nights."""
    by = {}
    for r in rows:
        x = by.setdefault(r["night"], [0.0, 0.0])
        x[0] += num(r)
        x[1] += den(r)
    nights = list(by.values())
    tot = sum(a for a, _ in nights) / max(sum(b for _, b in nights), EPS)
    if len(nights) < 2:
        return tot, float("nan"), float("nan")
    rnd = random.Random(seed)
    draws = []
    for _ in range(reps):
        a = b = 0.0
        for _ in nights:
            x = nights[rnd.randrange(len(nights))]
            a += x[0]
            b += x[1]
        draws.append(a / b if b else float("nan"))
    draws.sort()
    return tot, draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def boot_diff(rows, f, g, seed=SEED, reps=BOOT):
    """Mean of f - g per row (log losses), 95% interval resampling nights."""
    by = {}
    for r in rows:
        x = by.setdefault(r["night"], [0.0, 0])
        x[0] += f(r) - g(r)
        x[1] += 1
    nights = list(by.values())
    tot = sum(a for a, _ in nights) / max(sum(n for _, n in nights), 1)
    if len(nights) < 2:
        return tot, float("nan"), float("nan")
    rnd = random.Random(seed)
    draws = []
    for _ in range(reps):
        a = n = 0
        for _ in nights:
            x = nights[rnd.randrange(len(nights))]
            a += x[0]
            n += x[1]
        draws.append(a / n)
    draws.sort()
    return tot, draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


# ------------------------------------------------------------ published

def published(path: Path = HERE / "best_bets.json") -> list[dict]:
    """Settled published parlays with no void leg, one row per distinct
    ticket, in the walk forward's shape. Per-side joint counts are not stored
    on the record, only the ticket's fair price, so a side's count is filled
    from the walk forward's rebuild of the same ticket where it exists
    (see `attach_sides`)."""
    items = json.loads(path.read_text())
    seen = {}
    for b in items:
        if b.get("category") != "Pick: parlay" or b.get("result") not in ("win", "lose"):
            continue
        if any(l.get("result") not in ("win", "lose") for l in b["legs"]):
            continue
        key = tuple(sorted((l["event_id"], l["player"], l["stat"], l["threshold"]) for l in b["legs"]))
        if key in seen:
            continue
        teams = []
        for l in b["legs"]:
            if l["team"] not in teams:
                teams.append(l["team"])
        legs = [{"team": teams.index(l["team"]), "player": l["player"], "stat": l["stat"],
                 "threshold": l["threshold"], "hits": l["hits"], "total": l["total"],
                 "y": int(l["result"] == "win")} for l in b["legs"]]
        seen[key] = {"game": b["legs"][0]["event_id"], "ts": b["legs"][0]["kickoff"],
                     "night": night_of(b["legs"][0]["kickoff"]), "sport": b["sport"],
                     "said": 1 / b["fair"], "fair": b["fair"], "legs": legs,
                     "won": int(b["result"] == "win"), "sides": None,
                     "keys": sorted((l["player"], l["stat"], l["threshold"]) for l in b["legs"])}
    return list(seen.values())


def attach_sides(pub: list[dict], walk_rows: list[dict]) -> int:
    """Give each published ticket its per-side joint counts from the rebuild
    of the same fixture, when the rebuild finds the same four legs at the
    same joint price. Returns how many matched."""
    by = {(r["game"], tuple(map(tuple, r["keys"]))): r for r in walk_rows}
    n = 0
    for p in pub:
        r = by.get((p["game"], tuple(map(tuple, p["keys"]))))
        if r and abs(r["said"] - p["said"]) < 1e-6:
            # The rebuild's leg order and team numbering, with the
            # published results.
            res = {(l["player"], l["stat"], l["threshold"]): l["y"] for l in p["legs"]}
            p["legs"] = [dict(l, y=res[(l["player"], l["stat"], l["threshold"])]) for l in r["legs"]]
            p["sides"] = r["sides"]
            p["rebuilt"] = True
            n += 1
    return n


# ------------------------------------------------------------ report

def _summary_row(label, rows, said=lambda r: r["said"]):
    n = len(rows)
    k = sum(r["won"] for r in rows)
    s = sum(said(r) for r in rows)
    lo, hi = wilson(k, n)
    ratio, rlo, rhi = boot_ratio(rows, lambda r: r["won"], said)
    return (f"| {label} | {n} | {len({r['night'] for r in rows})} | {k} | {k / n:.1%} ({lo:.1%} to {hi:.1%}) | "
            f"{s / n:.1%} | {ratio:.2f} ({rlo:.2f} to {rhi:.2f}) |")


HEAD = ["| set | tickets | nights | landed | rate (95% Wilson) | said | landed / said (95% by night) |",
        "|---|---:|---:|---:|---:|---:|---:|"]


def side_rows(rows):
    """One row per side of each ticket: did that side's legs all land,
    against its joint count."""
    out = []
    for r in rows:
        for s in r["sides"] or []:
            if s["y"] is None:
                continue
            out.append({"night": r["night"], "won": s["y"], "said": s["hits"] / s["total"],
                        "total": s["total"], "n_legs": len(s["legs"])})
    return out


def calibration_table(rows, keyed):
    out = ["| stated | tickets | said | landed |", "|---|---:|---:|---:|"]
    bands = [(0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .7), (.7, 1.01)]
    for lo, hi in bands:
        sel = [r for r in rows if lo <= keyed(r) < hi]
        if sel:
            out.append(f"| {lo * 100:.0f}-{min(hi, 1) * 100:.0f}% | {len(sel)} | "
                       f"{sum(keyed(r) for r in sel) / len(sel):.3f} | {sum(r['won'] for r in sel) / len(sel):.3f} |")
    return out


def shape(row) -> tuple:
    """Legs per side, smallest first: (4,) is one team, (1, 3) and (2, 2) are split."""
    from collections import Counter
    return tuple(sorted(Counter(l["team"] for l in row["legs"]).values()))


def is_split(row) -> bool:
    return len(shape(row)) > 1


def correction_table(res) -> list[str]:
    out = ["| test set | correction | tickets | nights | landed | said | corrected | log loss said | "
           "log loss corrected | corrected minus said (95% by night) |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for x in res:
        d = x["diff"]
        out.append(f"| {x['set']} | {x['fix']} | {x['n']} | {x['nights']} | {x['landed']:.3f} | {x['said']:.3f} | "
                   f"{x['corrected']:.3f} | {x['ll_said']:.4f} | {x['ll_new']:.4f} | "
                   f"{d[0]:+.4f} ({d[1]:+.4f} to {d[2]:+.4f}) |")
    return out


def check(train, tests: dict):
    """Fit both corrections on train and score them on every test set.

    The shrink needs each side's joint count, which a published ticket only
    has when the walk forward rebuilt it exactly; the recalibration needs
    only the ticket's price and its legs' records, so it is scored on every
    published ticket. A correction holds only if it lowers log loss on every
    test set it can be scored on."""
    k = fit_k(train)
    w = fit_recal(train)
    res = []
    for label, rows in tests.items():
        for name, fn, ok in (("shrink", lambda r: shrunk(r, k), lambda r: bool(r.get("sides"))),
                             ("recalibration", lambda r: recal(r, w), lambda r: True)):
            sel = [r for r in rows if ok(r)]
            if not sel:
                continue
            ys = [r["won"] for r in sel]
            base = [r["said"] for r in sel]
            new = [fn(r) for r in sel]
            if name == "shrink" and k >= 1e5:
                name = "shrink (k infinite: multiply the legs)"
                fn = multiplied
                sel = rows
                new = [fn(r) for r in sel]
                ys = [r["won"] for r in sel]
                base = [r["said"] for r in sel]
            res.append({"set": label, "fix": name, "n": len(sel), "nights": len({r["night"] for r in sel}),
                        "landed": sum(ys) / len(ys), "said": sum(base) / len(base),
                        "corrected": sum(new) / len(new),
                        "ll_said": log_loss(base, ys), "ll_new": log_loss(new, ys),
                        "diff": boot_diff(sel, lambda r, fn=fn: log_loss([fn(r)], [r["won"]]),
                                          lambda r: log_loss([r["said"]], [r["won"]]))})
    holds = {}
    for name in ("shrink", "recalibration"):
        mine = [x for x in res if x["fix"].startswith(name)]
        holds[name] = len(mine) == len(tests) and all(x["ll_new"] < x["ll_said"] for x in mine)
    return k, w, res, holds


def report(walk_path: Path = OUT) -> str:
    rows = [r for r in json.loads(walk_path.read_text()) if not r["void"]]
    pub = published()
    matched = attach_sides(pub, json.loads(walk_path.read_text()))
    out = [f"Generated by `python -B parlay_check.py report` on "
           f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. "
           f"Intervals resample whole nights, {BOOT} draws, seed {SEED}.\n"]

    slate = [r for r in rows if r["slate_best"]]
    fixture = [r for r in rows if r["fixture_best"]]
    out.append("### 1. Landed against said\n")
    out += HEAD
    out.append(_summary_row("walk forward, every candidate", rows))
    out.append(_summary_row("walk forward, each fixture's best", fixture))
    out.append(_summary_row("walk forward, each slate's pick (what is published)", slate))
    for sport in SPORTS:
        sel = [r for r in slate if r["sport"] == sport]
        if sel:
            out.append(_summary_row(f"slate picks, {sport}", sel))
    out.append(_summary_row("published, settled with no void leg", pub))
    out.append(_summary_row("candidates, priced by multiplying legs", rows, multiplied))
    out.append(_summary_row("slate picks, priced by multiplying legs", slate, multiplied))
    out.append(_summary_row("published, priced by multiplying legs", pub, multiplied))

    out.append("\n### 2. Per side: the joint count on its own\n")
    out.append("One row per side of a ticket: did every leg on that side land, against the side's "
               "joint count (hits / total).\n")
    out += HEAD
    out.append(_summary_row("sides of every candidate", side_rows(rows)))
    out.append(_summary_row("sides of each fixture's best", side_rows(fixture)))
    out.append(_summary_row("sides of slate picks", side_rows(slate)))
    out.append(_summary_row("sides of slate picks, 4 legs on one side",
                            [s for s in side_rows(slate) if s["n_legs"] == 4]))
    out.append(_summary_row("sides of slate picks, 2 or 3 legs", [s for s in side_rows(slate) if s["n_legs"] in (2, 3)]))
    out.append(_summary_row("sides of slate picks, 1 leg", [s for s in side_rows(slate) if s["n_legs"] == 1]))

    out.append("\n### 3. Calibration of the slate picks\n")
    out += calibration_table(slate, lambda r: r["said"])

    out.append(f"\n### 4. Corrections, fitted before {CUT} on slate picks\n")
    out.append(f"The published record holds {len(pub)} settled tickets with no void leg; the walk forward "
               f"rebuilt {matched} of them exactly (same four legs, same joint price), and only those can carry "
               "per-side joint counts for the shrink.\n")
    train = [r for r in slate if r["night"] < CUT]
    later = [r for r in slate if r["night"] >= CUT]
    later_fix = [r for r in fixture if r["night"] >= CUT]
    k, w, res, holds = check(train, {"walk forward, later slate picks": later,
                                     "walk forward, later fixture bests": later_fix,
                                     "published": pub})
    out.append(f"Shrink: k = {k:g} pseudo-matches towards the product of the side's own legs. "
               f"Recalibration: logit P = {w[0]:+.3f} {w[1]:+.3f} logit(said) {w[2]:+.3f} logit(multiplied). "
               f"Training set: {len(train)} slate picks over {len({r['night'] for r in train})} nights.\n")
    out += correction_table(res)
    out.append(f"\nHolds on every test set: shrink {'yes' if holds['shrink'] else 'no'}, "
               f"recalibration {'yes' if holds['recalibration'] else 'no'}.")

    out.append("\n### 5. By shape: one team or split across both\n")
    out += HEAD
    for label, sel in (("walk forward, every candidate", rows), ("walk forward, each fixture's best", fixture),
                       ("walk forward, slate picks", slate), ("published", pub)):
        for sh in ((4,), (1, 3), (2, 2)):
            got = [r for r in sel if shape(r) == sh]
            if got:
                out.append(_summary_row(f"{label}, {'+'.join(map(str, sh))}", got))

    out.append("\n### 6. Exploratory: the same corrections fitted on earlier fixture bests\n")
    out.append("Not the pre-set test. Section 4 fits on the earlier slate picks because that is what "
               "is published; these fits use the larger set of each fixture's best, and the split-ticket "
               "rows were chosen after section 5 had been seen, so none of this counts as confirmation.\n")
    tests = {"walk forward, later slate picks": later, "walk forward, later fixture bests": later_fix,
             "published": pub}
    k2, w2, res2, holds2 = check([r for r in fixture if r["night"] < CUT], tests)
    out.append(f"All shapes: k = {k2:g}; recalibration {w2[0]:+.3f} {w2[1]:+.3f} {w2[2]:+.3f}. "
               f"Holds: shrink {'yes' if holds2['shrink'] else 'no'}, "
               f"recalibration {'yes' if holds2['recalibration'] else 'no'}.\n")
    out += correction_table(res2)
    split_tests = {k_: [r for r in v if is_split(r)] for k_, v in tests.items()}
    k3, w3, res3, holds3 = check([r for r in fixture if r["night"] < CUT and is_split(r)], split_tests)
    out.append(f"\nSplit tickets only: k = {k3:g}; recalibration {w3[0]:+.3f} {w3[1]:+.3f} {w3[2]:+.3f}. "
               f"Holds: shrink {'yes' if holds3['shrink'] else 'no'}, "
               f"recalibration {'yes' if holds3['recalibration'] else 'no'}.\n")
    out += correction_table(res3)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("walk", "report"))
    ap.add_argument("--cache", default=str(HERE / "cache"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=str(OUT), help="where walk writes its rows and report reads them")
    args = ap.parse_args(argv)
    if args.what == "walk":
        walk(Path(args.cache), Path(args.out), limit=args.limit)
    else:
        text = report(Path(args.out))
        (HERE / "calib" / "parlay_check.md").write_text(text + "\n")
        print(text)


if __name__ == "__main__":
    main()
