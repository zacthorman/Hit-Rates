"""
Good player lines: each player's own line, not one line per stat for the squad.

    python playerlines.py                 # next 8 hours, printed
    python playerlines.py --hours 48 --top 30

Why this exists. weekend.player_legs_for prices every player against the
report's one line per stat (24.5 receiving yards for every receiver on the
field), and its own docstring says that is fine for ranking and wrong for
staking. The NFL Defences tab already does the better thing in the page's
JavaScript: the highest ladder rung a player has cleared 7 times in his last
10, where his recent average still clears it by 10%. That never left the
browser, so it was never logged or settled. This is the same rule in Python,
for every sport, so the suggestions can be shown on tonight.html, logged by
besttrack (category "Player line") and linelog, and judged on results.

The rule, per player and stat:
  * only players who are available: not ruled out on the NFL injury report,
    in the confirmed XI once the line-up is out (football), on the active
    roster once the inactives are out (NFL)
  * at least MIN_GAMES real appearances
  * rungs are whole-number thresholds ("3+ shots", "40+ rushing yards");
    the chosen rung is the highest one cleared in at least HIT_RATE of the
    last RECENT games, with the recent average at least CLEAR times it
  * priced on the full sample through model.price and weekend.calibrate, the
    same path every other leg takes, so the chance is shrunk exactly as much
    as the site's settled player picks say it should be
  * kept only at MIN_CHANCE or better and a fair price of parlay.MIN_LEG_PRICE
    or longer: a 1.08 shot is not a bet anyone offers

Heuristic thresholds, mirroring the Defences tab. Not backtested yet: that is
what logging them is for. linelog.py report shows how they land.
"""
from __future__ import annotations

import argparse
import math
import re
import time
from pathlib import Path

import model
import parlay
import weekend

ROOT = Path(__file__).resolve().parent

RECENT = 10          # the window the rung is chosen on
HIT_RATE = 0.7       # cleared in 7 of the last 10
CLEAR = 1.10         # recent average at least 10% over the rung
MIN_GAMES = 8        # real appearances before a player is considered
MIN_CHANCE = 0.60    # calibrated chance to be suggested at all
PER_FIXTURE = 5      # suggestions shown per fixture, one per player
MAX_CHANCE = 0.94    # above this nobody prices it as a bet

# Stats that are one-off events rather than counts with a ladder: a "1+" rung
# on these is a different market (anytime scorer) with its own pricing, and a
# 7-in-10 record on them is almost always a small-sample accident.
SKIP_STATS = re.compile(r"touchdown|interception|goals?$|assists?$|sacks|fumble|"
                        r"red card|penalt|own goal|home run|stolen", re.I)

# Markets a bookmaker actually lists as a player line. "Minutes" is a perfectly
# good stat and nobody will take a bet on it; it topped the first run of this.
# A sport not named here falls back to every stat SKIP_STATS lets through.
OFFERED = {
    "football": {"Shots", "Shots on target", "Tackles", "Fouls", "Fouled",
                 "Passes", "Saves"},
    "baseball": {"Hits", "Total bases", "Hits runs and RBIs", "Singles",
                 "Pitcher strikeouts", "Outs recorded", "Hits allowed"},
    "american-football": {"Passing yards", "Passing completions", "Passing attempts",
                          "Rushing yards", "Rushing attempts", "Receiving receptions",
                          "Receiving yards", "Rushing and receiving yards",
                          "Passing and rushing yards", "Defensive combine tackles",
                          "Defensive assist tackles", "Kicking fg made",
                          "Kicking total points"},
}

PITCHER_STATS = {"Pitcher strikeouts", "Outs recorded", "Hits allowed"}
STARTER_OUTS = 12      # four innings a game on average: a starter, not a reliever

OUT_RE = re.compile(r"^(out|doubtful|injured reserve|ir\b|suspen|pup|physically unable|"
                    r"non-football|reserve)", re.I)


