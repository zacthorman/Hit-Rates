"""
Track every best bet, settle it from the box score, and learn from the misses.

    python bettrack.py log --event 16184611 --player "Derrick Henry" \\
        --stat "Rushing yards" --line 60 --price 1.10 --kind ladder --group henry-ladder
    python bettrack.py settle          # after the games, reads results from SofaScore
    python bettrack.py report          # P&L, hit rate, and the calibration table
    python bettrack.py fair 6 10       # what a 6/10 record is really worth, learned

track.py covers team markets. This is its sibling for what the best-bets
advice actually recommends: player props, ladders, multis and bet builders.

The point is the calibration. Every leg stores the hit rate the report was
showing when the pick was made (k of n). Once legs settle, report compares
"the site said 60%" with "it happened 40% of the time", fits how hard a raw
record should be pulled towards a coin flip, and writes that to
calibration.json and LESSONS.md. Future picks price off the learned number,
not the raw one. Until there are ~30 settled legs the fit is labelled as
provisional and the default (two phantom hits and two phantom misses) is used.

Rules, same spirit as track.py:
  * a leg logged after kick-off is refused unless --backfill, and backfilled
    legs are marked and left out of the P&L record (they still teach the
    calibration, because the rate was taken from a pre-match report)
  * settlement reads the result, so a loser cannot be dropped
  * a player who did not play voids the leg, it does not count as a loss
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import hitrates
import markets
import sofascore_api as api

HERE = Path(__file__).parent
BETS = HERE / "bets.json"
CALIB = HERE / "calibration.json"
LESSONS = HERE / "LESSONS.md"
REPORTS = HERE / "reports"
DEFAULT_PRIOR = 2.0          # phantom hits AND misses added to every record
MIN_FIT_LEGS = 30


def now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def load() -> list[dict]:
    return json.loads(BETS.read_text()) if BETS.exists() else []


def save(bets: list[dict]) -> None:
    BETS.write_text(json.dumps(bets, indent=2))


def prior() -> float:
    if CALIB.exists():
        try:
            return float(json.loads(CALIB.read_text()).get("prior", DEFAULT_PRIOR))
        except Exception:
            pass
    return DEFAULT_PRIOR


def adjusted(k: int, n: int, a: float | None = None) -> float:
    a = prior() if a is None else a
    return (k + a) / (n + 2 * a)


# ------------------------------------------------------------ report lookup

def _report_fixture(event_id: int):
    """The fixture entry for an event from any built report, newest first."""
    for path in sorted(REPORTS.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name.startswith("pick-"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if str(event_id) not in text:
            continue
        m = re.search(r"const ALL = (\{.*?\});\n", text, re.S)
        if not m:
            continue
        for f in json.loads(m.group(1)).get("fixtures", []):
            if f.get("fixture", {}).get("id") == event_id:
                return f, path.name
    return None, None


def model_record(fx: dict, player: str, stat: str, line: float, games: int = 10):
    """k of n from the report the pick was taken from: player's last `games`."""
    for ti, recs in enumerate(fx.get("players") or []):
        rows = sorted((r for r in recs if r.get("player") == player
                       and not r.get("former_club")), key=lambda r: r["date"])
        if rows:
            vals = [r["stats"][stat] for r in rows if stat in r.get("stats", {})][-games:]
            return (sum(v >= line for v in vals), len(vals),
                    rows[-1].get("player_id"), fx["teams"][ti]["name"])
    return None


# ------------------------------------------------------------------- log

def log(args) -> None:
    fx, source = _report_fixture(args.event)
    if not fx:
        raise SystemExit(f"Event {args.event} is not in any built report. Build it first.")
    F = fx["fixture"]
    kickoff = F.get("kickoff") or 0
    late = kickoff and kickoff <= now()
    if late and not args.backfill:
        raise SystemExit("That match has already kicked off. Use --backfill to record it "
                         "for calibration only (it stays out of the P&L record).")
    rec = model_record(fx, args.player, args.stat, args.line)
    if not rec:
        raise SystemExit(f"No '{args.player}' in {F['home']} v {F['away']}.")
    k, n, pid, team = rec
    leg = {
        "event_id": args.event, "fixture": f"{F['home']} v {F['away']}",
        "kickoff": kickoff, "player": args.player, "player_id": pid, "team": team,
        "stat": args.stat, "line": args.line, "model_k": k, "model_n": n,
        "model_p": round(adjusted(k, n), 3), "source": source,
        "value": None, "result": None,
    }
    bets = load()
    group = args.group or f"{args.player}-{args.stat}-{args.line}"
    bet = next((b for b in bets if b["group"] == group and b["result"] is None), None)
    if bet is None:
        bet = {"group": group, "kind": args.kind, "logged_at":
               datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
               "price": args.price, "stake": args.stake, "backfilled": bool(late),
               "placed": not args.suggested, "legs": [], "result": None, "profit": None,
               "note": args.note or ""}
        bets.append(bet)
    elif args.price:
        bet["price"] = args.price
    bet["legs"].append(leg)
    save(bets)
    tag = " (backfilled)" if late else ""
    print(f"  logged{tag}: [{bet['kind']}:{group}] {args.player} {args.stat} {args.line:g}+ "
          f"- report said {k}/{n}, treated as {leg['model_p']:.0%}")


