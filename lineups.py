#!/usr/bin/env python3
"""Who is actually starting, and the best picks among those who are.

    .venv/bin/python lineups.py              # every fixture kicking off in the next 3 hours
    .venv/bin/python lineups.py --hours 6
    .venv/bin/python lineups.py --event 15534027

Line-ups are published about an hour before kick-off. A player prop on a man
who is on the bench is a bet on nothing, and it has happened twice in a week
(Mbappe v Italy, Mbappe v Belgium). So this reads the confirmed line-up for
each fixture, then ranks player picks ONLY among confirmed starters, plus the
team picks, from the records already in reports/.

One request per fixture, through FlareSolverr like everything else, cached for
three minutes so re-running in the hour before kick-off picks up changes.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import time

import sofascore_api as api

TEAM = {"Goals": [0.5, 1.5, 2.5], "Match goals": [1.5, 2.5, 3.5],
        "Shots on target": [2.5, 3.5, 4.5, 5.5], "Total shots": [8.5, 10.5, 12.5, 14.5],
        "Corner kicks": [2.5, 3.5, 4.5, 5.5], "Match corners": [7.5, 8.5, 9.5, 10.5],
        "Both teams to score": [0.5], "Match cards": [2.5, 3.5, 4.5]}
PLAYER = {"Shots": [1, 2, 3, 4], "Shots on target": [1, 2], "Fouls": [1, 2], "Fouled": [1, 2],
          "Tackles": [1, 2, 3]}


def fixtures(hours: float, only: set[int] | None):
    now = time.time()
    for f in glob.glob("reports/*.html"):
        if "/pick-" in f:
            continue
        m = re.search(r"const ALL = (\{.*?\});\n", open(f, encoding="utf-8").read(), re.S)
        if not m:
            continue
        for fx in json.loads(m.group(1))["fixtures"]:
            F = fx["fixture"]
            if only:
                if F["id"] in only:
                    yield fx
            elif now - 600 < (F.get("kickoff") or 0) < now + hours * 3600:
                yield fx


def lineup(event_id: int):
    """(confirmed, {side: [starter names]}, {side: [bench names]}) or None."""
    data = api.get_json(f"event/{event_id}/lineups", max_age_hours=0.05, verbose=False)
    if not data:
        return None
    starters, bench = {}, {}
    for side in ("home", "away"):
        players = (data.get(side) or {}).get("players") or []
        starters[side] = [(p.get("player") or {}).get("name") for p in players if not p.get("substitute")]
        bench[side] = [(p.get("player") or {}).get("name") for p in players if p.get("substitute")]
    return bool(data.get("confirmed")), starters, bench


def picks(fx, starting: set[str]):
    out = []
    for ti, recs in enumerate(fx["records"]):
        team = fx["teams"][ti]["name"]
        for st, lines in TEAM.items():
            v = [r["stats"].get("ALL", {}).get(st) for r in recs]
            v = [x for x in v if x is not None][-10:]
            if len(v) < 8:
                continue
            for L in lines:
                k, k5 = sum(x > L for x in v), sum(x > L for x in v[-5:])
                out.append((team, st, f"o{L:g}", k, len(v), k5))
    pl = collections.defaultdict(list)
    for side in fx.get("players") or []:
        for r in side:
            pl[r["player"]].append(r)
    for n, rs in pl.items():
        if n not in starting:
            continue
        rs = sorted([r for r in rs if r.get("minutes", 0) >= 45 and not r.get("former_club")],
                    key=lambda r: r["date"])[-10:]
        if len(rs) < 6:
            continue
        for st, lines in PLAYER.items():
            v = [r["stats"].get(st, 0) or 0 for r in rs]
            for L in lines:
                k, k5 = sum(x >= L for x in v), sum(x >= L for x in v[-5:])
                out.append((n, st, f"{L}+", k, len(v), k5))
    # strong record, holding up lately, and the LONGEST line that still qualifies
    best = {}
    for who, st, line, k, n, k5 in out:
        if 0.7 <= k / n and k5 >= 4:
            key = (who, st)
            p = (k + 2) / (n + 4)
            if key not in best or float(line.strip("o+")) > float(best[key][3].strip("o+")):
                best[key] = (p, who, st, line, k, n, k5)
    return sorted(best.values(), reverse=True)


def update_reports(hours: float) -> None:
    """Refresh line-ups inside every report with a fixture in the window."""
    from pathlib import Path
    import lineup_data
    import report
    now = time.time()
    for f in sorted(glob.glob("reports/*.html")):
        if "/pick-" in f:
            continue
        path = Path(f)
        m = re.search(r"const ALL = (\{.*?\});\n", path.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        payload = json.loads(m.group(1))
        changed = 0
        for entry in payload.get("fixtures", []):
            ko = entry["fixture"].get("kickoff") or 0
            if now - 3 * 3600 < ko < now + hours * 3600:
                before = json.dumps(entry.get("lineups"), sort_keys=True)
                lineup_data.attach(entry, max_age_hours=0.05)
                if json.dumps(entry.get("lineups"), sort_keys=True) != before:
                    changed += 1
        if changed:
            report.write_report(payload, path)
            print(f"  {path.name}: line-ups updated for {changed} fixture(s)")
    print("Now: ./publish.sh")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--event", type=int, action="append")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--update", action="store_true",
                    help="write the latest line-ups into the reports (Line-ups tab), then publish")
    args = ap.parse_args()
    if args.update:
        update_reports(args.hours)
        return
    seen = set()
    for fx in fixtures(args.hours, set(args.event or []) or None):
        F = fx["fixture"]
        if F["id"] in seen:
            continue
        seen.add(F["id"])
        ko = time.strftime("%H:%M", time.localtime(F["kickoff"]))
        print(f"\n== {F['home']} v {F['away']}  {ko}  (event {F['id']})")
        lu = lineup(F["id"])
        if not lu:
            print("   no line-up yet (usually out ~60 min before kick-off)")
            continue
        confirmed, starters, bench = lu
        print("   CONFIRMED" if confirmed else "   PREDICTED, not confirmed: re-run nearer kick-off")
        for side, name in (("home", F["home"]), ("away", F["away"])):
            print(f"   {name}: {', '.join(n for n in starters[side] if n)}")
        starting = {n for s in starters.values() for n in s if n}
        # flag the players the site would have picked who are NOT starting
        stars = collections.Counter()
        for side in fx.get("players") or []:
            for r in side:
                if r.get("minutes", 0) >= 45:
                    stars[r["player"]] += r["stats"].get("Shots", 0) or 0
        benched = [n for n, _ in stars.most_common(8) if n not in starting]
        if benched:
            print(f"   NOT STARTING: {', '.join(benched)}")
        for p, who, st, line, k, n, k5 in picks(fx, starting)[:args.top]:
            print(f"   {p:.0%}  {who:22} {st:18} {line:5} {k}/{n}  last5 {k5}/5")


if __name__ == "__main__":
    main()
