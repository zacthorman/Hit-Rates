#!/usr/bin/env python3
"""Pinnacle's NBA and NFL player props, as fair chances, to judge Paddy Power's.

    python pinnacle_props.py            # the normal run (publish.sh calls it)
    python pinnacle_props.py --probe    # one league, prints the raw shapes that came back
    python pinnacle_props.py --status   # what is held, requests used today

Why (2 Nov 2026, research/BACKTEST-2026-11-02*.md): on Paddy Power's own
prices nothing about a player's form or matchup beat the book reliably, and
Paddy's own price moves carried no information (lines that shortened at Paddy
lost more, -17% NBA). The method professionals use is a sharp benchmark: bet
the soft book only when its price is longer than the sharp book's margin-free
chance. On football team markets that split was already +0.4% (Paddy at or
over Pinnacle) against -7.7% (under it), and cards +18%. This brings the same
benchmark to NBA and NFL player lines; pplog.py records it beside every Paddy
line ("sharp") and ruletrack.py scores the rule (props_beat_pinnacle).

Same feed, same manners as pinnacle_prices.py (Pinnacle's own site's guest
API; undocumented, and reading it is against Pinnacle's terms, so: per
league, not per game, paced, capped, a refusal locks it out, and
`touch .pinnacle_off` switches both off). Its own request count, so the
football fetch keeps its budget.

Writes reports/pinnacle_props.json:
    {"events": {pinGameId: {"name", "home", "away", "kickoff", "sport", "fid",
                            "fetchedAt", "props": [{"player", "stat", "line",
                            "over", "price", "p"}]}}, "updated"}
stat uses pplog's names (Points, Rebounds, ...); p is margin-free (over and
under of one line normalised). fid is the site's fixture id when matched.

The shapes below were written from what the guest API is known to return
(specials with special.category "Player Props" and a "Name (Stat)"
description, Over/Under participants, prices in American odds). Run --probe
once: it prints the categories, descriptions and market shapes it sees, so a
renamed field shows up at once rather than as an empty file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pinnacle_prices as PP  # noqa: E402  (headers, pacing, decimal(), lockouts)

OUT = ROOT / "reports" / "pinnacle_props.json"
STATE = ROOT / "cache" / "pinnacle_props_state.json"
MAX_PER_DAY = 120
MAX_RELATED = 16          # per-game lookups per run, only when the league call lacks prices
FRESH_HOURS = 1.0
WINDOW_HOURS = 36
SPORTS = {   # site sport -> (Pinnacle sport id, league name, fallback league id)
    "basketball": (4, "NBA", 487),
    "american-football": (15, "NFL", 889),
}

# Pinnacle's stat words -> pplog's names. Matched on the lower-cased text in
# brackets; anything unmatched is kept out and listed by --probe.
STATS = {
    "basketball": [
        (r"^(pts|points)\s*\+\s*(rebs?|rebounds)\s*\+\s*(asts?|assists)$", "Points rebounds and assists"),
        (r"^(pts|points)\s*\+\s*(rebs?|rebounds)$", "Points and rebounds"),
        (r"^(pts|points)\s*\+\s*(asts?|assists)$", "Points and assists"),
        (r"^(rebs?|rebounds)\s*\+\s*(asts?|assists)$", "Rebounds and assists"),
        (r"^points$", "Points"),
        (r"^rebounds$", "Rebounds"),
        (r"^assists$", "Assists"),
        (r"^(3 point fg|3-point fg|threes|3pt made|three point fg|3 pointers made)$", "Three pointers made"),
        (r"^steals$", "Steals"),
        (r"^blocks$", "Blocks"),
    ],
    "american-football": [
        (r"^(passing yards|pass yards)$", "Passing yards"),
        (r"^(rushing yards|rush yards)$", "Rushing yards"),
        (r"^(receiving yards|rec yards)$", "Receiving yards"),
        (r"^(receptions)$", "Receiving receptions"),
        (r"^(pass(ing)? \+ rush(ing)? yards|passing and rushing yards)$", "Passing and rushing yards"),
        (r"^(rush(ing)? \+ rec(eiving)? yards|rushing and receiving yards)$", "Rushing and receiving yards"),
        (r"^(td passes|passing touchdowns|pass tds)$", "Passing touchdowns"),
    ],
}
DESC = re.compile(r"^\s*(.+?)\s*\(([^)]+)\)\s*$")


def stat_of(sport: str, text: str):
    t = " ".join(text.lower().replace("’", "'").split())
    for pat, name in STATS.get(sport, []):
        if re.match(pat, t):
            return name
    return None


def parse_special(m: dict, sport: str):
    """(player, stat, {participantId: 'over'|'under'}, parentId) or None."""
    sp = m.get("special") or {}
    if "player" not in str(sp.get("category", "")).lower():
        return None
    got = DESC.match(str(sp.get("description") or m.get("description") or ""))
    if not got:
        return None
    player, stat = got.group(1), stat_of(sport, got.group(2))
    if not stat:
        return None
    sides = {}
    for p in m.get("participants") or []:
        nm = str(p.get("name", "")).lower()
        if nm in ("over", "under"):
            sides[p.get("id")] = nm
    if len(sides) != 2:
        return None
    parent = (m.get("parent") or {}).get("id") or m.get("parentId")
    return player, stat, sides, parent


def props_of(market: dict, sides: dict, player: str, stat: str) -> list[dict]:
    """A special's straight market -> over/under rows with margin-free chances."""
    if market.get("period", 0) != 0 or market.get("status", "open") != "open":
        return []
    by_line: dict = {}
    for pr in market.get("prices") or []:
        side = sides.get(pr.get("participantId")) or str(pr.get("designation", "")).lower()
        d = PP.decimal(pr.get("price"))
        pts = pr.get("points")
        if side not in ("over", "under") or not d or pts is None:
            continue
        by_line.setdefault(float(pts), {})[side] = d
    out = []
    for line, two in by_line.items():
        if len(two) != 2:
            continue
        book = sum(1 / d for d in two.values())
        for side, d in two.items():
            out.append({"player": player, "stat": stat, "line": line, "over": side == "over",
                        "price": round(d, 3), "p": round((1 / d) / book, 4)})
    return out