def _step(values: list[float]) -> int:
    """Rung size: units for counts, fives for yards, tens for passing yards."""
    typical = sorted(values)[len(values) // 2] if values else 0
    if typical <= 15:
        return 1
    if typical <= 120:
        return 5
    return 10


def _available(entry: dict, side_index: int, sport: str):
    """(names allowed or None for no filter, names ruled out, label)."""
    side = "home" if side_index == 0 else "away"
    out = {p[0] for p in (entry.get("injuries") or {}).get(side) or []
           if OUT_RE.match(p[2] or "")}
    lu = (entry.get("lineups") or {}).get("confirmed")
    if not lu:
        return None, out, "line-up not out yet"
    block = lu.get(side) or {}
    xi = {p.get("name") for p in block.get("xi") or []}
    missing = {m[0] for m in block.get("missing") or []}
    if sport == "american-football":
        roster = xi | set(block.get("bench") or [])
        return (roster - missing) or None, out | missing, "inactives applied"
    return xi or None, out | missing, "confirmed XI"


def _rung(recent: list[float]):
    """Highest whole-number threshold the rule allows, or None."""
    if len(recent) < MIN_GAMES:
        return None
    avg = sum(recent) / len(recent)
    step = _step(recent)
    best = None
    t = step
    top = max(recent)
    while t <= top:
        hits = sum(1 for v in recent if v >= t)
        if hits / len(recent) >= HIT_RATE and avg >= CLEAR * t:
            best = t
        t += step
    return best


def suggest(entry: dict, meta: dict, per_fixture: int = PER_FIXTURE) -> list[dict]:
    """The best player line for each available player, best first."""
    sport = weekend.sport_of(entry)
    offered = OFFERED.get(sport)
    stats = [s for s in (entry.get("playerLines") or {})
             if (s in offered if offered else not SKIP_STATS.search(s))]
    teams = entry.get("teams") or []
    qb_change = entry.get("qbChange") or {}
    cross = bool((entry.get("fixture") or {}).get("crossLeague"))
    legs = []
    for team_index, records in enumerate(entry.get("players") or []):
        if team_index >= len(teams):
            continue
        allowed, ruled_out, status = _available(entry, team_index, sport)
        new_qb = ("home" if team_index == 0 else "away") in qb_change
        by_player: dict[str, list] = {}
        for r in records:
            if r.get("player"):
                by_player.setdefault(r["player"], []).append(r)
        for name, games in by_player.items():
            if name in ruled_out or (allowed is not None and name not in allowed):
                continue
            played = sorted(weekend._played(games, sport),
                            key=lambda g: str(g.get("date") or ""), reverse=True)
            if len(played) < MIN_GAMES:
                continue
            # Pitcher props are only listed for the starter. A reliever's
            # "2+ outs" is unpriced, and whether he pitches at all is the bet.
            outs = [float(g["stats"]["Outs recorded"]) for g in played
                    if (g.get("stats") or {}).get("Outs recorded") is not None]
            starter = bool(outs) and sum(outs) / len(outs) >= STARTER_OUTS
            for stat in stats:
                if sport == "baseball" and stat in PITCHER_STATS and not starter:
                    continue
                if new_qb and stat.startswith(("Passing", "Receiving", "Rushing and receiving")):
                    continue
                values = [float(g["stats"][stat]) for g in played
                          if (g.get("stats") or {}).get(stat) is not None]
                if len(values) < MIN_GAMES:
                    continue
                recent = values[:RECENT]
                t = _rung(recent)
                if t is None:
                    continue
                line = t - 0.5
                hits = sum(1 for v in values if v > line)
                price = model.price(line, True, None, values, hits, len(values), sport=sport)
                if not math.isfinite(price["fair"]):
                    continue
                last3 = values[:3]
                legs.append({
                    "fixture": meta, "team": teams[team_index].get("name"),
                    "teamIndex": team_index, "player": name,
                    "position": played[0].get("position"), "period": "ALL",
                    "stat": stat, "line": line, "over": True,
                    "alt": True, "threshold": t,
                    "hits": hits, "total": len(values),
                    "recentHits": sum(1 for v in recent if v > line), "recentN": len(recent),
                    "avg": sum(recent) / len(recent),
                    "trend": (sum(last3) / len(last3)) / (sum(recent) / len(recent))
                    if sum(recent) else None,
                    "venue": None, "fair": price["fair"], "need": price["need"],
                    "p": price["p"], "source": "playerline",
                    "evidence": model.wilson_low(hits, len(values)),
                    "crossLeague": cross, "lineupStatus": status,
                })
    weekend.calibrate(legs)
    for l in legs:
        c = weekend.chance(l)
        l["chance"] = c
        l["fair"] = 1 / c if c else math.inf
    keep = [l for l in legs
            if MIN_CHANCE <= l["chance"] <= MAX_CHANCE and l["fair"] >= parlay.MIN_LEG_PRICE]
    keep.sort(key=lambda l: (-l["chance"], -l["total"]))
    out, seen = [], set()
    for l in keep:
        if l["player"] in seen:
            continue
        seen.add(l["player"])
        out.append(l)
        if len(out) >= per_fixture:
            break
    return out


def upcoming(hours: float):
    """(entry, meta) for every fixture kicking off in the next `hours`."""
    import make_index
    now = time.time()
    seen, out = set(), []
    paths = sorted((p for p in (ROOT / "reports").glob("*.html")
                    if not p.name.startswith("pick-")),
                   key=lambda p: -p.stat().st_mtime)
    for path in paths:
        for e, m in make_index.read_entries(path):
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            if now < (m["kickoff"] or 0) <= now + hours * 3600:
                out.append((e, m))
    return sorted(out, key=lambda x: x[1]["kickoff"])


def describe(l: dict) -> str:
    return f"{l['player']} {l['threshold']:g}+ {l['stat'].lower()}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--hours", type=float, default=8)
    ap.add_argument("--top", type=int, default=0, help="also print the best N across all fixtures")
    args = ap.parse_args(argv)
    every = []
    for entry, meta in upcoming(args.hours):
        legs = suggest(entry, meta)
        every.extend(legs)
        kick = time.strftime("%a %H:%M", time.localtime(meta["kickoff"]))
        print(f"\n{kick}  {meta['home']} v {meta['away']}  ({meta['competition']})")
        if not legs:
            print("   nothing qualified")
        for l in legs:
            trend = f"  trend {l['trend']:.2f}x" if l.get("trend") else ""
            print(f"   {describe(l):45} {l['recentHits']}/{l['recentN']} recent, "
                  f"{l['hits']}/{l['total']} all, avg {l['avg']:.1f}, "
                  f"chance {l['chance']:.0%}, fair {l['fair']:.2f}{trend}  [{l['lineupStatus']}]")
    if args.top:
        print(f"\nBest {args.top} across all fixtures")
        for l in sorted(every, key=lambda l: -l["chance"])[:args.top]:
            fx = l["fixture"]
            print(f"   {l['chance']:.0%}  fair {l['fair']:.2f}  {describe(l)}  ({fx['home']} v {fx['away']})")


if __name__ == "__main__":
    main()
