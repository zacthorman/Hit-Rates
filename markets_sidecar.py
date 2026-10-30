"""
Betfair prices the report pages read in the browser: reports/markets.json.

    python markets_sidecar.py

The league reports are built hours before publish.sh fetches exchange prices,
so the prices cannot be baked into the pages. This writes them beside the
reports instead, and each page fetches the file when it opens: the match odds
strip (who is favourite to win) and, on a player profile, Betfair's own price
for the player markets it lists (to score, shots on target 1+ and 2+, shown a
card). Run by publish.sh straight after market_prices.py.

Only prices someone could actually take are kept: a player runner needs a
back price and either a mid price or a lay within 30% of the back. An empty
book on a player market shows a back of 1.01 and means nothing.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import market_prices

HERE = Path(__file__).resolve().parent
OUT = HERE / "reports" / "markets.json"

PLAYER_MARKETS = {"TO_SCORE": "score", "SHOTS_ON_TARGET_P1": "sot1",
                  "SHOTS_ON_TARGET_P2": "sot2", "SHOWN_A_CARD": "card"}


def norm_name(s: str) -> str:
    """Same as normName() in the page: accents off, letters and spaces only."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if c.isascii() and (c.isalpha() or c == " "))
    return " ".join(s.lower().split())


def usable(r: dict):
    back, lay, mid = r.get("back"), r.get("lay"), r.get("price")
    if not back or back < 1.02 or back > 60:
        return None
    if mid is None and not (lay and lay / back <= 1.3):
        return None
    return {"back": back, "mid": round(mid, 3) if mid else None}


def build(data: dict) -> dict:
    events = {}
    for fid, ev in (data.get("events") or {}).items():
        out = {}
        mo = market_prices.match_odds(data, fid)
        if mo:
            m = next(x for x in ev["markets"] if x["type"] == "MATCH_ODDS")
            # Prices to go with the chances, matched to the side by chance.
            def price_for(p):
                for r in m["runners"]:
                    if r.get("p") is not None and abs(r["p"] - p) < 1e-9:
                        return r.get("price") or r.get("back")
                return None
            out["match"] = {
                side: {"p": mo[side], "price": price_for(mo[side])}
                for side in ("home", "draw", "away") if mo.get(side) is not None}
            out["match"]["matched"] = round(mo.get("matched") or 0)
        players = {}
        for m in ev["markets"]:
            key = PLAYER_MARKETS.get(m["type"])
            if not key:
                continue
            for r in m["runners"]:
                u = usable(r)
                if u:
                    players.setdefault(norm_name(r["name"]), {})[key] = u
        if players:
            out["players"] = players
        if out:
            events[fid] = out
    # Paddy Power, when paddypower_prices.py holds any: per player, every line.
    try:
        pp = json.loads((HERE / "reports" / "paddypower.json").read_text())
    except (OSError, ValueError):
        pp = {}
    for fid, e in (pp.get("events") or {}).items():
        by = {}
        for l in e.get("lines", []):
            by.setdefault(l["key"], []).append(
                {"m": l["market"], "s": l.get("selection") or "", "o": l.get("side"),
                 "l": l.get("line"), "p": l["price"]})
        team = e.get("team") or []
        if by or team:
            events.setdefault(fid, {})["pp"] = {"at": e.get("fetchedAt"), "players": by, "team": team,
                                                "goals": e.get("goals") or [],
                                                "home": e.get("ppHome") or "", "away": e.get("ppAway") or ""}
    # Pinnacle's margin-free chances for corners, cards and goals (pinnacle_prices.py),
    # so the pages can show a team line only when Paddy Power beats it (29 Oct 2026).
    try:
        pin = json.loads((HERE / "reports" / "pinnacle.json").read_text())
    except (OSError, ValueError):
        pin = {}
    for fid, e in (pin.get("events") or {}).items():
        rows = [{"stat": l["stat"], "scope": l["scope"], "line": l["line"], "over": l["over"], "p": l["p"]}
                for l in e.get("lines") or [] if l.get("line") is not None and isinstance(l.get("over"), bool)]
        if rows:
            events.setdefault(fid, {})["pin"] = {"at": e.get("fetchedAt"), "name": e.get("name") or "", "lines": rows}
    # Bet365, when bet365_prices.py holds any (via Oddschecker): same shape.
    try:
        b3 = json.loads((HERE / "reports" / "bet365.json").read_text())
    except (OSError, ValueError):
        b3 = {}
    for fid, e in (b3.get("events") or {}).items():
        by = {}
        for l in e.get("lines", []):
            by.setdefault(l["key"], []).append(
                {"m": l["market"], "s": l.get("selection") or "", "o": l.get("side"),
                 "l": l.get("line"), "p": l["price"]})
        team = e.get("team") or []
        if by or team:
            events.setdefault(fid, {})["b365"] = {"at": e.get("fetchedAt"), "players": by, "team": team,
                                                  "home": e.get("ppHome") or "", "away": e.get("ppAway") or ""}
    # Best bookmaker price per line, from Oddschecker pages Zac saved by hand
    # (oddschecker_import.py). Same shape, plus the bookmaker ("b", None when
    # copied text could not say) and how many bookmakers priced it ("n").
    try:
        oc = json.loads((HERE / "reports" / "oddschecker.json").read_text())
    except (OSError, ValueError):
        oc = {}
    for fid, e in (oc.get("events") or {}).items():
        by = {}
        for l in e.get("lines", []):
            by.setdefault(l["key"], []).append(
                {"m": l["market"], "s": l.get("selection") or "", "o": l.get("side"),
                 "l": l.get("line"), "p": l["price"], "b": l.get("book"), "n": l.get("books")})
        if by:
            events.setdefault(fid, {})["oc"] = {"at": e.get("fetchedAt"), "players": by}
    return {"fetched": data.get("fetched"), "events": events}


def main() -> int:
    data = market_prices.load(max_hours=24)
    if not data:
        print("  markets.json not written: no fresh market_prices.json")
        return 0
    OUT.parent.mkdir(exist_ok=True)
    payload = build(data)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    n = len(payload["events"])
    p = sum(len(e.get("players", {})) for e in payload["events"].values())
    q = sum(1 for e in payload["events"].values() if e.get("pp"))
    b = sum(1 for e in payload["events"].values() if e.get("b365"))
    o = sum(1 for e in payload["events"].values() if e.get("oc"))
    print(f"  markets.json: {n} events, {p} Betfair player prices, Paddy Power on {q} game(s), Bet365 on {b}, "
          f"Oddschecker best prices on {o}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