def _game(parent: dict | None):
    if not parent:
        return None
    ps = parent.get("participants") or []
    home = next((p.get("name") for p in ps if p.get("alignment") == "home"), None)
    away = next((p.get("name") for p in ps if p.get("alignment") == "away"), None)
    try:
        ko = datetime.fromisoformat(parent["startTime"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError, AttributeError):
        ko = None
    return home, away, ko


def league_id(st: dict, sport: str) -> int | None:
    sid, name, fallback = SPORTS[sport]
    key = f"league_{sport}"
    if st.get(key + "_on") == PP.today() and st.get(key):
        return st[key]
    got = PP.get(f"/sports/{sid}/leagues?all=false", st)
    lid = next((l.get("id") for l in got if isinstance(l, dict) and l.get("name") == name), None) or fallback
    st[key], st[key + "_on"] = lid, PP.today()
    return lid


def run(probe: bool = False) -> int:
    if PP.OFF.exists():
        print("  pinnacle props: switched off (.pinnacle_off)")
        return 0
    PP.MAX_PER_DAY = MAX_PER_DAY            # this feed's own cap
    st = _load()
    if st.get("lockedUntil", 0) > time.time():
        print(f"  pinnacle props: locked out ({st.get('lockedWhy')})")
        return 0
    try:
        out = json.loads(OUT.read_text())
    except (OSError, ValueError):
        out = {"events": {}}
    held = out.setdefault("events", {})
    now = time.time()
    for k in [k for k, e in held.items() if (e.get("kickoff") or 0) < now - 3 * 3600]:
        held.pop(k)
    try:
        import bet365_prices
        events = bet365_prices.load_events()
    except Exception:  # noqa: BLE001
        events = {}
    got = related = 0
    try:
        for sport in SPORTS:
            if not probe and now - st.setdefault("at", {}).get(sport, 0) < FRESH_HOURS * 3600:
                continue
            lid = league_id(st, sport)
            ms = PP.get(f"/leagues/{lid}/matchups", st)
            mk = PP.get(f"/leagues/{lid}/markets/straight", st)
            st.setdefault("at", {})[sport] = time.time()
            ms = ms if isinstance(ms, list) else []
            mk = mk if isinstance(mk, list) else []
            by_m: dict = {}
            for x in mk:
                by_m.setdefault(x.get("matchupId"), []).append(x)
            specials = [m for m in ms if m.get("type") == "special"]
            if probe:
                print(f"\n== {sport} league {lid}: {len(ms)} matchups ({len(specials)} specials), {len(mk)} markets")
                print("  categories:", sorted({str((m.get('special') or {}).get('category')) for m in specials}))
                print("  descriptions:", [str((m.get('special') or {}).get('description')) for m in specials][:25])
                s0 = next((m for m in specials if "player" in str((m.get("special") or {}).get("category", "")).lower()), None)
                print("  a player special:", json.dumps(s0)[:700] if s0 else None)
                if s0:
                    print("  its markets:", json.dumps(by_m.get(s0.get("id")))[:500])
            games: dict = {}
            unmatched_stats = set()
            for m in specials:
                parsed = parse_special(m, sport)
                if not parsed:
                    sp = m.get("special") or {}
                    if "player" in str(sp.get("category", "")).lower():
                        d = DESC.match(str(sp.get("description") or ""))
                        if d:
                            unmatched_stats.add(d.group(2))
                    continue
                player, stat, sides, parent_id = parsed
                game = games.setdefault(parent_id, {"parent": m.get("parent"), "rows": [], "need": []})
                rows = [r for x in by_m.get(m.get("id"), []) for r in props_of(x, sides, player, stat)]
                if rows:
                    game["rows"] += rows
                else:
                    game["need"].append((m.get("id"), sides, player, stat))
            if probe and unmatched_stats:
                print("  stats not mapped:", sorted(unmatched_stats))
            for gid, g in games.items():
                home, away, ko = _game(g["parent"]) or (None, None, None)
                if ko and not now - 3 * 3600 < ko < now + WINDOW_HOURS * 3600:
                    continue
                # Prices missing from the league call: one related-markets call per game, capped.
                if g["need"] and related < MAX_RELATED:
                    rel = PP.get(f"/matchups/{gid}/markets/related/straight", st)
                    related += 1
                    by_rel: dict = {}
                    for x in rel if isinstance(rel, list) else []:
                        by_rel.setdefault(x.get("matchupId"), []).append(x)
                    for mid, sides, player, stat in g["need"]:
                        g["rows"] += [r for x in by_rel.get(mid, []) for r in props_of(x, sides, player, stat)]
                    if probe:
                        print(f"  related call for {home} v {away}: {len(rel) if isinstance(rel, list) else rel}")
                if not g["rows"]:
                    continue
                fid = None
                if home and away and ko:
                    try:
                        fid = bet365_prices.match_fixture(f"{home} v {away}", ko, events)
                    except Exception:  # noqa: BLE001
                        fid = None
                held[str(gid)] = {"name": f"{home} v {away}", "home": home, "away": away, "kickoff": ko,
                                  "sport": sport, "fid": fid, "fetchedAt": time.time(), "props": g["rows"]}
                got += 1
    except PP.Capped as e:
        print(f"  pinnacle props: stopped early ({e})")
    except PP.Transient as e:
        _lock(st, str(e), PP.TRANSIENT_HOURS)
    except PP.Refused as e:
        _lock(st, str(e), PP.LOCKOUT_HOURS)
    _save(st)
    out["updated"] = time.time()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    n = sum(len(e["props"]) for e in held.values())
    print(f"  pinnacle props: {got} game(s) priced, {n} prop prices held, "
          f"{st.get('count', {}).get(PP.today(), 0)}/{MAX_PER_DAY} requests today")
    return 0


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st))


