#!/usr/bin/env python3
"""The Paddy Power record for TEAM lines: corners, cards, fouls, shots on target.

    python teamlog.py snapshot   # log every team line on upcoming games (publish.sh)
    python teamlog.py settle     # results for anything finished (publish.sh)
    python teamlog.py report     # how the team lines have done so far

The player record (pplog.py) has been settling Paddy Power's player lines since
October; the team lines the Value tab added on 20 Oct 2026 had no record at
all, and on 21 Oct they were 26 of the 30 "takes" on the European pages. The
page then called none of them a take. This builds the evidence to decide
whether it should: every line, the price first and last seen, and what our
number was at the time (the expectation and how it was made, so any spread
or calibration can be tried on it later), then the result.

Since teamline_backtest.py (TEAM-LINES.md), a team line can be a take only in
a market that passed it, priced by the team model. So each line also carries
the team model's chance and expected count, its market, and at each price
seen the verdict teamlines.verdict() gives that chance (the page's rule: in a
passed market it is the page's own verdict; in a failed one the page still
prices from the record, and neither is ever a take). `report` splits the
settled lines by market and verdict: the takes in a passed market are the
ones the backtest has to be right about.

Written to pplog/team-YYYY-MM.jsonl, beside the player log. Football only (the
NBA and NFL team totals are points, which Betfair prices sharper). Reads the
cache and the reports only; settling makes one statistics request per
finished game, the same request besttrack.py makes.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "pplog"
PP = ROOT / "reports" / "paddypower.json"
MARKETS = ROOT / "reports" / "markets.json"
TEAM_ODDS_POWER = {"Corner kicks": 0.7, "Total shots": 0.7, "Shots on target": 0.8}  # mirrors report.py


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if c.isascii() and (c.isalpha() or c == " ")).lower().split())


def _files() -> list[Path]:
    return sorted(DIR.glob("team-*.jsonl"))


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _key(r: dict) -> str:
    return f"{r['event_id']}|{r['scope']}|{r['stat']}|{r['line']}|{int(r['over'])}"


# ------------------------------------------------------------------ our number

def _order(pp_home: str, teams: list[dict]) -> list[int]:
    """Paddy Power's home side against the report's teams, by name (ppTeamOrder)."""
    stop = {"the", "club", "real", "sporting", "city", "united"}
    words = lambda s: {w for w in _norm(s).split() if len(w) >= 3 and w not in stop}
    a, b = words(teams[0]["name"]), words(teams[1]["name"])
    h = words(pp_home)
    return [1, 0] if len(h & b) > len(h & a) else [0, 1]


def _lambdas(match: dict) -> tuple[float, float] | None:
    """Each side's expected goals from Betfair's home/draw/away (goalLambdas)."""
    try:
        ph, pd_, pa = match["home"]["p"], match["draw"]["p"], match["away"]["p"]
    except (KeyError, TypeError):
        return None
    pois = lambda l: [math.exp(-l) * l ** k / math.factorial(k) for k in range(11)]
    best, err = None, math.inf
    lh = 0.15
    while lh <= 4.5:
        h = pois(lh)
        la = 0.15
        while la <= 4.5:
            a = pois(la)
            H = sum(h[i] * a[j] for i in range(11) for j in range(11) if i > j)
            Dr = sum(h[i] * a[i] for i in range(11))
            A = 1 - H - Dr
            e = (H - ph) ** 2 + (Dr - pd_) ** 2 + (A - pa) ** 2
            if e < err:
                err, best = e, (lh, la)
            la += 0.1
        lh += 0.1
    return best


def _expected(entry: dict, stat: str, t: int, lam) -> tuple[float, str, list] | None:
    """(expectation, basis, last-10 values) for one side, as teamExpected() makes it."""
    recs = (entry.get("records") or [[], []])[t][-10:]
    vals = [((r.get("stats") or {}).get("ALL") or {}).get(stat) for r in recs]
    vals = [v for v in vals if v is not None]
    proj = (((entry.get("projection") or {}).get("ALL") or {}).get(stat) or [None, None])
    if proj[t] is not None and proj[t] > 0:
        return float(proj[t]), "projection", vals
    if len(vals) < 3:
        return None
    mean = sum(vals) / len(vals)
    power = TEAM_ODDS_POWER.get(stat)
    if (entry.get("fixture") or {}).get("crossLeague") and power and lam:
        goals = [((r.get("stats") or {}).get("ALL") or {}).get("Goals") for r in (entry.get("records") or [[], []])[t]]
        goals = [g for g in goals if g is not None]
        g = sum(goals) / len(goals) if goals else 0
        if len(goals) >= 5 and g > 0.2:
            adj = min(2.5, max(0.2, (lam[t] / g) ** power))
            return mean * adj, "odds", vals
    return mean, "record", vals


# ------------------------------------------------------------------ snapshot

def _models(entry: dict) -> dict:
    """teamlines.side_models(), or {} when the team model cannot be read."""
    try:
        import teamlines
        return teamlines.side_models(entry)
    except Exception as exc:
        print(f"team log: team model skipped ({type(exc).__name__}: {exc})")
        return {}


def _verdict(row: dict, price: float):
    import teamlines
    return teamlines.verdict(row["tl_market"], row.get("model_p"), price) if row.get("model_p") else None


def snapshot(args=None) -> int:
    import playerlines
    import teamlines
    try:
        pp = json.loads(PP.read_text())
        mk = json.loads(MARKETS.read_text()).get("events") or {}
    except (OSError, ValueError):
        print("team log: no Paddy Power prices held")
        return 0
    now = time.time()
    fixtures = {str(m["id"]): (e, m) for e, m in playerlines.upcoming(48)}
    existing = {}
    for path in _files():
        for r in _read(path):
            existing[_key(r)] = (path, r)
    new_rows, updated = [], set()
    for fid, ev in (pp.get("events") or {}).items():
        if fid not in fixtures or not ev.get("team"):
            continue
        entry, meta = fixtures[fid]
        if meta["kickoff"] <= now or ((entry.get("fixture") or {}).get("sport") or "football") != "football":
            continue
        teams = entry.get("teams") or [{}, {}]
        order = _order(ev.get("ppHome") or "", teams)
        lam = _lambdas((mk.get(fid) or {}).get("match") or {})
        models = _models(entry)
        for l in ev["team"]:
            if l["scope"] == "match":
                a, b = _expected(entry, l["stat"], 0, lam), _expected(entry, l["stat"], 1, lam)
                if not a or not b:
                    continue
                exp, basis = a[0] + b[0], (a[1] if a[1] == b[1] else "mixed")
                vals, side, side_idx = None, "Match", None
                shown = len(a[2]) >= 5 and len(b[2]) >= 5
            else:
                t = order[0 if l["scope"] == "home" else 1]
                x = _expected(entry, l["stat"], t, lam)
                if not x:
                    continue
                exp, basis, vals = x
                side = teams[t].get("name")
                side_idx = t
                shown = len(vals) >= 5     # teamValued() shows no line on fewer
            row = {"event_id": int(fid), "fixture": f"{meta['home']} v {meta['away']}",
                   "competition": meta.get("competition"), "kickoff": meta["kickoff"],
                   "cross_league": bool((entry.get("fixture") or {}).get("crossLeague")),
                   "scope": l["scope"], "team": side, "side": side_idx, "stat": l["stat"], "line": l["line"],
                   "over": l["over"], "market": l.get("market"),
                   "tl_market": teamlines.market_key(l["stat"], l["scope"])}
            mc = teamlines.model_chance(models, l["stat"], l["scope"], side_idx, l["line"], l["over"])
            row.update({"model_p": round(mc[0], 4) if mc and shown else None,
                        "model_mu": round(mc[1], 3) if mc else None})
            snap = {"t": round(now), "price": l["price"], "verdict": _verdict(row, l["price"])}
            key = _key(row)
            if key in existing:
                path, old = existing[key]
                if old.get("result") is None:
                    old["last"] = snap
                    updated.add(path)
                continue
            row.update({"logged_at": round(now), "first": snap, "last": snap,
                        "expected": round(exp, 3), "basis": basis, "recent": vals,
                        "result": None, "value": None})
            existing[key] = (None, row)
            new_rows.append(row)
    for path in updated:
        _write(path, [existing[_key(r)][1] for r in _read(path)])
    if new_rows:
        by = collections.defaultdict(list)
        for r in new_rows:
            by[DIR / time.strftime("team-%Y-%m.jsonl", time.gmtime(r["kickoff"]))].append(r)
        for path, rows in by.items():
            _write(path, (_read(path) if path.exists() else []) + rows)
    print(f"team log: {len(new_rows)} new line(s), {len(updated)} file(s) re-priced")
    return len(new_rows)


# ------------------------------------------------------------------ settle

def settle(args=None) -> int:
    import besttrack
    import hitrates
    import sofascore_api as api
    now = time.time()
    done = 0
    cache = {}
    for path in _files():
        rows = _read(path)
        changed = False
        for r in rows:
            if r["result"] is not None or r["kickoff"] > now - 3 * 3600:
                continue
            eid = r["event_id"]
            if eid not in cache:
                ev = (api.get_json(f"event/{eid}", max_age_hours=1, verbose=False) or {})
                ev = ev.get("event", ev)
                fin = (ev.get("status") or {}).get("type") == "finished"
                stats = hitrates.extract_match_stats(api.event_statistics(eid)) if fin else None
                cache[eid] = (ev, stats)
            ev, stats = cache[eid]
            st = (ev.get("status") or {}).get("type")
            if st in ("canceled", "postponed"):
                r["result"], changed = "void", True
                continue
            if st != "finished" or not stats:
                continue
            home, away = (ev.get("homeTeam") or {}).get("name"), (ev.get("awayTeam") or {}).get("name")
            leg = lambda team: {"team": team, "period": "ALL", "stat": r["stat"]}
            if r["scope"] == "match":
                a, b = besttrack._team_value(leg(home), ev, stats), besttrack._team_value(leg(away), ev, stats)
                v = None if a is None or b is None else a + b
            else:
                # the report's side 0 is SofaScore's home team (reports are built from it)
                v = besttrack._team_value(leg(home if r["side"] == 0 else away), ev, stats)
            if v is None:
                continue
            r["value"] = v
            r["result"] = "win" if (v > r["line"] if r["over"] else v < r["line"]) else "lose"
            done += 1
            changed = True
        if changed:
            _write(path, rows)
    print(f"team log: settled {done} line(s)")
    return done


def summary(rows: list[dict]) -> dict:
    """{(market, verdict): {n, won, said, pl}} over settled lines, at the last price seen.

    The verdict is the page's at that price; lines logged before the team
    model was recorded have none and count as "unpriced"."""
    import teamlines
    by = collections.defaultdict(list)
    for r in rows:
        if r.get("result") not in ("win", "lose"):
            continue
        key = r.get("tl_market") or teamlines.market_key(r["stat"], r["scope"])
        by[(key, (r.get("last") or r["first"]).get("verdict") or "unpriced")].append(r)
    out = {}
    for k, rs in by.items():
        price = lambda r: (r.get("last") or r["first"])["price"]  # noqa: E731
        ps = [r["model_p"] for r in rs if r.get("model_p") is not None]
        out[k] = {"n": len(rs), "won": sum(r["result"] == "win" for r in rs),
                  "said": sum(ps) / len(ps) if ps else None,
                  "pl": sum((price(r) - 1) if r["result"] == "win" else -1 for r in rs)}
    return out


def report(args=None) -> None:
    rows = [r for p in _files() for r in _read(p) if r["result"] in ("win", "lose")]
    if not rows:
        print("team log: nothing settled yet")
        return
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["stat"], r["basis"])].append(r)
    for (stat, basis), rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        won = sum(r["result"] == "win" for r in rs)
        pl = sum((r["first"]["price"] - 1) if r["result"] == "win" else -1 for r in rs)
        print(f"  {stat:16} {basis:10} {len(rs):4} lines, won {won / len(rs):.0%}, "
              f"every line {pl:+.1f}u ({pl / len(rs):+.0%})")
    import teamlines
    print("\n  by market and the page's verdict at the last price (team model's chance where it priced the line):")
    for (key, v), x in sorted(summary(rows).items()):
        said = f", said {x['said']:.0%}" if x["said"] is not None else ""
        passed = " (passed)" if teamlines.market_gate(key) else ""
        print(f"  {teamlines.market_name(key):28}{passed:9} {v:9} {x['n']:4} lines, won {x['won'] / x['n']:.0%}"
              f"{said}, {x['pl']:+.1f}u ({x['pl'] / x['n']:+.0%})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["snapshot", "settle", "report"])
    a = ap.parse_args()
    {"snapshot": snapshot, "settle": settle, "report": report}[a.cmd]()


if __name__ == "__main__":
    main()