# ---------------------------------------------------------------- settle

def _lineup_values(event_id: int, player_id: int, sport: str):
    data = api.get_json(f"event/{event_id}/lineups", max_age_hours=1, verbose=False) or {}
    fill = markets.ZERO_FILL_BY_SPORT.get(sport, hitrates.PLAYER_ZERO_FILL)
    if fill is None:
        fill = hitrates.PLAYER_ZERO_FILL
    for side in ("home", "away"):
        for p in (data.get(side) or {}).get("players", []) or []:
            if (p.get("player") or {}).get("id") == player_id:
                return hitrates._player_stat_values(p.get("statistics") or {}, zero_fill=fill)
    return None


def settle(args) -> None:
    bets = load()
    changed = 0
    for bet in bets:
        if bet["result"] is not None:
            continue
        for leg in bet["legs"]:
            if leg["result"] is not None or (leg["kickoff"] and leg["kickoff"] > now()):
                continue
            ev = api.get_json(f"event/{leg['event_id']}", max_age_hours=1, verbose=False) or {}
            ev = ev.get("event", ev)
            if (ev.get("status") or {}).get("type") != "finished":
                continue
            sport = (((ev.get("tournament") or {}).get("category") or {})
                     .get("sport") or {}).get("slug") or "football"
            vals = _lineup_values(leg["event_id"], leg["player_id"], sport)
            if not vals:
                leg["result"] = "void"
            else:
                v = vals.get(leg["stat"], 0.0)
                leg["value"] = v
                leg["result"] = "win" if v >= leg["line"] else "lose"
            changed += 1
            print(f"  {leg['player']} {leg['stat']} {leg['line']:g}+: "
                  f"{leg['value']} -> {leg['result']}  (report had {leg['model_k']}/{leg['model_n']})")
        live = [l for l in bet["legs"] if l["result"] != "void"]
        if all(l["result"] is not None for l in bet["legs"]):
            if not live:
                bet["result"] = "void"
            elif all(l["result"] == "win" for l in live):
                bet["result"] = "win"
            else:
                bet["result"] = "lose"
            if bet.get("price") and bet["result"] != "void":
                bet["profit"] = round(bet["stake"] * (bet["price"] - 1)
                                      if bet["result"] == "win" else -bet["stake"], 2)
    save(bets)
    print(f"\nSettled {changed} leg(s). "
          f"{sum(1 for b in bets if b['result'] is None)} bet(s) still open.")
    fit_and_write()


# ------------------------------------------------------- calibration / learn

BANDS = [(0, .55), (.55, .65), (.65, .75), (.75, .85), (.85, 1.01)]


def _legs(include_site: bool = True):
    """Settled legs to learn from: tracked bets, plus every best bet the site
    published (besttrack.py), so the calibration is fitted on the lot."""
    legs = [l for b in load() for l in b["legs"] if l["result"] in ("win", "lose")]
    if include_site:
        try:
            import besttrack
            legs += besttrack.calib_legs()
        except Exception:
            pass
    return legs


def fit_and_write() -> dict:
    legs = _legs()
    out = {"legs": len(legs), "prior": DEFAULT_PRIOR, "provisional": True, "bands": []}
    if legs:
        def loss(a):
            s = 0.0
            for l in legs:
                p = min(max((l["model_k"] + a) / (l["model_n"] + 2 * a), 1e-3), 1 - 1e-3)
                s -= math.log(p if l["result"] == "win" else 1 - p)
            return s
        grid = [x / 2 for x in range(0, 41)]
        best = min(grid, key=loss)
        out["fitted_prior"] = best
        if len(legs) >= MIN_FIT_LEGS:
            out["prior"], out["provisional"] = best, False
        for lo, hi in BANDS:
            band = [l for l in legs if lo <= l["model_k"] / max(l["model_n"], 1) < hi]
            if band:
                out["bands"].append({
                    "raw": f"{int(lo*100)}-{int(min(hi,1)*100)}%", "legs": len(band),
                    "said": round(sum(l["model_k"] / l["model_n"] for l in band) / len(band), 3),
                    "happened": round(sum(l["result"] == "win" for l in band) / len(band), 3)})
    CALIB.write_text(json.dumps(out, indent=2))
    _write_lessons(out, legs)
    return out


