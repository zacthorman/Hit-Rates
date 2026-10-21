"""Print only Bet365's prices (Oddschecker code B3) for the given market IDs.

  python3 bet365_odds.py 3587987298 3587890557
  python3 bet365_odds.py <ids> --book B3 --book PP     # more than one bookmaker
"""

from __future__ import annotations

import argparse
from collections import Counter

from oddschecker_client import OddscheckerClient


def main():
    p = argparse.ArgumentParser()
    p.add_argument("market_ids", nargs="+")
    p.add_argument("--book", action="append", help="Oddschecker bookmaker code, default B3 (Bet365)")
    args = p.parse_args()
    books = set(args.book or ["B3"])

    with OddscheckerClient() as c:
        markets = c.get_many(args.market_ids)

    for m in markets:
        bets = {b.get("betId"): b for b in m.get("bets", []) if isinstance(b, dict)}
        rows = [
            o for o in m.get("odds", [])
            if o.get("bookmakerCode") in books and o.get("status") == "ACTIVE" and o.get("oddsDecimal")
        ]
        print(f"\n{m.get('marketName', '?')}  ({m.get('subeventStartTime', '')})")
        if not rows:
            seen = Counter(o.get("bookmakerCode") for o in m.get("odds", []))
            print(f"  no {', '.join(sorted(books))} prices. Codes in this market: {', '.join(sorted(seen))}")
            continue
        def label(o):
            b = bets.get(o.get("betId"), {})
            name = (b.get("betName") or "?").replace(" Over", "")
            line = b.get("line")
            plus = f"{int(float(line) + 0.5)}+" if line else ""
            return name, plus, b.get("bestOddsDecimal")

        for o in sorted(rows, key=lambda o: (label(o)[0], label(o)[1])):
            name, plus, best = label(o)
            flag = "  best" if best and o["oddsDecimal"] >= best else f"  (best {best})" if best else ""
            print(f"  {o['oddsDecimal']:>7}  {name} {plus}{flag}")


if __name__ == "__main__":
    main()