def _lock(st: dict, why: str, hours: float) -> None:
    st["lockedUntil"] = time.time() + hours * 3600
    st["lockedWhy"] = why
    print(f"  pinnacle props: refused ({why}); locked out for {hours:g}h")


# ------------------------------------------------------------ lookup for pplog

_IDX: dict = {}


def _norm(s: str) -> str:
    import pplog
    return pplog._norm(s)


def index() -> dict:
    """(sport, normalised player, stat) -> [(kickoff, fid, rows at each line)], cached on the file's mtime."""
    try:
        mt = OUT.stat().st_mtime
    except OSError:
        return {}
    if _IDX.get("mt") == mt:
        return _IDX["idx"]
    idx: dict = {}
    try:
        data = json.loads(OUT.read_text())
    except (OSError, ValueError):
        data = {}
    for gid, e in (data.get("events") or {}).items():
        for r in e.get("props") or []:
            k = (e.get("sport"), _norm(r["player"]), r["stat"])
            idx.setdefault(k, []).append((e.get("kickoff") or 0, e.get("fid"), r))
    _IDX.update(mt=mt, idx=idx)
    return idx


def sharp_for(sport: str, player: str, stat: str, line: float, over: bool, kickoff: float, fid=None):
    """Pinnacle's margin-free chance for this exact side, or its nearest line.

    {"p", "price", "line", "same"}: same is True when Pinnacle's line equals
    Paddy's; otherwise line is Pinnacle's nearest line (kept so the gap can be
    modelled later, not used by the rule)."""
    rows = index().get((sport, _norm(player), stat)) or []
    rows = [(ko, f, r) for ko, f, r in rows
            if (fid is not None and f is not None and str(f) == str(fid)) or abs((ko or 0) - kickoff) < 4 * 3600]
    if not rows:
        return None
    side = [r for _, _, r in rows if r["over"] == bool(over)]
    if not side:
        return None
    best = min(side, key=lambda r: abs(r["line"] - line))
    return {"p": best["p"], "price": best["price"], "line": best["line"], "same": abs(best["line"] - line) < 1e-9}


def status() -> None:
    st = _load()
    try:
        held = json.loads(OUT.read_text()).get("events", {})
    except (OSError, ValueError):
        held = {}
    for gid, e in sorted(held.items(), key=lambda kv: kv[1].get("kickoff") or 0):
        print(f"  {e['name']:<44} {time.strftime('%a %H:%M', time.localtime(e.get('kickoff') or 0))}  "
              f"{len(e['props'])} prices  fid={e.get('fid')}")
    print(f"  requests today: {st.get('count', {}).get(PP.today(), 0)}/{MAX_PER_DAY}",
          f"locked: {st.get('lockedWhy')}" if st.get("lockedUntil", 0) > time.time() else "")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--probe", action="store_true")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.status:
        status()
        return 0
    PP.HDR = PP.headers()
    return run(probe=a.probe)


if __name__ == "__main__":
    sys.exit(main())
