#!/usr/bin/env python3
"""NBA blowout projection for the rules on trial (ruletrack.py).

    python blowout.py tonight     # print each upcoming game's projected margin and starters

Why (28 Oct 2026): in the report's box scores (28 teams, last 20 games each),
starters on the LOSING side of a 15+ point game scored 20% fewer points and
21% fewer points, rebounds and assists than in games decided by under 10
(ranges -14% to -26% and -16% to -26%). Starters on the WINNING side lost 16%
of their minutes but nothing in output: they put the numbers up before they
sat. So the under to take in a likely blowout is the underdog's starters',
not the favourite's.

The projection is deliberately simple and needs nothing logged in advance, so
the same number can be rebuilt for games already played:

  margin = home's average margin over its last 10 games
         - away's average margin over its last 10 games
         + 2.5 for home court

positive means the home side is favoured. A "starter" is a player who started
3 or more of his team's 5 games before this one. Both are read from the NBA
report's box scores (reports/nba.html) and saved, the first time they are
worked out, to pplog/blowout.json, so a game keeps its projection after it
rolls out of the report's last 20.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "reports" / "nba.html"
STORE = ROOT / "pplog" / "blowout.json"
HOME_COURT = 2.5
FORM_GAMES = 10
MIN_FORM = 5

_DATA = None


def _report() -> dict:
    """The NBA report's data: team records and player box scores, by team."""
    global _DATA
    if _DATA is not None:
        return _DATA
    recs: dict[str, dict] = {}
    players: dict[str, dict] = {}
    if REPORT.exists():
        text = REPORT.read_text()
        m = re.search(r"^const ALL = ", text, flags=re.M)
        if m:
            raw = text[m.end():text.find("\n", m.end())].rstrip().rstrip(";")
            for f in json.loads(raw).get("fixtures", []):
                for side, rec, pl in zip(f.get("teams", []), f.get("records", []), f.get("players", [])):
                    t = side["name"]
                    for r in rec:
                        recs.setdefault(t, {})[r["id"]] = r
                    for p in pl:
                        players.setdefault(t, {})[(p["player"], p["match_id"])] = p
    _DATA = {"recs": recs, "players": players}
    return _DATA


def _form(team: str, before: str):
    rs = sorted((r for r in _report()["recs"].get(team, {}).values() if r["date"] < before),
                key=lambda r: r["date"], reverse=True)[:FORM_GAMES]
    if len(rs) < MIN_FORM:
        return None
    return sum(r["goals_for"] - r["goals_against"] for r in rs) / len(rs)


def _starters(team: str, before: str) -> list[str]:
    games = sorted({(p["date"], p["match_id"]) for p in _report()["players"].get(team, {}).values()
                    if p["date"] < before}, reverse=True)[:5]
    ids = {g[1] for g in games}
    count: dict[str, int] = {}
    for p in _report()["players"].get(team, {}).values():
        if p["match_id"] in ids and p.get("started"):
            count[p["player"]] = count.get(p["player"], 0) + 1
    return sorted(n for n, c in count.items() if c >= 3)


def _load() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return {}


def _save(store: dict) -> None:
    try:
        STORE.parent.mkdir(exist_ok=True)
        STORE.write_text(json.dumps(store, indent=0, sort_keys=True))
    except OSError:
        pass


_STORE = None


def projection(event_id, fixture: str, kickoff: float):
    """{home, away, margin, starters: {team: [names]}} or None if a side has too little form."""
    global _STORE
    if _STORE is None:
        _STORE = _load()
    key = str(event_id)
    if key in _STORE:
        return _STORE[key]
    if " v " not in fixture:
        return None
    home, away = fixture.split(" v ", 1)
    day = datetime.datetime.fromtimestamp(kickoff, datetime.timezone.utc).strftime("%Y-%m-%d")
    fh, fa = _form(home, day), _form(away, day)
    if fh is None or fa is None:
        return None
    out = {"home": home, "away": away, "margin": round(fh - fa + HOME_COURT, 2),
           "starters": {home: _starters(home, day), away: _starters(away, day)}}
    _STORE[key] = out
    _save(_STORE)
    return out


def underdog_starter(row: dict, min_margin: float):
    """(margin, True) if row's player starts for the projected underdog by min_margin or more."""
    p = projection(row["event_id"], row.get("fixture", ""), row.get("kickoff") or 0)
    if not p or abs(p["margin"]) < min_margin:
        return None
    dog = p["away"] if p["margin"] > 0 else p["home"]
    if row.get("team") != dog:
        return None
    norm = lambda s: re.sub(r"[^a-z]", "", s.lower())
    if norm(row.get("player", "")) not in {norm(n) for n in p["starters"].get(dog, [])}:
        return None
    return abs(p["margin"])


if __name__ == "__main__":
    import time
    sys.path.insert(0, str(ROOT))
    import pplog
    now = time.time()
    seen = set()
    for r in pplog.all_rows():
        if r.get("sport") != "basketball" or not (now < (r.get("kickoff") or 0) < now + 24 * 3600):
            continue
        if r["event_id"] in seen:
            continue
        seen.add(r["event_id"])
        p = projection(r["event_id"], r["fixture"], r["kickoff"])
        if not p:
            print(f"{r['fixture']}: not enough form")
            continue
        fav = p["home"] if p["margin"] > 0 else p["away"]
        dog = p["away"] if p["margin"] > 0 else p["home"]
        print(f"{time.strftime('%a %H:%M', time.localtime(r['kickoff']))}  {r['fixture']:45} "
              f"{fav} by {abs(p['margin']):.1f}  underdog starters: {', '.join(p['starters'][dog])}")
