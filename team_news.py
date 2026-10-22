#!/usr/bin/env python3
"""Team news for every sport, attached to each fixture as entry["injuries"].

    python team_news.py            # refresh the reports in place (publish.sh)
    python team_news.py --dry-run  # print who is out, change nothing

The Value tab, the picks of the week and the NBA/NFL model all read one list
per side, [[player, position, status], ...]. Anyone whose status starts Out,
Doubtful, Suspended, Injured Reserve, Inactive or Not in squad is left out of
the value lines, and the model re-scores his team-mates without him (their
usage goes up, as it did in training when a regular sat).

Sources, strongest first:
  1. the confirmed line-up (SofaScore, about an hour before the start):
     anyone with a record who is not in it is Inactive (NBA, NFL) or Not in
     squad (football); a football player named on the bench is Bench, since
     a prop priced on a starter's minutes is the wrong bet for a sub.
  2. ESPN's injury report (NBA and NFL), cached three hours.
  3. SofaScore's missing players, which it lists before any line-up: all
     day before an NBA tip-off, with the predicted XI in football.
NFL quarterback changes stay in nfl_injuries.py, which this calls first.

Refreshing makes one SofaScore request per NBA or NFL game in the next 36
hours (lineups, cached two hours) and at most one ESPN request per sport.
Football uses the line-ups the build and lineups_auto.py already fetched,
so costs nothing. Never fatal: any failure leaves an entry as it was.
"""
from __future__ import annotations

import glob
import json
import re
import time
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
ESPN = {"american-football": ("nfl", "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"),
        "basketball": ("nba", "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries")}
MAX_AGE = 3 * 3600
HORIZON = 36 * 3600
# the page's INJ_OUT and weekend.py's out_re match the same words
OUT = re.compile(r"^(out|doubtful|suspen|injured reserve|ir\b|inactive|not in squad|bench|pup|"
                 r"physically unable|non-football|reserve)", re.I)
SUSPENDED = {3, 11, 12}


def _norm(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z ]", "", n.lower().replace("-", " "))
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return " ".join(n.split())


def espn(sport: str, max_age: float = MAX_AGE) -> dict:
    """{normalised player name: (position, status)} across the league."""
    if sport not in ESPN:
        return {}
    code, url = ESPN[sport]
    path = ROOT / "cache" / f"espn_{code}_injuries.json"
    data = None
    if path.exists() and time.time() - path.stat().st_mtime < max_age:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = None
    if data is None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 hit-rates"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"  team news: ESPN {code} not fetched ({type(exc).__name__}), using cache if any")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
    out = {}
    for team in data.get("injuries") or []:
        for inj in team.get("injuries") or []:
            ath = inj.get("athlete") or {}
            status = inj.get("status")
            if isinstance(status, dict):
                status = status.get("name") or status.get("type")
            if ath.get("displayName") and status:
                out[_norm(ath["displayName"])] = ((ath.get("position") or {}).get("abbreviation") or "", str(status))
    return out


def _sofa_status(m: list, in_xi: bool) -> str:
    reason, kind, desc = (m + [None, None, None])[1:4]
    desc = (desc or "").replace("_", " ").strip()
    if reason in SUSPENDED:
        return "Suspended"
    if reason == 4:
        return "Out (coach's decision)"
    if in_xi:
        return "Questionable (in the predicted XI)"
    if kind == "doubtful":
        # football: a doubtful man SofaScore still has in its predicted XI
        # usually plays, and the model is pricing him
        return f"Questionable, {desc}" if desc else "Questionable"
    return f"Out ({desc})" if desc else "Out"


