#!/usr/bin/env python3
"""Does the Betfair connection work, and which markets does it carry?

    .venv/bin/python betfair_probe.py               # next 48h of football
    .venv/bin/python betfair_probe.py "Sao Paulo"   # one fixture by name
    .venv/bin/python betfair_probe.py --nfl

Logs in, lists upcoming fixtures, then for the first few prints every market
type with live back/lay prices. That answers the only question that matters
before building on it: are the markets the site picks (shots on target,
corners, cards, player props) actually on the exchange?
"""
import collections
import sys

import betfair_api as bf

args = [a for a in sys.argv[1:] if not a.startswith("--")]
sport = bf.AMERICAN_FOOTBALL if "--nfl" in sys.argv else bf.FOOTBALL
text = args[0] if args else None

bf.login()
print("logged in")
evs = bf.events(sport, hours=48, text=text)
print(f"{len(evs)} fixture(s) in the next 48 hours" + (f" matching {text!r}" if text else ""))
evs.sort(key=lambda e: e.get("openDate", ""))
types = collections.Counter()
for e in evs[:3 if not text else 1]:
    print(f"\n== {e['name']}  {e.get('openDate', '')}  ({e.get('marketCount')} markets)")
    cat = bf.markets(e["id"])
    books = {b["marketId"]: bf.best(b) for b in bf.prices([m["marketId"] for m in cat])}
    for m in sorted(cat, key=lambda m: m["marketName"]):
        mtype = (m.get("description") or {}).get("marketType", "?")
        types[mtype] += 1
        prices = books.get(m["marketId"], {})
        runners = ", ".join(
            f"{r['runnerName']} {prices.get(r['selectionId'], (None,))[0] or '-'}"
            for r in m.get("runners", [])[:4])
        print(f"   {mtype:28} {m['marketName'][:40]:40} {runners}")
print("\nmarket types seen:", ", ".join(f"{k} ({v})" for k, v in types.most_common()))
