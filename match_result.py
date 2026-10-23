#!/usr/bin/env python3
"""Match-result accas: who wins, from the goals projection and the exchange.

    python match_result.py                     # every football fixture in the next 24 hours
    python match_result.py --league mls        # one report (its filename, without .html)
    python match_result.py --league mls --legs 3 --log
    python match_result.py settle              # settle logged accas from SofaScore
    python match_result.py report              # how the logged picks have done

Each report already carries projected goals for both sides. Two independent
Poisson counts off those give home, draw and away. That is a simplification
(real scorelines have a few more draws than independent Poissons allow), and
nothing in this repo has ever tested the goals projection on match results.
So the market is treated as the stronger opinion:

  * chance   the average of the model's and the market's probability
  * safe     legs ranked by chance, and only where the model and the market
             both make that side the favourite
  * value    legs where the model's probability beats the market's by at
             least --edge points, shown separately and never auto-added

Market prices are the Betfair back prices in market_prices.json, which the
gameweek update refreshes. A fixture without a price is skipped rather than
guessed. Commission is not taken off the price shown.

--log appends each acca and its legs to match_results.json. The record is
appended and settled, never edited, so after a few weeks report() says
whether the model's probabilities beat the market's on the same games. Until
then the value list is a list of disagreements, not an edge.
"""
from __future__ import annotations

import argparse
import json
import math
import probability
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import make_index
import weekend

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
PRICES = HERE / "market_prices.json"
STORE = HERE / "match_results.json"
MAX_GOALS = 10


def _pois(lam: float, k: int) -> float:
    return probability.poisson_pmf(k, lam)


def outcome_probs(home_goals: float, away_goals: float) -> tuple[float, float, float]:
    """Home, draw, away from two independent Poisson goal counts."""
    h = d = a = 0.0
    for i in range(MAX_GOALS + 1):
        pi = _pois(home_goals, i)
        for j in range(MAX_GOALS + 1):
            p = pi * _pois(away_goals, j)
            if i > j:
                h += p
            elif i == j:
                d += p
            else:
                a += p
    total = h + d + a
    return h / total, d / total, a / total


def _prices() -> dict:
    try:
        return json.loads(PRICES.read_text()).get("events", {})
    except Exception:
        return {}


def match_odds(event: dict) -> dict | None:
    """{'home': (back, p), 'draw': ..., 'away': ...} from the Betfair market.

    Runners are matched by position, home then away, with the draw found by
    name. 'swapped' means Betfair lists the fixture the other way round.
    """
    market = next((m for m in event.get("markets", []) if m.get("type") == "MATCH_ODDS"), None)
    if not market:
        return None
    draw = [r for r in market["runners"] if "draw" in r["name"].lower()]
    sides = [r for r in market["runners"] if "draw" not in r["name"].lower()]
    if len(draw) != 1 or len(sides) != 2:
        return None
    if event.get("swapped"):
        sides = sides[::-1]
    out = {}
    for key, r in (("home", sides[0]), ("away", sides[1]), ("draw", draw[0])):
        if not r.get("back") or not r.get("p"):
            return None
        out[key] = (float(r["back"]), float(r["p"]))
    out["matched"] = market.get("matched") or 0
    return out


def legs(league: str | None = None, hours: float = 24, now: float | None = None) -> list[dict]:
    """One leg per side per fixture still to kick off inside the window."""
    now = now or time.time()
    prices = _prices()
    paths = [REPORTS / f"{league}.html"] if league else sorted(
        p for p in REPORTS.glob("*.html") if not p.name.startswith("pick-"))
    out, seen = [], set()
    for path in paths:
        if not path.exists():
            raise SystemExit(f"no report called {path.name}; try one of: "
                             + ", ".join(p.stem for p in REPORTS.glob("*.html") if not p.name.startswith("pick-")))
        for entry, meta in make_index.read_entries(path):
            fid = meta["id"]
            if fid in seen or not (now < meta["kickoff"] < now + hours * 3600):
                continue
            if weekend.sport_of(entry) != "football":
                continue
            goals = ((entry.get("projection") or {}).get("ALL") or {}).get("Goals")
            odds = match_odds(prices.get(str(fid), {}))
            if not goals or len(goals) != 2 or not odds:
                continue
            seen.add(fid)
            model = dict(zip(("home", "draw", "away"), outcome_probs(*goals)))
            fav_model = max(model, key=model.get)
            fav_market = max(("home", "draw", "away"), key=lambda k: odds[k][1])
            for side in ("home", "away"):
                back, market_p = odds[side]
                out.append({
                    "event_id": fid, "kickoff": meta["kickoff"],
                    "competition": meta["competition"], "report": path.stem,
                    "fixture": f"{meta['home']} v {meta['away']}",
                    "team": meta["home"] if side == "home" else meta["away"],
                    "side": side, "goals": goals,
                    "model": model[side], "market": market_p,
                    "chance": (model[side] + market_p) / 2,
                    "back": back, "matched": odds["matched"],
                    "agree": fav_model == side and fav_market == side,
                    "result": None,
                })
    return out


