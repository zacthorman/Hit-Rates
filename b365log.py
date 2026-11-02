#!/usr/bin/env python3
"""The Bet365 record: every Bet365 player line, our chance, and the result.

    python b365log.py snapshot   # log every held Bet365 line (publish.sh)
    python b365log.py settle     # settle what has finished (publish.sh)
    python b365log.py report     # the record so far, as text

Added 2 Nov 2026. Bet365's player prices were on the pages (bet365_prices.py,
via Oddschecker) but never logged or settled, so nothing could say whether a
Bet365 bet won. This is pplog.py pointed at Bet365's files, so the two
records are kept the same way and the same rules can be tested on both:

  * prices from reports/bet365.json, rows to b365log/ (one JSON-lines file a
    month, gitignored like pplog/), each row tagged "book": "b365";
  * our chance is the same as pplog's (the player model, the site's record),
    with Bet365's Sub On Play On on the lines it covers (supersub.py,
    B365_MAX_LINE and B365_COMPETITIONS): shots, shots on target, fouls,
    fouled, tackles, assists, cards and goals, the starter's count carrying
    over to his replacement;
  * settled from SofaScore as pplog settles, Sub On Play On included;
  * lines no Paddy Power record has tested (tackles, and lines above Paddy's
    top one, such as 7+ shots) are marked "untested" and never called value.

Bet365 only qualifies a game when it shows the Sub On Play On icon, which
Oddschecker does not pass through, so the competition list decides here.
Check the icon on the slip before staking.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pplog  # noqa: E402

DIR = ROOT / "b365log"
PRICES = ROOT / "reports" / "bet365.json"


def use_bet365() -> None:
    """Point pplog at Bet365's files. Everything after this reads and writes
    b365log/, never pplog/."""
    pplog.DIR = DIR
    pplog.PP = PRICES
    pplog.PAGE = ROOT / "b365-results.html"
    pplog.BOOK = "b365"
    pplog.BOOK_NAME = "Bet365"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["snapshot", "settle", "report"])
    a = ap.parse_args(argv)
    use_bet365()
    {"snapshot": pplog.snapshot, "settle": pplog.settle, "report": pplog.report}[a.cmd]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
