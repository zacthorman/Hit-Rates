"""Player props for one built report, ranked honestly.

    python player_bets.py reports/minnesota-vikings-v-green-bay-packers.html
    python player_bets.py reports/premier-league.html --floor 1.5 --top 12

Reads a report that already exists. No network, no refetching, and it works on
any sport the report covers, because everything underneath is hit rates and
intervals rather than anything that knows what a corner is.

The ranking is the Wilson lower bound with the z widened for how many
questions were asked. That correction is the point of this script. A round of
player props asks a few hundred separate questions, and the best of a few
hundred sample rates is mostly the luckiest sample: unadjusted, the top of
this list is reliably a fluke off fifteen games. The adjusted figure is the
floor you can actually stand behind.

Two things it prints that are worth reading before the table. A leg whose over
and under both land on the same price is a coin flip wearing a price, and gets
flagged. So does a perfect record, which is true and usually worth nothing --
a book will price twenty from twenty at about 1.05.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import model
import weekend


def load(path: Path) -> tuple[dict, dict]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"const ALL = (\{.*?\});\n", text, re.S)
    if not match:
        raise SystemExit(f"{path} has no payload in it")
    data = json.loads(match.group(1))
    if not data.get("fixtures"):
        raise SystemExit(f"{path} has no fixtures in it")
    return data, data["fixtures"][0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", help="a file under reports/")
    parser.add_argument("--floor", type=float, default=2.0,
                        help="minimum fair price (default 2.0)")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--fixture", type=int, default=0,
                        help="index, for a report holding several fixtures")
    args = parser.parse_args()

    data, _ = load(Path(args.report))
    entry = data["fixtures"][args.fixture]
    fixture = entry["fixture"]
    meta = {"id": fixture.get("id"), "home": fixture.get("home"),
            "away": fixture.get("away"), "competition": fixture.get("competition"),
            "kickoff": fixture.get("kickoff") or 0}

    legs = weekend.player_legs_for(entry, meta)
    if not legs:
        raise SystemExit("no player legs: the report has no player data, or no "
                         "player reaches the minimum sample")

    groups = weekend.group_count(legs)
    z = weekend.selection_z(groups)
    for leg in legs:
        leg["adjusted"] = model.wilson_low(leg["hits"], leg["total"], z=z)

    stale = fixture.get("staleDays")
    print(f"\n{meta['home']} v {meta['away']}  [{meta['competition']}]")
    print(f"{len(legs)} legs from {groups} distinct player/stat questions, z={z:.2f}")
    if stale and stale >= 60:
        print(f"!! the newest match behind these is {stale} days old, so squads "
              f"and roles have moved since")

    # A coin flip and a certainty both price themselves out, in opposite
    # directions. Name them rather than letting them sit in the table looking
    # like findings.
    pairs: dict[tuple, list] = {}
    for leg in legs:
        pairs.setdefault((leg.get("player"), leg["stat"]), []).append(leg)
    flips = [k for k, v in pairs.items()
             if len(v) == 2 and abs(v[0]["fair"] - v[1]["fair"]) < 0.01]
    certain = sorted({leg.get("player") for leg in legs
                      if leg["hits"] == leg["total"] and leg["total"] >= 15})

    def table(title, rows):
        print(f"\n{title}")
        if not rows:
            print("   nothing qualified")
            return
        print(f"   {'player':22} {'pos':5} {'market':30} {'record':>8} "
              f"{'fair':>6} {'floor':>6}")
        for r in rows:
            market = (f"{'over' if r['over'] else 'under'} {r['line']} "
                      f"{r['stat'].lower()}")
            print(f"   {(r.get('player') or '')[:21]:22} "
                  f"{str(r.get('position') or '')[:4]:5} {market[:29]:30} "
                  f"{r['hits']}/{r['total']:<6} {r['fair']:>6.2f} "
                  f"{r['adjusted'] * 100:>5.0f}%")

    priced = [r for r in legs if r["fair"] >= args.floor]
    table(f"BEST AT {args.floor:.2f}+",
          sorted(priced, key=lambda r: -r["adjusted"])[:args.top])
    table("STRONGEST RECORDS, ANY PRICE",
          sorted(legs, key=lambda r: -r["adjusted"])[:args.top])

    if flips:
        print(f"\ncoin flips (over and under priced the same, so the record "
              f"says nothing): {len(flips)}")
        for player, stat in flips[:5]:
            print(f"   {player} {stat.lower()}")
    if certain:
        print(f"\nperfect records, true and close to worthless "
              f"(a book prices these near 1.05): {', '.join(certain[:6])}")

    best = max(priced, key=lambda r: r["adjusted"], default=None)
    if best:
        print(f"\nThe strongest thing at {args.floor:.2f}+ has a floor of "
              f"{best['adjusted'] * 100:.0f}%. Read that as how much the record "
              f"is really worth once the searching is paid for.")


if __name__ == "__main__":
    main()
