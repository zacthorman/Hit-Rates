#!/usr/bin/env python3
"""Zac's real slips: every bet actually placed, with the price taken, stake and return.

    python slips.py add slips_in.json     # append slips (a list of slip objects, see below)
    python slips.py report                # P&L overall, by book, by bet shape and by kind of leg

bettrack.py tracks the site's own suggestions; this is what was really bet,
so the two can be compared. Each leg is matched to pplog (Paddy's record of
that line) for the player's last-10 record at that line, so the report can
answer questions like "do 10/10 legs at 1.20+ make money for me?".

Slip: {"id": "...", "book": "Sky Bet", "placed": "2026-10-26 22:44", "stake": 5.0,
       "price": 2.10, "returns": 10.48, "result": "win"|"lose"|"void"|"pending",
       "legs": [{"player": "Evan Mobley", "stat": "Assists", "line": 1.5, "over": true,
                 "price": 1.14, "result": "win", "sport": "basketball", "fixture": "..."}]}
A line of "2+" is entered as over 1.5. Results are as the bookmaker settled them.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "slips" / "slips.jsonl"


def load() -> list[dict]:
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def add(path: str) -> None:
    new = json.loads(Path(path).read_text())
    have = {s["id"] for s in load()}
    LOG.parent.mkdir(exist_ok=True)
    n = 0
    with LOG.open("a") as fh:
        for s in new:
            if s["id"] in have:
                continue
            fh.write(json.dumps(s) + "\n")
            n += 1
    print(f"slips: {n} added, {len(have) + n} on record")


def _record(leg: dict, idx: dict):
    """(k10, n10) for this player, stat, line and side from pplog, if Paddy offered it."""
    import pplog
    r = idx.get((pplog._norm(leg["player"]), leg["stat"], float(leg["line"]), bool(leg["over"])))
    return (r["k10"], r["n10"]) if r and r.get("n10") else None


def _index() -> dict:
    import pplog
    idx = {}
    for r in pplog.all_rows():
        if r.get("player"):
            idx[(pplog._norm(r["player"]), r["stat"], float(r["line"]), bool(r["over"]))] = r
    return idx


def report() -> str:
    S = [s for s in load() if s["result"] in ("win", "lose", "void")]
    out = []
    staked = sum(s["stake"] for s in S if s["result"] != "void")
    ret = sum(s["returns"] for s in S if s["result"] != "void")
    out.append(f"{len(S)} settled slips, staked £{staked:.2f}, returned £{ret:.2f}, "
               f"profit £{ret - staked:+.2f} ({(ret - staked) / staked:+.0%} of stakes)" if staked else "no settled slips")
    by = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for s in S:
        if s["result"] == "void":
            continue
        n = len([l for l in s["legs"] if l.get("result") != "void"])
        for key in (f"book: {s.get('book', '?')}", f"shape: {'single' if n == 1 else 'double' if n == 2 else f'{n}-fold'}"):
            by[key][0] += 1; by[key][1] += s["stake"]; by[key][2] += s["returns"]
    for k, (n, st, r) in sorted(by.items()):
        out.append(f"  {k:22s} {n:3d} slips  staked £{st:7.2f}  profit £{r - st:+8.2f}")
    # legs: hit rate against the price taken, by kind
    try:
        idx = _index()
    except Exception:  # noqa: BLE001
        idx = {}
    legs = collections.defaultdict(lambda: [0, 0, 0.0])
    for s in S:
        for l in s["legs"]:
            if l.get("result") not in ("win", "lose"):
                continue
            rec = _record(l, idx)
            band = ("record unknown" if not rec else
                    "record 10/10" if rec[0] == rec[1] else
                    "record 9/10" if rec[0] / rec[1] >= .9 else "record under 90%")
            p = l["price"]
            pb = "under 1.20" if p < 1.2 else "1.20-1.45" if p < 1.46 else "1.46+"
            for key in (f"{'over' if l['over'] else 'under'}", f"{band}", f"{band}, {pb}"):
                legs[key][0] += 1; legs[key][1] += l["result"] == "win"; legs[key][2] += 1 / p
    if legs:
        out.append("\nLegs (landed v what the price needed):")
        for k, (n, w, need) in sorted(legs.items()):
            out.append(f"  {k:32s} {n:3d} legs  landed {w / n:4.0%}  price needed {need / n:4.0%}")
    return "\n".join(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "add":
        add(sys.argv[2])
    else:
        print(report())
