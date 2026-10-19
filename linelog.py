"""
Log every line the model prices, before kick-off, and settle it afterwards.

    python linelog.py snapshot     # every leg on every fixture in the next 48 hours
    python linelog.py settle       # results for anything finished
    python linelog.py report       # how it all landed

besttrack.py records what the site chose to put forward: the picks and the
top three singles a fixture. That is the right record for "do the picks
work", and the wrong one for "does the model work", because a list of the
best-looking of thousands only ever measures the best-looking. This records
all of them, every leg tonight.py can price plus every playerlines.py
suggestion, so calibration can be checked across the whole range the model
quotes, not just the top of it, and so a new rule can be backtested on lines
that were logged before anyone knew the result.

Rules (same as besttrack):
  * a line is recorded only while its fixture is still before kick-off
  * the first sighting of a line is kept; later publishes do not re-record it
  * a player who did not play voids the line; it is not a loss
  * records are only ever appended and settled, never edited

Storage. One JSON-lines file a month in linelog/, around 2 MB a busy day.
That is too much for the public repo's history, so linelog/ is gitignored
and lives with cache/ on this machine. The summary (report) is small and
is what matters; back the folder up if you want the raw rows to survive.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIR = HERE / "linelog"
WINDOW_HOURS = 48
BANDS = ((0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01))


def _month_file(ts: float) -> Path:
    return DIR / f"{time.strftime('%Y-%m', time.gmtime(ts))}.jsonl"


def _files() -> list[Path]:
    return sorted(DIR.glob("*.jsonl")) if DIR.exists() else []


def _read(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _write(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    tmp.replace(path)


def _key(r: dict) -> str:
    return (f"{r['event_id']}|{r['player'] or r['team']}|{r['stat']}|{r['period']}|"
            f"{r['line']}|{r['over']}")


def _num(x):
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def _row(leg: dict, meta: dict, sport: str, kind: str, now: float) -> dict:
    import weekend
    fx = leg.get("fixture") or meta or {}
    ex = leg.get("exchange") or {}
    try:
        chance = weekend.chance(leg)
    except Exception:
        chance = leg.get("p")
    return {
        "logged_at": int(now), "kind": kind,
        "event_id": fx.get("id"), "fixture": f"{fx.get('home')} v {fx.get('away')}",
        "competition": fx.get("competition"), "kickoff": fx.get("kickoff") or 0,
        "sport": sport, "team": leg.get("team"), "player": leg.get("player"),
        "stat": leg.get("stat"), "period": leg.get("period") or "ALL",
        "line": leg.get("line"), "over": bool(leg.get("over", True)),
        "alt": bool(leg.get("alt")), "threshold": leg.get("threshold"),
        "hits": leg.get("hits"), "total": leg.get("total"),
        "chance": _num(chance), "p_model": _num(leg.get("pModel") or leg.get("p")),
        "p_exchange": _num(leg.get("pExchange")),
        "fair": _num(leg.get("fair")), "need": _num(leg.get("need")),
        "back": _num(ex.get("back")), "exchange_kind": ex.get("kind"),
        "source": leg.get("source"),
        "lineup": leg.get("lineupStatus"),
        "value": None, "result": None,
    }


def snapshot(args=None) -> int:
    import playerlines
    import tonight
    import weekend
    now = time.time()
    DIR.mkdir(exist_ok=True)
    have = set()
    for f in _files()[-2:]:
        have |= {_key(r) for r in _read(f)}
    new = []
    for entry, meta in playerlines.upcoming(WINDOW_HOURS):
        if (meta.get("kickoff") or 0) <= now:
            continue
        sport = weekend.sport_of(entry)
        legs = [(l, "line") for l in tonight.legs_of(entry, meta)]
        legs += [(l, "player line") for l in playerlines.suggest(entry, meta, per_fixture=50)]
        for leg, kind in legs:
            r = _row(leg, meta, sport, kind, now)
            if r["line"] is None or r["event_id"] is None:
                continue
            k = _key(r)
            if k in have:
                continue
            have.add(k)
            new.append(r)
    if new:
        path = _month_file(now)
        with path.open("a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(f"line log: {len(new)} new line(s) recorded")
    return len(new)


def settle(args=None) -> int:
    import besttrack
    import hitrates
    import sofascore_api as api
    now = time.time()
    events: dict = {}
    done = 0
    for path in _files():
        rows = _read(path)
        changed = False
        for r in rows:
            if r["result"] is not None or r["kickoff"] > now - 3 * 3600:
                continue
            eid = r["event_id"]
            if eid not in events:
                ev = api.get_json(f"event/{eid}", max_age_hours=1, verbose=False) or {}
                ev = ev.get("event", ev)
                stats = hitrates.extract_match_stats(api.event_statistics(eid)) \
                    if (ev.get("status") or {}).get("type") == "finished" else None
                events[eid] = (ev, stats)
            ev, stats = events[eid]
            status = (ev.get("status") or {}).get("type")
            if status in ("canceled", "postponed"):
                r["result"] = "void"
                changed = True
                continue
            if status != "finished":
                continue
            v = (besttrack._player_value(r, r["sport"]) if r["player"]
                 else besttrack._team_value(r, ev, stats or {}))
            if v is None:
                continue
            if v == "dnp":
                r["result"] = "void"
            else:
                r["value"] = v
                won = v > r["line"] if r["over"] else v < r["line"]
                r["result"] = "win" if won else "lose"
            done += 1
            changed = True
        if changed:
            _write(path, rows)
    print(f"line log: settled {done} line(s)")
    return done


def summary() -> dict:
    rows = [r for f in _files() for r in _read(f)]
    settled = [r for r in rows if r["result"] in ("win", "lose") and r.get("chance")]

    def table(keyf):
        g = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
        for r in settled:
            k = keyf(r)
            if k is None:
                continue
            won = r["result"] == "win"
            p = min(max(r["chance"], 1e-4), 1 - 1e-4)
            g[k][0] += won
            g[k][1] += 1
            g[k][2] += r["chance"]
            g[k][3] -= math.log(p if won else 1 - p)
        return {k: {"n": v[1], "said": v[2] / v[1], "landed": v[0] / v[1],
                    "log_loss": v[3] / v[1]} for k, v in sorted(g.items(), key=lambda x: str(x[0]))}

    def band(r):
        for lo, hi in BANDS:
            if lo <= r["chance"] < hi:
                return f"{int(lo * 100)}-{min(int(hi * 100), 100)}%"

    priced = [r for r in settled if r.get("back")]
    profit = sum((r["back"] - 1) * 0.95 if r["result"] == "win" else -1 for r in priced
                 if r["chance"] * (r["back"] - 1) * 0.95 - (1 - r["chance"]) > 0)
    nval = sum(1 for r in priced if r["chance"] * (r["back"] - 1) * 0.95 - (1 - r["chance"]) > 0)
    return {
        "logged": len(rows), "settled": len(settled),
        "open": sum(1 for r in rows if r["result"] is None),
        "by_band": table(band),
        "by_kind": table(lambda r: r["kind"]),
        "by_sport": table(lambda r: r["sport"]),
        "by_market": table(lambda r: f"{r['sport']} {'player' if r['player'] else 'team'} {r['stat']}"),
        "value_bets": {"n": nval, "profit": profit},
    }


def report(args=None) -> None:
    s = summary()
    print(f"{s['logged']} lines logged, {s['settled']} settled, {s['open']} open\n")
    for name in ("by_band", "by_kind", "by_sport", "by_market"):
        print(name.replace("_", " "))
        for k, v in s[name].items():
            if v["n"] < 20 and name == "by_market":
                continue
            print(f"   {str(k):48} n={v['n']:<6} said {v['said']:.0%}  landed {v['landed']:.0%}"
                  f"  log loss {v['log_loss']:.3f}")
        print()
    vb = s["value_bets"]
    print(f"value bets at the Betfair back price, after 5% commission: "
          f"{vb['n']} bets, profit {vb['profit']:+.1f}u")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["snapshot", "settle", "report"])
    args = ap.parse_args()
    {"snapshot": snapshot, "settle": settle, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()
