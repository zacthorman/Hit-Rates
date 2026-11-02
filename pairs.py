#!/usr/bin/env python3
"""Same-game pairs: what a two-leg bet builder is really worth.

    python pairs.py scan                  # tonight's NBA/NFL pairs that land together most
    python pairs.py scan --hours 30
    python pairs.py check "Pascal Siakam|Points|19.5|over" "Pascal Siakam|Three pointers made|1.5|over"

A bet builder of two legs that tend to land together is worth more than the
two prices multiplied, so it is value whenever the book charges less for the
link than it is really worth. LIFT below is how much more often each kind of
pair landed together than independence says, measured out of sample on the
box scores (2 Nov 2026, research/PAIRS-2026-11-02.md): each player's line set
at his own last-20 median, the link from his earlier games, scored on the
next game.

  NBA, the same player:  points + threes 1.27, points + rebounds 1.10,
                         assists + rebounds 1.07, points + assists 1.06
  NBA, team-mates:       about independent (1.00 to 1.04)
  NFL, team-mates:       QB passing yards + a receiver's yards 1.29, + his
                         catches 1.17; QB passing + the running back's
                         rushing yards 0.91 (they pull apart)
  NFL, the same player:  catches + receiving yards 1.63

A pair's own history (twenty shared games) did not predict better than the
kind of pair it is, so only these kind-level figures are used.

Each leg's chance is Pinnacle's margin-free one at the same line where
pplog has it (sharp), else the margin-free Paddy main line, else Paddy's
alt price less a typical 7% alt margin. The fair builder price is
1 / P(both); Paddy's builder at that price or longer is value. The lifts
were measured at median lines: on far rungs (25+ points from a 17-point
scorer) the link is usually stronger, so the fair price is if anything a
little long there.
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SAME = {   # same player, both overs
    ("basketball", "Points", "Three pointers made"): 1.27,
    ("basketball", "Points", "Rebounds"): 1.10,
    ("basketball", "Assists", "Rebounds"): 1.07,
    ("basketball", "Assists", "Points"): 1.06,
    ("basketball", "Assists", "Three pointers made"): 1.03,
    ("basketball", "Rebounds", "Three pointers made"): 1.03,
    ("american-football", "Receiving receptions", "Receiving yards"): 1.63,
    ("american-football", "Passing yards", "Rushing yards"): 1.04,
}
MATES = {  # team-mates, both overs
    ("basketball", "Assists", "Points"): 1.035,
    ("american-football", "Passing yards", "Receiving yards"): 1.29,
    ("american-football", "Passing yards", "Receiving receptions"): 1.17,
    ("american-football", "Passing yards", "Rushing yards"): 0.91,
}
# Links every book prices in (one stat is mostly the other): shown by check,
# left out of scan so it lists the pairs worth asking Paddy's builder about.
OBVIOUS = {("american-football", "Receiving receptions", "Receiving yards")}
ALT_MARGIN = 0.07
MIN_LIFT = 1.10          # scan: pairs worth a look


def lift(sport: str, a: dict, b: dict) -> float:
    same = a["player"] == b["player"]
    if not same and a.get("team") != b.get("team"):
        return 1.0
    k = (sport,) + tuple(sorted((a["stat"], b["stat"])))
    return (SAME if same else MATES).get(k, 1.0)


def joint(pa: float, pb: float, a_over: bool, b_over: bool, L: float) -> float:
    """P(both legs win) from the two OVER chances and the over/over lift."""
    both_over = min(pa, pb, pa * pb * L)
    if a_over and b_over:
        return both_over
    if a_over and not b_over:
        return max(0.0, pa - both_over)
    if b_over and not a_over:
        return max(0.0, pb - both_over)
    return max(0.0, 1 - pa - pb + both_over)


def over_chance(r: dict, rows_by_key: dict):
    """Chance the OVER of this row's line lands: Pinnacle, else Paddy's two
    sides margin-free, else the alt price less ALT_MARGIN."""
    s = r.get("last") or r.get("first") or {}
    sh = s.get("sharp") or {}
    if sh.get("same") and sh.get("p"):
        return sh["p"] if r["over"] else 1 - sh["p"]
    other = rows_by_key.get((r["event_id"], r["player"], r["stat"], r["line"], not r["over"]))
    if other:
        a, b = 1 / s["price"], 1 / ((other.get("last") or other["first"])["price"])
        p = a / (a + b)
        return p if r["over"] else 1 - p
    if r["over"] and s.get("price"):
        return min(0.97, (1 / s["price"]) / (1 + ALT_MARGIN))
    return None


def _price(r):
    return (r.get("last") or r.get("first") or {}).get("price")


def scan(rows: list[dict], top: int = 12) -> list[dict]:
    by_key = {(r["event_id"], r["player"], r["stat"], r["line"], r["over"]): r for r in rows}
    by_game: dict = {}
    for r in rows:
        if _price(r) and 1.3 <= _price(r) <= 3.5:
            by_game.setdefault(r["event_id"], []).append(r)
    out = []
    for gid, legs in by_game.items():
        sport = legs[0]["sport"]
        for a, b in itertools.combinations(legs, 2):
            if a["player"] == b["player"] and a["stat"] == b["stat"]:
                continue
            if a["player"] == b["player"] and (sport,) + tuple(sorted((a["stat"], b["stat"]))) in OBVIOUS:
                continue
            L = lift(sport, a, b)
            if (L if a["over"] == b["over"] else 1 / L) < MIN_LIFT:
                continue
            pa, pb = over_chance(dict(a, over=True), by_key), over_chance(dict(b, over=True), by_key)
            if pa is None or pb is None:
                continue
            pj = joint(pa, pb, a["over"], b["over"], L)
            if pj <= 0:
                continue
            pa_side = pa if a["over"] else 1 - pa
            pb_side = pb if b["over"] else 1 - pb
            out.append({"a": a, "b": b, "lift": L, "p": pj, "fair": 1 / pj,
                        "multiplied": _price(a) * _price(b), "indep": 1 / (pa_side * pb_side)})
    # one entry per player pair, best link first, then the shortest fair price
    out.sort(key=lambda x: (-x["lift"], x["fair"]))
    seen, keep = set(), []
    for x in out:
        k = (x["a"]["event_id"], x["a"]["player"], x["b"]["player"], x["a"]["stat"], x["b"]["stat"])
        if k in seen:
            continue
        seen.add(k)
        keep.append(x)
    return keep[:top]


def _leg(r: dict) -> str:
    side = f"{r['line'] + 0.5:g}+" if (r.get("label") or "").endswith("+") else \
        f"{'over' if r['over'] else 'under'} {r['line']:g}"
    return f"{r['player']} {side} {r['stat'].lower()}"


def _rows(hours: float):
    import pplog
    now = time.time()
    return [r for r in pplog.all_rows() if r.get("result") is None and r.get("sport") in ("basketball", "american-football")
            and now < (r.get("kickoff") or 0) < now + hours * 3600]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--hours", type=float, default=24)
    s.add_argument("--top", type=int, default=12)
    c = sub.add_parser("check")
    c.add_argument("legs", nargs=2, help='"Player|Stat|line|over or under"')
    c.add_argument("--hours", type=float, default=36)
    a = ap.parse_args()
    rows = _rows(a.hours)
    if a.cmd == "scan":
        got = scan(rows, a.top)
        if not got:
            print("No same-game pairs with a strong link and prices on both legs yet.")
        for x in got:
            print(f"{x['a']['fixture']}\n  {_leg(x['a'])} + {_leg(x['b'])}\n"
                  f"  legs multiplied {x['multiplied']:.2f}, fair builder {x['fair']:.2f} "
                  f"(link x{x['lift']:.2f}): Paddy's builder at {x['fair']:.2f} or longer is value\n")
        return 0
    by_key = {(r["event_id"], r["player"], r["stat"], r["line"], r["over"]): r for r in rows}
    legs = []
    for spec in a.legs:
        try:
            player, stat, line, side = [x.strip() for x in spec.split("|")]
            line, over = float(line), side.lower().startswith("o")
        except ValueError:
            print(f"could not read {spec!r}: use \"Player|Stat|19.5|over\"")
            return 1
        m = next((r for r in rows if r["player"].lower() == player.lower() and r["stat"].lower() == stat.lower()
                  and abs(r["line"] - line) < 1e-9), None)
        if not m:
            print(f"no Paddy line logged for {spec}")
            return 1
        legs.append(dict(m, over=over))
    x, y = legs
    if x["event_id"] != y["event_id"]:
        print("different games: a normal double, priced at the two prices multiplied")
        return 0
    L = lift(x["sport"], x, y)
    pa, pb = over_chance(dict(x, over=True), by_key), over_chance(dict(y, over=True), by_key)
    pj = joint(pa, pb, x["over"], y["over"], L)
    print(f"{_leg(x)}: chance {pa if x['over'] else 1 - pa:.0%}\n{_leg(y)}: chance {pb if y['over'] else 1 - pb:.0%}\n"
          f"link x{L:.2f} -> both {pj:.0%}, fair builder {1 / pj:.2f} "
          f"(independent would be {1 / ((pa if x['over'] else 1 - pa) * (pb if y['over'] else 1 - pb)):.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
