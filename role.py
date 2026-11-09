#!/usr/bin/env python3
"""Where a footballer plays today, and his record when he plays there (8 Nov 2026).

SofaScore lists a line-up as the goalkeeper, then each line of the formation
from the back, each line right to left. Checked on the cached line-ups before
relying on it: Trippier (right-back) is slot 2 in all 37 of his back-four
starts, Van Dijk (left centre-back) slot 4 in his, Saka slot 9 in a 4-3-3 and
slot 8 in a 4-2-3-1, Martinelli slot 11 and 10, Haaland the last slot. So the
formation plus the order gives a role, and a role change is visible before
kick-off.

Why it matters: Mukiele, 8 Nov, Sunderland v Chelsea. A 7/10 shot record built
at right-back, and the confirmed XI had him at right centre-back (4-2-3-1,
slot 3). A record from one role is not evidence for another.

    python role.py 16363920            # roles in one cached line-up
    python role.py --player "Nordi Mukiele"   # his starts by role

Roles: GK, CB, FB, WB, DM, CM, AM, W, ST. Families (what counts as the same
job for a record): GK, CB, FB (full-back or wing-back), CM (holding or
central), AM (attacking or wide), ST.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

CACHE = Path(__file__).parent / "cache"

FAMILY = {"GK": "GK", "CB": "CB", "FB": "FB", "WB": "FB", "DM": "CM", "CM": "CM",
          "AM": "AM", "W": "AM", "ST": "ST"}
NAME = {"GK": "goalkeeper", "CB": "centre-back", "FB": "full-back", "WB": "wing-back",
        "DM": "holding midfield", "CM": "central midfield", "AM": "attacking midfield",
        "W": "wide", "ST": "striker"}
FAMILY_NAME = {"GK": "in goal", "CB": "centre-back", "FB": "full-back or wing-back",
               "CM": "central midfield", "AM": "attacking midfield or wide", "ST": "up front"}
MIN_ROLE_GAMES = 5      # fewer starts in today's role than this: no role record to judge on
USUAL_OF = 10           # his usual role is the commonest over this many recent starts

_memo: dict = {}


def _role(li: int, nl: int, j: int, s: int, back: int) -> str:
    """Role for position j (0 = right) of a line of size s, line li of nl."""
    outer = s > 1 and j in (0, s - 1)
    if li == 0:                                     # the back line
        if s >= 5:
            return "WB" if outer else "CB"
        if s == 4:
            return "FB" if outer else "CB"
        return "CB"
    if li == nl - 1:                                # the front line
        return "W" if s >= 3 and outer else "ST"
    if li == 1:                                     # first line in front of the defence
        if back <= 3 and s >= 4:
            return "WB" if outer else "CM"
        if s >= 4:
            return "W" if outer else "CM"
        if s == 3:
            return "CM"
        return "DM" if nl >= 4 or s == 1 else "CM"
    if s >= 4:                                      # a later midfield line
        return "W" if outer else "CM"
    if s == 3:
        return "W" if outer else "AM"
    return "AM"


def roles(formation: str, starters: list[dict]) -> dict[int, str]:
    """player id -> role for one side's starters, in SofaScore's order. Empty
    when the formation and the eleven do not add up (it never guesses)."""
    sizes = [int(x) for x in (formation or "").split("-") if x.isdigit()]
    gk = [p for p in starters if (p.get("position") or (p.get("player") or {}).get("position")) == "G"]
    outf = [p for p in starters if p not in gk]
    if not sizes or sum(sizes) != len(outf) or len(gk) > 1:
        return {}
    out = {p["player"]["id"]: "GK" for p in gk if (p.get("player") or {}).get("id")}
    k = 0
    for li, s in enumerate(sizes):
        for j in range(s):
            pid = (outf[k].get("player") or {}).get("id")
            if pid:
                out[pid] = _role(li, len(sizes), j, s, sizes[0])
            k += 1
    return out


def lineup(event_id) -> dict | None:
    if event_id in _memo:
        return _memo[event_id]
    try:
        d = json.loads((CACHE / f"event_{event_id}_lineups.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    _memo[event_id] = d
    return d


def match_roles(event_id) -> dict[int, str]:
    """Every starter's role in one cached line-up, both sides."""
    key = ("roles", event_id)
    if key in _memo:
        return _memo[key]
    d = lineup(event_id) or {}
    out = {}
    for side in ("home", "away"):
        b = d.get(side) or {}
        out.update(roles(b.get("formation"), [p for p in b.get("players") or [] if not p.get("substitute")]))
    _memo[key] = out
    return out


