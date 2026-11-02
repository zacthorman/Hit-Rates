#!/usr/bin/env python3
"""Tonight's staking plan: which legs, how much, and which to combine.

    python slipkit.py                    # plan for a £100 bank
    python slipkit.py --bank 250         # your bank
    python slipkit.py --hours 30         # how far ahead to look (default 24)

Built 2 Nov 2026 from the backtests (research/BACKTEST-2026-11-02*.md):

  * A stake is only sized on an edge that has a sharp benchmark behind it:
    Pinnacle's margin-free chance at the same line (pplog "sharp",
    pinnacle_props.py). edge = Paddy price x Pinnacle chance - 1.
  * Rules still being tracked (NBA under reversion, drift after a miss) are
    listed at a flat token stake: they have no measured edge yet, and sizing
    them as if they had would be betting the backtest's noise.
  * Size: quarter Kelly, capped at MAX_BET of the bank a bet and MAX_DAY a
    night. Full Kelly is the growth-optimal stake when the edge is known
    exactly; ours is an estimate, and a quarter keeps most of the growth with
    a small fraction of the swings.
  * Combining: a double of two legs with edges e1 and e2 is worth
    (1 + e1)(1 + e2) - 1, so two +4% legs make a +8.2% double, while a +4%
    leg with a -8% banker makes a -4.3% double. Only legs with their own
    edge go into doubles, never one from the same game (Paddy prices
    same-game legs as a bet builder, with its own correlation charge), and
    the double is staked on its own Kelly, which is far smaller than a
    single's because it loses more often.
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

KELLY = 0.25
MAX_BET = 0.02
MAX_DAY = 0.08
MIN_EDGE = 0.03          # a leg needs this much over Pinnacle's fair price to be staked
TOKEN = 0.0025           # tracked rules: 0.25% of the bank, flat
PRICE_RANGE = (1.40, 3.00)
TRACKED = {
    "nba_under_reversion_strong": "Line 0.75+ sd above his 20-game mean (NBA under, tracking)",
    "nba_under_reversion": "Line above his long-run baseline (NBA under, tracking)",
    "nba_alt_drift_miss": "Drift after a miss (NBA alt over, tracking)",
}


def kelly(p: float, price: float) -> float:
    """Full-Kelly fraction for a bet won with chance p at decimal price."""
    b = price - 1
    return max(0.0, (p * b - (1 - p)) / b) if b > 0 else 0.0


def _snap(r: dict) -> dict:
    return r.get("last") or r.get("first") or {}


def edge_of(r: dict):
    """(Pinnacle chance, edge) at this row's latest Paddy price, or None."""
    s = _snap(r)
    sh = s.get("sharp") or (r.get("first") or {}).get("sharp") or {}
    if not sh.get("same") or not sh.get("p") or not s.get("price"):
        return None
    return sh["p"], s["price"] * sh["p"] - 1


def candidates(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(edged legs, tracked legs) among the given unsettled rows."""
    import pplog
    edged, seen = [], set()
    for r in rows:
        price = _snap(r).get("price")
        got = edge_of(r)
        if not got or not price or not PRICE_RANGE[0] <= price <= PRICE_RANGE[1]:
            continue
        p, e = got
        if e < MIN_EDGE:
            continue
        k = (r["event_id"], pplog._norm(r["player"]), r["stat"])
        if k in seen:
            continue
        seen.add(k)
        edged.append(dict(r, _p=p, _edge=e, _price=price))
    edged.sort(key=lambda r: -r["_edge"])
    import ruletrack
    tracked = []
    q = ruletrack.tonight(time.time() - 1, max(r["kickoff"] for r in rows) + 1) if rows else {}
    for rule in TRACKED:
        for r in q.get(rule, []):
            k = (r["event_id"], pplog._norm(r["player"]), r["stat"])
            if k in seen:
                continue
            seen.add(k)
            tracked.append(dict(r, _rule=rule, _price=_snap(r).get("price")))
    return edged, tracked


def plan(edged: list[dict], tracked: list[dict], bank: float) -> dict:
    singles, doubles = [], []
    for r in edged:
        f = min(MAX_BET, KELLY * kelly(r["_p"], r["_price"]))
        singles.append((r, f * bank))
    for a, b in itertools.combinations(edged[:8], 2):
        if a["event_id"] == b["event_id"]:
            continue
        p, price = a["_p"] * b["_p"], a["_price"] * b["_price"]
        e = price * p - 1
        f = min(MAX_BET / 2, KELLY * kelly(p, price))
        if f > 0:
            doubles.append((a, b, price, e, f * bank))
    doubles.sort(key=lambda d: -d[3])
    doubles = doubles[:3]
    flat = [(r, TOKEN * bank) for r in tracked[:6]]
    total = sum(s for _, s in singles) + sum(d[4] for d in doubles) + sum(s for _, s in flat)
    cap = MAX_DAY * bank
    scale = min(1.0, cap / total) if total else 1.0
    return {"singles": [(r, s * scale) for r, s in singles],
            "doubles": [(a, b, pr, e, s * scale) for a, b, pr, e, s in doubles],
            "tracked": [(r, s * scale) for r, s in flat], "scaled": scale < 1, "total": total * scale}


def _leg(r: dict) -> str:
    side = (f"{r['line'] + 0.5:g}+" if r.get("label", "").endswith("+") else
            f"{'over' if r['over'] else 'under'} {r['line']:g}")
    return f"{r['player']} {side} {r['stat'].lower()}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bank", type=float, default=100.0)
    ap.add_argument("--hours", type=float, default=24.0)
    a = ap.parse_args()
    import pplog
    now = time.time()
    rows = [r for r in pplog.all_rows() if r.get("result") is None and r.get("sport") in ("basketball", "american-football")
            and now < (r.get("kickoff") or 0) < now + a.hours * 3600]
    edged, tracked = candidates(rows)
    p = plan(edged, tracked, a.bank)
    print(f"Bank £{a.bank:.0f}. Quarter Kelly, max {MAX_BET:.0%} a bet, {MAX_DAY:.0%} a night"
          + (" (scaled down to the nightly cap)" if p["scaled"] else "") + ".\n")
    if p["singles"]:
        print("Singles: Paddy over Pinnacle's fair price")
        for r, s in p["singles"]:
            print(f"  £{s:5.2f}  {_leg(r):48} @ {r['_price']:.2f}  Pinnacle fair {1 / r['_p']:.2f}  edge {r['_edge']:+.1%}  ({r['fixture']})")
    else:
        print("Singles: none. No Paddy line is 3%+ over Pinnacle's fair price at the same line yet.")
    if p["doubles"]:
        print("\nDoubles: two edged legs, different games")
        for x, y, pr, e, s in p["doubles"]:
            print(f"  £{s:5.2f}  {_leg(x)} + {_leg(y)}  @ {pr:.2f}  edge {e:+.1%}")
    if p["tracked"]:
        print("\nTracked rules, token stakes (no measured edge yet)")
        for r, s in p["tracked"]:
            print(f"  £{s:5.2f}  {_leg(r):48} @ {r['_price']:.2f}  {TRACKED[r['_rule']]}")
    print(f"\nTotal staked: £{p['total']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
