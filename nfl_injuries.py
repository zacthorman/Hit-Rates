#!/usr/bin/env python3
"""NFL injuries and quarterback changes, attached to each NFL fixture.

    python nfl_injuries.py            # refresh reports/nfl.html in place, print QB changes
    python nfl_injuries.py --dry-run  # print only

Why this exists: a receiver's record was built catching passes from whoever
has been starting at quarterback. If that man is out, the record describes a
different offence, and a line priced off it is priced on the wrong thing.
SofaScore only says who is active about 90 minutes before kick-off, which is
too late to be useful most of the week, so three sources are combined:

  1. ESPN's public injury report (Out, Doubtful, IR, Questionable), fetched
     at build time and cached for three hours.
  2. The confirmed inactives, once SofaScore has them.
  3. nfl_starters.json, a manual override for when you know before either:
         {"Kansas City Chiefs": "Gardner Minshew"}
     Delete the line once it no longer applies.

attach(entry) writes entry["injuries"] and entry["qbChange"]. The report
reads both (Defences tab), and weekend.py uses them to keep injured players,
and receivers whose quarterback has changed, out of the picks of the week.
Never fatal: any failure leaves the entry as it was.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
import pagedata

ROOT = Path(__file__).parent
CACHE = ROOT / "cache" / "espn_nfl_injuries.json"
OVERRIDES = ROOT / "nfl_starters.json"
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
MAX_AGE = 3 * 3600

OUT = re.compile(r"^(out|doubtful|injured reserve|ir\b|suspen|pup|physically unable|"
                 r"non-football|reserve)", re.I)
KEEP = re.compile(r"^(out|doubtful|questionable|injured reserve|ir\b|suspen|pup|"
                  r"physically unable|non-football|reserve)", re.I)

# A replacement with no record is assumed to manage this share of the
# starter's output. Backups who have started are shrunk towards it by three
# phantom games, so one good afternoon does not make a man a franchise QB.
BACKUP_LEVEL = 0.8
PHANTOM = 3
MIN_ATTEMPTS = 10


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return " ".join(n.split())


def fetch(max_age: float = MAX_AGE) -> dict:
    """{team display name: [[player, position, status], ...]}, cached."""
    data = None
    if CACHE.exists() and time.time() - CACHE.stat().st_mtime < max_age:
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            data = None
    if data is None:
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 hit-rates"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(json.dumps(data), encoding="utf-8")
        except Exception as exc:
            print(f"  ESPN injuries not fetched ({type(exc).__name__}), using cache if any")
            try:
                data = json.loads(CACHE.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return parse(data)


def parse(data: dict) -> dict:
    out: dict[str, list] = {}
    for team in data.get("injuries") or []:
        name = team.get("displayName") or (team.get("team") or {}).get("displayName")
        rows = []
        for inj in team.get("injuries") or []:
            ath = inj.get("athlete") or {}
            if not name:
                name = (ath.get("team") or {}).get("displayName")
            status = inj.get("status")
            if isinstance(status, dict):
                status = status.get("name") or status.get("type")
            if not status or not KEEP.match(str(status)):
                continue
            pos = (ath.get("position") or {}).get("abbreviation") or ""
            rows.append([ath.get("displayName") or "", pos, str(status)])
        if name:
            out.setdefault(name, []).extend(rows)
    return out


def overrides() -> dict:
    try:
        return json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _starts(records: list) -> list[dict]:
    """One row per game: the quarterback who threw the most, with his line."""
    games: dict = {}
    for r in records or []:
        if r.get("position") != "QB" or r.get("former_club"):
            continue
        s = r.get("stats") or {}
        att = s.get("Passing attempts") or 0
        if att < MIN_ATTEMPTS:
            continue
        g = games.get(r["match_id"])
        if g is None or att > g["att"]:
            games[r["match_id"]] = {"date": r.get("date") or "", "name": r["player"], "att": att,
                                    "yds": s.get("Passing yards") or 0,
                                    "cmp": s.get("Passing completions") or 0}
    return sorted(games.values(), key=lambda g: g["date"])


def qb_change(entry: dict, t: int, injured: list, override: str | None) -> dict | None:
    """Who will start, and how far his passing is from what the receivers' records saw.

    Receivers' records are their last ten games, which may already mix
    quarterbacks (an injury last season, a backup for two weeks). So the
    question is not "is the usual starter out" but "is the man starting this
    week the one who threw most of those ten games". If he threw seven or
    more, nothing changes. Otherwise receivers are rescaled by his passing
    per start against the team's average over those same ten games.
    """
    records = (entry.get("players") or [[], []])[t] or []
    starts = _starts(records)
    if not starts:
        return None
    last10 = starts[-10:]
    counts = Counter(g["name"] for g in last10)

    side = "home" if t == 0 else "away"
    out_status = {_norm(p[0]): p[2] for p in injured if OUT.match(p[2] or "")}
    confirmed = ((entry.get("lineups") or {}).get("confirmed") or {}).get(side) or {}
    roster = {_norm(p["name"]) for p in confirmed.get("xi") or []} | {_norm(n) for n in confirmed.get("bench") or []}
    missing = {_norm(m[0]) for m in confirmed.get("missing") or []}

    def unavailable(name: str) -> str | None:
        k = _norm(name)
        if k in missing or (roster and k not in roster):
            return "inactive"
        if k in out_status:
            return f"listed {out_status[k]}"
        return None

    if override:
        current, source = override, "manual override (nfl_starters.json)"
    else:
        # Latest starter first: whoever started last week starts this week
        # unless he is hurt. Then the rest by how recently they started.
        order = [g["name"] for g in reversed(starts)]
        order += [n for n, _ in Counter(r["player"] for r in records if r.get("position") == "QB").most_common()]
        current = next((n for n in dict.fromkeys(order) if not unavailable(n)), None)
        source = "confirmed inactives" if roster else "ESPN injury report"

    share = sum(1 for g in last10 if current and _norm(g["name"]) == _norm(current)) / len(last10)
    if share >= 0.7:
        return None

    others = Counter({n: c for n, c in counts.items() if not current or _norm(n) != _norm(current)})
    regular = others.most_common(1)[0][0] if others else last10[-1]["name"]
    yds0 = sum(g["yds"] for g in last10) / len(last10)
    cmp0 = sum(g["cmp"] for g in last10) / len(last10)
    mine = [g for g in starts if current and _norm(g["name"]) == _norm(current) and g["att"] >= 15]
    n = len(mine)
    yds1 = (sum(g["yds"] for g in mine) + PHANTOM * BACKUP_LEVEL * yds0) / (n + PHANTOM)
    cmp1 = (sum(g["cmp"] for g in mine) + PHANTOM * BACKUP_LEVEL * cmp0) / (n + PHANTOM)
    clamp = lambda x: round(min(1.2, max(0.55, x)), 3)
    status = unavailable(regular)
    yf = clamp(yds1 / yds0) if yds0 else 1
    rf = clamp(cmp1 / cmp0) if cmp0 else 1
    # Nobody hurt and nothing overridden: the latest starter is a guess at
    # who starts, so only act on it when the passing gap is worth acting on.
    if not status and not override and abs(yf - 1) < 0.1 and abs(rf - 1) < 0.1:
        return None
    reason = (status or "not starting") + f", threw {counts[regular]} of the last {len(last10)}"
    return {"from": regular, "to": current, "toStarts": n, "reason": reason, "source": source,
            "share": round(share, 2),
            "yds": yf, "rec": rf}


def attach(entry: dict, report: dict | None = None) -> bool:
    """Add injuries and qbChange to one NFL fixture entry. Returns True on change."""
    if (entry.get("fixture") or {}).get("sport") != "american-football":
        return False
    try:
        report = fetch() if report is None else report
        over = overrides()
        before = json.dumps([entry.get("injuries"), entry.get("qbChange")], sort_keys=True)
        inj, qb = {}, {}
        for t, team in enumerate(entry.get("teams") or []):
            side = "home" if t == 0 else "away"
            # Only players who appear in this report: the rest is noise.
            known = {_norm(r["player"]) for r in (entry.get("players") or [[], []])[t] or []}
            rows = [p for p in report.get(team["name"], []) if _norm(p[0]) in known]
            inj[side] = rows
            change = qb_change(entry, t, rows, over.get(team["name"]))
            if change:
                qb[side] = change
        if report:
            inj["fetched"] = datetime.now().strftime("%a %d %b %H:%M")
        entry["injuries"] = inj
        if qb:
            entry["qbChange"] = qb
        else:
            entry.pop("qbChange", None)
        after = json.dumps([entry.get("injuries"), entry.get("qbChange")], sort_keys=True)
        return before != after
    except Exception as exc:
        print(f"  injuries skipped for {entry.get('fixture', {}).get('home')} ({type(exc).__name__}: {exc})")
        return False


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    path = ROOT / "reports" / "nfl.html"
    text = path.read_text(encoding="utf-8")
    payload = json.loads(pagedata.search(text).group(1))
    report = fetch(max_age=0 if not args.dry_run else MAX_AGE)
    for entry in payload["fixtures"]:
        attach(entry, report)
        for side, q in (entry.get("qbChange") or {}).items():
            team = entry["fixture"][side]
            print(f"  {team}: {q['from']} {q['reason']} -> {q['to'] or 'backup, no record'} "
                  f"(yards x{q['yds']:.2f}, receptions x{q['rec']:.2f}, {q['source']})")
    if not args.dry_run:
        import report as rep
        rep.write_report(payload, path)
        print(f"Updated {path.name}. Now: ./publish.sh")


if __name__ == "__main__":
    main()