def safe_acca(pool: list[dict], n: int) -> list[dict]:
    picks = sorted((l for l in pool if l["agree"]), key=lambda l: -l["chance"])
    out, used = [], set()
    for leg in picks:
        if leg["event_id"] in used:
            continue
        out.append(leg)
        used.add(leg["event_id"])
        if len(out) == n:
            break
    return out


def value_legs(pool: list[dict], edge: float) -> list[dict]:
    return sorted((l for l in pool if l["model"] - l["market"] >= edge),
                  key=lambda l: -(l["model"] - l["market"]))


def _uk(ts: float) -> str:
    return datetime.fromtimestamp(ts, ZoneInfo("Europe/London")).strftime("%a %H:%M")


def _row(leg: dict) -> str:
    return (f"  {leg['team']:<26} {leg['fixture']:<44} {_uk(leg['kickoff'])}  "
            f"back {leg['back']:>5.2f}  model {leg['model']:>4.0%}  market {leg['market']:>4.0%}  "
            f"chance {leg['chance']:>4.0%}")


def show(args) -> None:
    pool = legs(args.league, args.hours)
    if not pool:
        print("No priced fixtures in that window. The gameweek update refreshes the prices.")
        return
    acca = safe_acca(pool, args.legs)
    if len(acca) < args.legs:
        print(f"Only {len(acca)} fixture(s) where the model and the market agree on a winner.")
    if acca:
        price = math.prod(l["back"] for l in acca)
        chance = math.prod(l["chance"] for l in acca)
        print(f"\nSafest {len(acca)}-leg win acca: price {price:.2f}, chance {chance:.0%}, "
              f"fair {1 / chance:.2f}")
        for leg in acca:
            print(_row(leg))
    vals = value_legs(pool, args.edge)
    if vals:
        print(f"\nModel above the market by {args.edge:.0%}+ (untested, singles only):")
        for leg in vals:
            print(_row(leg))
    if args.log and acca:
        items = load()
        items.append({"logged": time.time(), "kind": "safe", "legs": acca,
                      "price": math.prod(l["back"] for l in acca), "result": None})
        for leg in vals:
            items.append({"logged": time.time(), "kind": "value", "legs": [leg],
                          "price": leg["back"], "result": None})
        save(items)
        print(f"\nLogged to {STORE.name}.")


def load() -> list[dict]:
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return []


def save(items: list[dict]) -> None:
    STORE.write_text(json.dumps(items, indent=1))


def settle(args=None) -> None:
    import sofascore_api as api
    items, now, done = load(), time.time(), 0
    for item in items:
        if item["result"] is not None:
            continue
        for leg in item["legs"]:
            if leg["result"] is not None or leg["kickoff"] > now - 3 * 3600:
                continue
            ev = api.get_json(f"event/{leg['event_id']}", max_age_hours=1, verbose=False) or {}
            ev = ev.get("event", ev)
            status = (ev.get("status") or {}).get("type")
            if status in ("canceled", "postponed"):
                leg["result"] = "void"
            elif status == "finished":
                h = (ev.get("homeScore") or {}).get("current")
                a = (ev.get("awayScore") or {}).get("current")
                if h is None or a is None:
                    continue
                leg["score"] = f"{h}-{a}"
                won = h > a if leg["side"] == "home" else a > h
                leg["result"] = "win" if won else "lose"
                done += 1
        if all(l["result"] is not None for l in item["legs"]):
            live = [l for l in item["legs"] if l["result"] != "void"]
            item["result"] = ("void" if not live else
                              "win" if all(l["result"] == "win" for l in live) else "lose")
    save(items)
    print(f"settled {done} leg(s), {sum(1 for i in items if i['result'] is None)} bet(s) open")


def report(args=None) -> None:
    items = load()
    settled = [i for i in items if i["result"] in ("win", "lose")]
    if not settled:
        print("Nothing settled yet.")
        return
    for kind in ("safe", "value"):
        group = [i for i in settled if i["kind"] == kind]
        if group:
            wins = sum(1 for i in group if i["result"] == "win")
            profit = sum((i["price"] - 1) if i["result"] == "win" else -1 for i in group)
            print(f"{kind}: {wins}/{len(group)} won, {profit:+.2f} units at 1 unit each")
    # The real question: on the same legs, whose probabilities were closer?
    seen, model_b, market_b = set(), 0.0, 0.0
    for i in settled:
        for leg in i["legs"]:
            key = (leg["event_id"], leg["side"])
            if leg["result"] not in ("win", "lose") or key in seen:
                continue
            seen.add(key)
            y = 1.0 if leg["result"] == "win" else 0.0
            model_b += (leg["model"] - y) ** 2
            market_b += (leg["market"] - y) ** 2
    if seen:
        n = len(seen)
        print(f"Brier on {n} legs: model {model_b / n:.3f}, market {market_b / n:.3f} "
              f"(lower is better; under 100 legs this is noise)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="show", choices=("show", "settle", "report"))
    ap.add_argument("--league", help="report name, e.g. mls, premier-league")
    ap.add_argument("--legs", type=int, default=2)
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--edge", type=float, default=0.10, help="model minus market, default 0.10")
    ap.add_argument("--log", action="store_true", help="append the acca to match_results.json")
    args = ap.parse_args(argv)
    {"show": show, "settle": settle, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