def attach(entry: dict, reports: dict | None = None) -> bool:
    """Write entry["injuries"]. Returns True when it changed."""
    try:
        sport = (entry.get("fixture") or {}).get("sport") or "football"
        if sport == "darts":
            return False
        before = json.dumps(entry.get("injuries"), sort_keys=True)
        if sport == "american-football":
            import nfl_injuries
            nfl_injuries.attach(entry)          # ESPN rows and any QB change
        league = (reports or {}).get(sport)
        if league is None:
            league = espn(sport)
        store = entry.get("lineups") or {}
        confirmed = store.get("confirmed")
        listing = confirmed or store.get("predicted") or store.get("news") or {}
        old = entry.get("injuries") or {}
        news = {}
        for t in (0, 1):
            side = "home" if t == 0 else "away"
            records = (entry.get("players") or [[], []])[t] or []
            pos_of = {}
            for r in records:
                if r.get("player"):
                    pos_of[r["player"]] = r.get("position") or ""
            known = {_norm(n): n for n in pos_of}
            status: dict[str, str] = {}
            # 3. SofaScore's missing list
            block = listing.get(side) or {}
            xi = {_norm(p.get("name")) for p in block.get("xi") or []}
            for m in block.get("missing") or []:
                k = _norm(m[0])
                if k in known:
                    status[k] = _sofa_status(list(m), k in xi)
            # 2. ESPN (NFL rows already came through nfl_injuries)
            for row in old.get(side) or [] if sport == "american-football" else []:
                if _norm(row[0]) in known:
                    status[_norm(row[0])] = row[2]
            for k in known:
                if k in league:
                    status[k] = league[k][1]
            # 1. the confirmed line-up beats everything
            if confirmed and (confirmed.get(side) or {}).get("xi"):
                c = confirmed[side]
                cxi = {_norm(p.get("name")) for p in c.get("xi") or []}
                bench = {_norm(n) for n in c.get("bench") or []}
                for k in known:
                    if k in cxi:
                        status.pop(k, None)
                    elif k in bench:
                        if sport == "football":
                            status[k] = "Bench (confirmed line-up)"
                        else:
                            status.pop(k, None)     # an NBA bench man plays
                    elif not any(_norm(m[0]) == k for m in c.get("missing") or []):
                        status[k] = "Not in squad" if sport == "football" else "Inactive"
            news[side] = [[known[k], pos_of[known[k]], s] for k, s in sorted(status.items())]
        news["fetched"] = datetime.now().strftime("%a %d %b %H:%M")
        news["source"] = ("confirmed line-up" if confirmed else
                          "ESPN and SofaScore" if sport in ESPN else "SofaScore")
        entry["injuries"] = news
        strip = lambda d: json.dumps({k: v for k, v in (d or {}).items() if k != "fetched"}, sort_keys=True)
        return strip(json.loads(before) if before != "null" else None) != strip(news)
    except Exception as exc:  # noqa: BLE001
        print(f"  team news skipped for {entry.get('fixture', {}).get('home')} ({type(exc).__name__}: {exc})")
        return False


def refresh(dry: bool = False) -> int:
    import lineup_data
    import report as rep
    now = time.time()
    leagues = {s: espn(s) for s in ESPN}
    changed = 0
    online = True
    for f in sorted(glob.glob(str(ROOT / "reports" / "*.html"))):
        path = Path(f)
        if path.name.startswith("pick-") or path.name == "darts.html":
            continue
        text = path.read_text(encoding="utf-8")
        m = re.search(r"const ALL = (\{.*?\});\n", text, re.S)
        if not m:
            continue
        payload = json.loads(m.group(1))
        hit = []
        for entry in payload.get("fixtures", []):
            fx = entry.get("fixture") or {}
            ko = fx.get("kickoff") or 0
            if not (now < ko < now + HORIZON):
                continue
            sport = fx.get("sport") or "football"
            if sport in ESPN and not (entry.get("lineups") or {}).get("confirmed"):
                try:
                    # offline: whatever SofaScore said in the last two days
                    lineup_data.attach(entry, max_age_hours=2 if online else 48)
                except SystemExit:
                    # sofascore_api stops when FlareSolverr is down: carry on
                    # with what is cached, and stop asking this run
                    online = False
                    print("  team news: SofaScore not reachable, using cached line-ups")
            if attach(entry, leagues):
                hit.append(entry)
            if dry:
                for t, side in enumerate(("home", "away")):
                    outs = [f"{p[0]} ({p[2]})" for p in entry["injuries"].get(side) or [] if OUT.match(p[2])]
                    if outs:
                        print(f"  {fx.get(side)}: {', '.join(outs)}")
        if hit and not dry:
            rep.write_report(payload, path)
            changed += len(hit)
            print(f"  team news: {path.name}, {len(hit)} game(s) changed")
    return changed


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    n = refresh(a.dry_run)
    if not a.dry_run:
        print(f"team news: {n} game(s) updated")


if __name__ == "__main__":
    main()
