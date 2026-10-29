#!/usr/bin/env python3
"""Rebuild SLIPS.md from slips/slips.json.

    python slips_md.py

The record holds player-prop slips from the system only (29 Oct 2026): every
leg an NBA or NFL player prop. Team bets and other sports are left out.
"""
import collections
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def band(r):
    if not r or not r.get("n10"):
        return "no record"
    k, n = r["k10"], r["n10"]
    return "10/10" if k == n else "9/10" if k / n >= 0.9 else "7-8/10" if k / n >= 0.7 else "under 7/10"


def shape(s):
    n = len(s["legs"])
    return "Single" if n == 1 else "Double" if n == 2 else "Treble" if n == 3 else "Fold (4+)"


def build() -> str:
    d = json.loads((ROOT / "slips" / "slips.json").read_text())
    S = [s for s in d if s["status"] in ("won", "lost")]
    st = sum(s["stake"] for s in S)
    rt = sum(s["returns"] for s in S)
    order = ["Single", "Double", "Treble", "Fold (4+)"]
    by = collections.OrderedDict((k, [0, 0, 0.0, 0.0]) for k in order)
    kinds, alt, lost = collections.OrderedDict(), collections.OrderedDict(
        (b, [0, 0, 0.0]) for b in ("10/10", "9/10", "7-8/10", "under 7/10", "no record")), []
    for s in S:
        g = by[shape(s)]
        g[0] += 1; g[1] += s["status"] == "won"; g[2] += s["stake"]; g[3] += s["returns"] - s["stake"]
        for l in s["legs"]:
            k = kinds.setdefault(l["kind"], [0, 0, 0.0])
            k[0] += 1; k[1] += l["result"] == "won"; k[2] += l["price"]
            if l["kind"] == "alt over":
                a = alt[band(l.get("record"))]
                a[0] += 1; a[1] += l["result"] == "won"; a[2] += l["price"]
            if l["result"] == "lost":
                lost.append(f"- {l['text']} @ {l['price']:.2f} ({l['kind']}, record {band(l.get('record'))})")
    out = ["# Placed bets (NBA and NFL player slips)", "",
           f"Updated {time.strftime('%d %b %Y %H:%M')}. {len(S)} settled bet(s), staked £{st:.2f}, returned £{rt:.2f}, "
           + (f"**profit £{rt - st:+.2f}** ({(rt - st) / st * 100:+.0f}% of stakes)." if st else ""), "",
           "Only slips where every leg is an NBA or NFL player prop (29 Oct 2026). Team bets and other sports are left out.", "",
           "| Bet type | Bets | Won | Staked | Profit |", "|---|---|---|---|---|"]
    out += [f"| {k} | {g[0]} | {g[1]} | £{g[2]:.2f} | £{g[3]:+.2f} |" for k, g in by.items() if g[0]]
    out += ["", "Legs (each leg counted once per slip; a leg on two slips counts twice):", "",
            "| Kind of leg | Legs | Landed | Avg price | Break-even | Hit rate needed v got |", "|---|---|---|---|---|---|"]
    for k, g in kinds.items():
        hit, ap = g[1] / g[0], g[2] / g[0]
        out.append(f"| {k} | {g[0]} | {hit:.0%} | {ap:.2f} | {1 / ap:.0%} | {(hit - 1 / ap) * 100:+.0f}% |")
    out += ["", "Alt-line overs by the player's last-10 record at that line (Paddy's logged line):", "",
            "| Record | Legs | Landed | Avg price |", "|---|---|---|---|"]
    out += [f"| {b} | {g[0]} | {g[1] / g[0]:.0%} | {g[2] / g[0]:.2f} |" for b, g in alt.items() if g[0]]
    out += ["", "Legs that lost:", ""] + lost
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = build()
    (ROOT / "SLIPS.md").write_text(text)
    print(text)
