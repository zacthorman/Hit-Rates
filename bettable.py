#!/usr/bin/env python3
"""Can this leg actually be bet at Paddy Power?

    python bettable.py            # what tonight's legs would keep and drop, by market

28 Oct 2026, Zac: "only have bets you can actually bet on ... anything
bettable on Paddy is fine". The site prices plenty Paddy Power does not sell
(turnovers, tackles, steals and blocks, team shots by half, offsides), and a
pick nobody can place is noise. So tonight.py keeps a leg only if this says
yes, and shows Paddy's price beside it.

Two ways to say yes:
  * Paddy priced the game (reports/paddypower.json): the exact selection is
    there, same player or side, same stat, same line, same direction, full
    time. The price comes back with it.
  * Paddy has not priced the game yet (it fetches at most 60 games a day,
    nearest first): the market is one Paddy sells in that sport (SELLS
    below, taken from what its feed has returned), so it can be bet once the
    prices are in. No price comes back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PP = ROOT / "reports" / "paddypower.json"

# (sport, player market?) -> stats Paddy sells, full time only. Taken from
# the markets reports/paddypower.json held on 28 Oct 2026 (pplog.read_line
# names) plus the team markets paddypower_prices.TEAM_MARKETS reads.
SELLS = {
    ("football", True): {"Shots", "Shots on target", "Fouls", "Fouled", "Goals", "Card", "Assists"},
    ("football", False): {"Corner kicks", "Yellow cards", "Shots on target", "Fouls", "Total shots", "Goals"},
    ("basketball", True): {"Points", "Rebounds", "Assists", "Three pointers made", "Steals", "Blocks",
                           "Points rebounds and assists", "Points and rebounds", "Points and assists",
                           "Rebounds and assists"},
    ("basketball", False): {"Points"},
    ("american-football", True): {"Receiving yards", "Rushing yards", "Passing yards", "Receiving receptions",
                                  "Rushing and receiving yards", "Passing and rushing yards",
                                  "Passing touchdowns", "Anytime touchdown"},
    ("american-football", False): set(),
    ("baseball", True): {"Hits"},
    ("baseball", False): set(),
}
# Football team markets Paddy sells only for one side (the N+ runner markets)
# or only for the match (goals), not both.
SIDE_ONLY = {"Shots on target", "Fouls", "Total shots"}
MATCH_ONLY = {"Goals"}
# The site's names for the same thing, where they differ from Paddy's.
ALIAS = {"Yellow card": "Card", "Shown a card": "Card", "Booked": "Card", "3 pointers": "Three pointers made"}

# Off only for backtests that replay old fixtures and must stay reproducible
# (parlay_check.py): there is no Paddy Power board for those games.
ON = True

_HITS = re.compile(r"^To Record (\d+)\+ Hits$")


def _norm(s) -> str:
    import sharp
    return sharp.norm(str(s or ""))


def _short(s) -> str:
    import sharp
    return sharp._short(str(s or ""))


def _read_player(l: dict):
    import pplog
    r = pplog.read_line(l)
    if r:
        return r[0], float(r[1]), bool(r[2])
    m = l.get("market") or ""
    g = _HITS.match(m)
    if g:
        return "Hits", int(g.group(1)) - 0.5, True
    if m == "To Record A Hit":
        return "Hits", 0.5, True
    return None


_IX = None


def index(path: Path | None = None) -> dict:
    """fixture id -> {"players": {(name, stat, line, over): price}, "team": {...}, "home", "away"}."""
    global _IX
    if _IX is not None and path is None:
        return _IX
    try:
        data = json.loads((path or PP).read_text())
    except (OSError, ValueError):
        data = {}
    out = {}
    for fid, ev in (data.get("events") or {}).items():
        players, team = {}, {}
        for l in ev.get("lines") or []:
            r = _read_player(l)
            if not r or not l.get("price"):
                continue
            for who in {_norm(l.get("player")), _short(l.get("player"))}:
                if who:
                    k = (who, *r)
                    players[k] = max(players.get(k, 0), l["price"])
        for l in (ev.get("team") or []) + (ev.get("goals") or []):
            if l.get("price"):
                team[(l["scope"], l["stat"], float(l["line"]), bool(l["over"]))] = l["price"]
        out[str(fid)] = {"players": players, "team": team, "home": ev.get("ppHome") or "",
                         "away": ev.get("ppAway") or "", "name": ev.get("name") or ""}
    if path is None:
        _IX = out
    return out


def _stat(leg) -> str:
    s = leg.get("stat") or ""
    return ALIAS.get(s, s)


def _line(leg):
    if leg.get("alt") and leg.get("threshold") is not None:
        return float(leg["threshold"]) - 0.5, True
    if leg.get("line") is None:
        return None, None
    return float(leg["line"]), bool(leg.get("over"))


def _scope(leg, meta, ev) -> str | None:
    team = leg.get("team")
    if not team or _norm(team) in ("match", "both teams", ""):
        return "match"
    t = set(_norm(team).split())
    for scope, name in (("home", ev.get("home")), ("away", ev.get("away"))):
        if name and t & set(_norm(name).split()):
            return scope
    if team == meta.get("home"):
        return "home"
    if team == meta.get("away"):
        return "away"
    return None


def check(leg: dict, meta: dict, sport: str) -> tuple[bool, float | None]:
    """(bettable at Paddy Power, Paddy's price when it has priced the game)."""
    if not ON:
        return True, None
    if (leg.get("period") or "ALL") != "ALL":
        return False, None
    is_player = bool(leg.get("player"))
    stat = _stat(leg)
    if stat not in SELLS.get((sport, is_player), set()):
        return False, None
    line, over = _line(leg)
    if line is None:
        return False, None
    ev = index().get(str(meta.get("id")))
    if is_player:
        if not ev or not ev["players"]:
            return True, None
        for who in (_norm(leg["player"]), _short(leg["player"])):
            p = ev["players"].get((who, stat, line, over))
            if p:
                return True, p
        return False, None
    scope = _scope(leg, meta, ev or {})
    if sport == "football":
        if scope == "match" and stat in SIDE_ONLY or scope != "match" and stat in MATCH_ONLY:
            return False, None
    if not ev or not ev["team"]:
        return True, None
    p = ev["team"].get((scope, stat, line, over)) if scope else None
    return (True, p) if p else (False, None)


def ok(leg: dict, meta: dict, sport: str) -> bool:
    return check(leg, meta, sport)[0]


def recorded_ok(leg: dict) -> bool:
    """For a leg as besttrack.py records it (event_id, fixture 'A v B', sport)."""
    home, _, away = (leg.get("fixture") or "").partition(" v ")
    return ok(leg, {"id": leg.get("event_id"), "home": home, "away": away}, leg.get("sport") or "football")


def keep(legs: list[dict], meta: dict, sport: str) -> list[dict]:
    """The legs Paddy Power will take, each with its Paddy price (pp_price) when known."""
    out = []
    for l in legs:
        ok, price = check(l, meta, sport)
        if ok:
            l["pp_price"] = price
            out.append(l)
    return out


def main() -> None:
    import collections
    import time
    import make_index
    import tonight
    import weekend
    kept, dropped = collections.Counter(), collections.Counter()
    now = time.time()
    for path in sorted((ROOT / "reports").glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        for entry, meta in make_index.read_entries(path):
            if not now < meta["kickoff"] < now + 12 * 3600:
                continue
            sport = weekend.sport_of(entry)
            for l in tonight.legs_of(entry, meta, filter_bettable=False):
                k = (sport, "player" if l.get("player") else "team", _stat(l), l.get("period") or "ALL")
                (kept if check(l, meta, sport)[0] else dropped)[k] += 1
    for name, c in (("KEPT", kept), ("DROPPED", dropped)):
        print(name)
        for k, v in c.most_common():
            print(f"  {v:5}  {' | '.join(k)}")


if __name__ == "__main__":
    main()