def _write_lessons(cal: dict, legs: list[dict]) -> None:
    bets = [b for b in load() if b["result"] in ("win", "lose")]
    lines = ["# Betting lessons (generated by bettrack.py, do not edit by hand)", "",
             f"Updated {datetime.now().strftime('%d %b %Y %H:%M')}. "
             f"{len(legs)} settled leg(s), {len(bets)} settled bet(s).", ""]
    if cal["provisional"]:
        lines += [f"**Provisional.** Fewer than {MIN_FIT_LEGS} settled legs, so prices still use "
                  f"the default pull of {DEFAULT_PRIOR:g} phantom hits and misses. The fit so far "
                  f"suggests {cal.get('fitted_prior', DEFAULT_PRIOR):g}.", ""]
    else:
        lines += [f"Raw records are pulled towards 50% by **{cal['prior']:g}** phantom hits and "
                  f"misses. A 6/10 record is worth {adjusted(6, 10, cal['prior']):.0%}, "
                  f"a 9/10 record {adjusted(9, 10, cal['prior']):.0%}.", ""]
    if cal["bands"]:
        lines += ["| Report said | Legs | Average said | Actually hit |", "|---|---|---|---|"]
        lines += [f"| {b['raw']} | {b['legs']} | {b['said']:.0%} | {b['happened']:.0%} |"
                  for b in cal["bands"]]
        lines.append("")
    by_kind = {}
    for b in bets:
        by_kind.setdefault(b["kind"], []).append(b)
    if by_kind:
        lines += ["| Bet type | Settled | Won | Profit (placed, priced only) |", "|---|---|---|---|"]
        for kind, bs in sorted(by_kind.items()):
            prof = sum(b["profit"] or 0 for b in bs if b.get("placed") and not b.get("backfilled"))
            lines.append(f"| {kind} | {len(bs)} | {sum(b['result']=='win' for b in bs)} | {prof:+.2f} |")
        lines.append("")
    misses = [l for l in legs if l["result"] == "lose" and l["model_k"] / l["model_n"] >= .6]
    if misses:
        lines += ["Recent misses the report rated 60%+:", ""]
        lines += [f"- {l['player']} {l['stat']} {l['line']:g}+ ({l['fixture']}): "
                  f"got {l['value']:g}, report had {l['model_k']}/{l['model_n']}"
                  for l in misses[-10:]]
    LESSONS.write_text("\n".join(lines) + "\n")


def report(args) -> None:
    cal = fit_and_write()
    print(LESSONS.read_text())
    open_ = [b for b in load() if b["result"] is None]
    if open_:
        print(f"{len(open_)} open bet(s): " + ", ".join(b["group"] for b in open_))


def fair(args) -> None:
    p = adjusted(args.k, args.n)
    print(f"{args.k}/{args.n} -> {p:.0%} after learning, fair price {1/p:.2f} "
          f"(prior {prior():g}{', provisional' if not CALIB.exists() or json.loads(CALIB.read_text()).get('provisional', True) else ''})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("log", help="log a leg (before kick-off)")
    a.add_argument("--event", type=int, required=True)
    a.add_argument("--player", required=True)
    a.add_argument("--stat", required=True)
    a.add_argument("--line", type=float, required=True, help="N for an N+ market")
    a.add_argument("--price", type=float, help="decimal odds for the whole bet")
    a.add_argument("--stake", type=float, default=1.0)
    a.add_argument("--kind", choices=["single", "ladder", "multi", "bb"], default="single")
    a.add_argument("--group", help="legs with the same group are one bet (multi / bet builder)")
    a.add_argument("--suggested", action="store_true", help="recommended, not placed")
    a.add_argument("--backfill", action="store_true")
    a.add_argument("--note")
    sub.add_parser("settle")
    sub.add_parser("report")
    f = sub.add_parser("fair")
    f.add_argument("k", type=int)
    f.add_argument("n", type=int)
    args = ap.parse_args()
    {"log": log, "settle": settle, "report": report, "fair": fair}[args.cmd](args)


if __name__ == "__main__":
    main()
