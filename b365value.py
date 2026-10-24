#!/usr/bin/env python3
"""Bet365 football player lines against the player model, with Paddy Power beside them.

    python b365value.py              # every held Bet365 game, value first
    python b365value.py --all        # also lines with no edge

Reads reports/bet365.json (bet365_prices.py), reports/fmodel.json (the
backtested player model, predicted XI until line-ups land, confirmed after)
and reports/paddypower.json. Nothing is fetched.

How to read it (23 Oct 2026):
  * Model is the player model's chance, cut by how far that market's hits have
    fallen short of the model on settled Paddy Power bets (boostcheck's shrink,
    pplog), where there is a record.
  * Edge is that chance times the Bet365 price, minus one.
  * Over 15% is flagged CHECK, not "better": a real edge on a player line is a
    few per cent, and a big one nearly always means the model is missing
    something (a role change, a minutes limit, a player not starting).
  * PP is Paddy Power's price for the same line, so the better book is plain.
  * Mkt is the median price of the other bookmakers Oddschecker lists for the
    same line (n books), and vs Mkt how much longer Bet365 is than that. The
    other books carry their own margin, so Bet365 at or above the median is
    already a good price. A line where the model is ahead AND Bet365 is at
    least as long as the market is tagged BOTH: two independent reasons, the
    strongest kind on this list. (Market data from 23 Oct 2026 fetches on.)
  * Predicted XI until the confirmed XI lands: re-run after line-ups (about an
    hour before kick-off) before betting anything.
Nothing here is proven: the player model's value bets at Paddy Power were
-19% over 97 bets to 22 Oct (papertrade). Track before staking.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pplog  # noqa: E402

TYPES = {"Player Shots": "Shots", "Player Shots On Target": "Shots on target", "Player Fouls": "Fouls",
         "Player Fouls Won": "Fouled", "Player Tackles": "Tackles", "Player Assists": "Assists"}
MAX_PRICE = 8.0
CHECK = 0.15


def _shrink() -> dict:
    try:
        import boostcheck
        return {k: g["shrink"] for k, g in boostcheck._segments(pplog.all_rows()).items() if g["n"] >= 10}
    except Exception:  # noqa: BLE001
        return {}


def _pp_prices() -> dict:
    """(fixture id, player, stat, line) -> Paddy Power over price."""
    out = {}
    try:
        pp = json.loads((ROOT / "reports" / "paddypower.json").read_text())
    except (OSError, ValueError):
        return out
    for fid, ev in (pp.get("events") or {}).items():
        for l in ev.get("lines", []):
            r = pplog.read_line(l)
            if r and r[2]:
                k = (fid, pplog._norm(l.get("player", "")), r[0], r[1])
                out[k] = max(out.get(k, 0), l["price"])
    return out


def rows(show_all: bool = False) -> list[dict]:
    b = json.loads((ROOT / "reports" / "bet365.json").read_text())
    fm = json.loads((ROOT / "reports" / "fmodel.json").read_text()).get("events", {})
    shrink, pp = _shrink(), _pp_prices()
    now, out = time.time(), []
    for fid, e in (b.get("events") or {}).items():
        if e.get("kickoff", 0) < now:
            continue
        fe = fm.get(fid)
        if not fe:
            continue
        players = {pplog._norm(n): (n, v) for n, v in (fe.get("players") or {}).items()}
        for l in e.get("lines", []):
            stat = TYPES.get(l.get("type"))
            if not stat or not l.get("price") or l["price"] > MAX_PRICE:
                continue
            m = re.search(r"(\d+) Or More", l.get("market") or "")
            n = int(m.group(1)) if m else 1
            hit = players.get(pplog._norm(l.get("player", "")))
            if not hit:
                continue
            p = ((hit[1].get("lines") or {}).get(stat) or {}).get(str(n))
            if p is None:
                continue
            ps = p * shrink.get(stat, 1.0)
            edge = ps * l["price"] - 1
            if edge <= 0 and not show_all:
                continue
            med, nb = l.get("mkt_median"), l.get("mkt_n", 0)
            vs = (l["price"] / med - 1) if med else None
            out.append({"mkt": med, "mkt_n": nb, "vs_mkt": vs,
                        "both": bool(vs is not None and nb >= 4 and vs >= 0 and 0 < edge <= CHECK),
                        "fixture": e.get("name"), "kickoff": e["kickoff"], "player": hit[0], "stat": stat,
                        "n": n, "price": l["price"], "model": ps, "raw": p, "edge": edge,
                        "pp": pp.get((fid, hit[0] and pplog._norm(hit[0]), stat, n - 0.5)),
                        "xi": "confirmed" if fe.get("confirmed") else "predicted",
                        "fetched": e.get("fetchedAt")})
    out.sort(key=lambda r: (not r["both"], r["edge"] > CHECK, -r["edge"]))
    return out


def main() -> int:
    show_all = "--all" in sys.argv
    rs = rows(show_all)
    if not rs:
        print("No Bet365 lines with an edge (or no Bet365 games held). Run bet365_prices.py first.")
        return 0
    print(f"{'Edge':>6} {'B365':>5} {'Mkt':>9} {'vsMkt':>6} {'PP':>5} {'Model':>6}  Bet")
    for r in rs:
        flag = "  BOTH" if r["both"] else ("  CHECK" if r["edge"] > CHECK else "")
        pp = f"{r['pp']:.2f}" if r["pp"] else "  -  "
        mk = f"{r['mkt']:.2f}({r['mkt_n']})" if r["mkt"] else "    -    "
        vs = f"{r['vs_mkt']:+.0%}" if r["vs_mkt"] is not None else "  -  "
        ko = time.strftime("%a %H:%M", time.localtime(r["kickoff"]))
        print(f"{r['edge']:+6.0%} {r['price']:5.2f} {mk:>9} {vs:>6} {pp:>5} {r['model']:6.0%}  {r['player']} {r['n']}+ "
              f"{r['stat'].lower()}  ({r['fixture']}, {ko}, {r['xi']} XI){flag}")
    print("\nBOTH: the model is ahead (by 15% or less) and Bet365 is at least the market's median price. "
          "Edge over 15% is marked CHECK: most likely the model is missing something.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