def today(event_id, player_id) -> tuple[str | None, bool]:
    """(role, confirmed) in an upcoming match's cached line-up, confirmed XI
    or predicted; (None, False) when he is not in it or it does not add up."""
    d = lineup(event_id) or {}
    return match_roles(event_id).get(player_id), bool(d.get("confirmed"))


def _apps(rows: list[dict], stat: str, zero_fill=frozenset(), min_minutes: float = 0) -> list[dict]:
    """model.appearances, keeping the match id (same gate, same zero fill)."""
    gated = any((g.get("minutes") or 0) > 0 for g in rows)
    out = []
    for g in rows:
        if gated and (g.get("minutes") or 0) < min_minutes:
            continue
        if not gated and not (g.get("stats") or {}):
            continue
        v = (g.get("stats") or {}).get(stat)
        if v is None and stat in zero_fill:
            v = 0
        if v is None:
            continue
        out.append({"value": v, "match": g.get("match_id"), "started": g.get("started", True)})
    return out


def usual(rows: list[dict], player_id) -> str | None:
    """His commonest role family over his last USUAL_OF starts with a known role."""
    fams = []
    for g in reversed(rows):
        if g.get("started") is False or not g.get("match_id"):
            continue
        r = match_roles(g["match_id"]).get(player_id)
        if r:
            fams.append(FAMILY[r])
            if len(fams) >= USUAL_OF:
                break
    if not fams:
        return None
    c = collections.Counter(fams)
    best = max(c.values())
    for f in fams:                       # ties go to the most recent
        if c[f] == best:
            return f


def line_role(event_id, rows: list[dict], stat: str, line: float, over: bool = True,
              zero_fill=frozenset(), min_minutes: float = 0) -> dict | None:
    """Today's role against his usual one, and his record on this line in
    starts at today's role family (last ten of them). None when today's role
    is unknown (no line-up, or he is not in it)."""
    pid = next((g.get("player_id") for g in rows if g.get("player_id")), None)
    if pid is None:
        return None
    role, confirmed = today(event_id, pid)
    if not role:
        return None
    fam = FAMILY[role]
    us = usual(rows, pid)
    hit = (lambda v: v > line) if over else (lambda v: v <= line)
    at = [a for a in _apps(rows, stat, zero_fill, min_minutes)
          if a["match"] and match_roles(a["match"]).get(pid) and FAMILY[match_roles(a["match"])[pid]] == fam]
    at = at[-10:]
    return {"role": role, "family": fam, "usual": us, "change": bool(us and us != fam),
            "k": sum(1 for a in at if hit(a["value"])), "n": len(at), "xi": "confirmed" if confirmed else "predicted"}


def badge_text(rl: dict, stat_label: str = "") -> str:
    """'Centre-back today, usually full-back or wing-back: 7/12 there'."""
    if not rl or not rl.get("change"):
        return ""
    s = f"{NAME[rl['role']].capitalize()} today, usually {FAMILY_NAME.get(rl['usual'], rl['usual'])}"
    if rl.get("n"):
        s += f": {rl['k']}/{rl['n']}{' ' + stat_label if stat_label else ''} there"
    else:
        s += ": no record there"
    return s


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--player"] and len(argv) > 1:
        name, c = argv[1], collections.Counter()
        for f in CACHE.glob("event_*_lineups.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            for side in ("home", "away"):
                b = d.get(side) or {}
                st = [p for p in b.get("players") or [] if not p.get("substitute")]
                r = roles(b.get("formation"), st)
                for p in st:
                    if (p.get("player") or {}).get("name") == name and p["player"]["id"] in r:
                        c[(b.get("formation"), r[p["player"]["id"]])] += 1
        for (form, r), n in c.most_common():
            print(f"  {n:3d}  {r:2s}  {form}")
        return
    for eid in argv:
        d = lineup(int(eid)) or {}
        for side in ("home", "away"):
            b = d.get(side) or {}
            st = [p for p in b.get("players") or [] if not p.get("substitute")]
            r = roles(b.get("formation"), st)
            print(f"{side} {b.get('formation')}: " + ", ".join(
                f"{p['player']['name']} {r.get(p['player']['id'], '?')}" for p in st))


if __name__ == "__main__":
    main()
