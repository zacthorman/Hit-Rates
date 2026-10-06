"""
The rolling challenge: a 1.8 to 2.2 bet, then the whole return on the next.

    python challenge.py start --stake 10            # new run, everything rolls
    python challenge.py start --stake 10 --bank half  # bank half of each profit
    python challenge.py log --event 16184622 --player "Jaylen Warren" \\
        --stat "Rushing and receiving yards" --line 60 --price 1.96
    python challenge.py log --event 16184622 --player "Harold Fannin Jr." \\
        --stat "Receiving yards" --line 30          # second leg, same step
    python challenge.py status                      # pot, step, record

Each step is an ordinary bettrack.py bet (group "ch<run>-s<step>"), so it is
settled from the box score by `bettrack.py settle` like everything else and
feeds the same calibration. This file only remembers the runs and works out
the pot from how each step settled. A void step returns the stake and the run
carries on at the same step number with a fresh bet.

Prices outside 1.80 to 2.20 are refused: the point of the challenge is the
fixed band, and a 1.5 "to get through tonight" is how it stops meaning anything.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import bettrack

HERE = Path(__file__).parent
STATE = HERE / "challenge.json"
LOW, HIGH = 1.80, 2.20


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"runs": []}


def save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=2))


def _group(run_id: int, step: int, retry: int) -> str:
    return f"ch{run_id}-s{step}" + (f"v{retry}" if retry else "")


def walk(run: dict, bets: list[dict]) -> dict:
    """Replay one run against bets.json: pot, banked, steps, and whether it is alive."""
    pot, banked = float(run["stake"]), 0.0
    steps, step, retry = [], 1, 0
    alive, open_bet = True, None
    by_group = {b["group"]: b for b in bets}
    while True:
        group = _group(run["id"], step, retry)
        b = by_group.get(group)
        if b is None:
            break
        res = b.get("result")
        steps.append({"step": step, "group": group, "price": b.get("price"),
                      "stake": round(pot, 2), "result": res or "open", "legs": b["legs"]})
        if res is None:
            open_bet = group
            break
        if res == "void":          # stake back, same step, fresh bet
            retry += 1
            continue
        if res == "lose":
            alive, pot = False, 0.0
            break
        profit = pot * ((b.get("price") or 1) - 1)
        if run.get("bank") == "half":
            banked += profit / 2
            pot += profit / 2
        else:
            pot += profit
        step, retry = step + 1, 0
        if run.get("cashout") and step > run["cashout"]:
            break
    cashed = bool(alive and run.get("cashout") and step > run["cashout"])
    return {"pot": round(pot, 2), "banked": round(banked, 2), "steps": steps,
            "alive": alive and not cashed, "cashed": cashed,
            "next_step": step, "next_retry": retry, "open": open_bet,
            # What this run made or lost against its own starting stake.
            "profit": round((pot + banked - run["stake"]) if (cashed or not alive) else 0.0, 2)}


def current() -> tuple[dict, dict] | tuple[None, None]:
    s = load()
    if not s["runs"]:
        return None, None
    run = s["runs"][-1]
    return run, walk(run, bettrack.load())


def start(args) -> None:
    run, st = current()
    if run and st["alive"] and st["steps"] and not args.force:
        raise SystemExit(f"Run {run['id']} is still alive at step {st['next_step']} "
                         f"with £{st['pot']:.2f}. Finish it, or --force to abandon it.")
    s = load()
    rid = (s["runs"][-1]["id"] + 1) if s["runs"] else 1
    cashout = args.cashout if args.cashout is not None else \
        (s["runs"][-1].get("cashout") if s["runs"] else None)
    target = args.target if args.target is not None else \
        (s.get("target") or None)
    if target:
        s["target"] = target
    s["runs"].append({"id": rid, "stake": args.stake, "bank": args.bank, "cashout": cashout,
                      "started": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")})
    save(s)
    print(f"Run {rid} started: £{args.stake:.2f}, "
          f"{'banking half of each profit' if args.bank == 'half' else 'everything rolls'}"
          + (f", cash out after {cashout} wins" if cashout else "") + ".")


def log(args) -> None:
    run, st = current()
    if not run:
        raise SystemExit("No run yet: python challenge.py start --stake 10")
    if not st["alive"]:
        how = "cashed out" if st.get("cashed") else "bust"
        raise SystemExit(f"Run {run['id']} is {how}. Start the next: python challenge.py start")
    if st["open"]:
        group = st["open"]
        existing = next(b for b in bettrack.load() if b["group"] == group)
        if any(l["result"] is not None for l in existing["legs"]):
            raise SystemExit("This step has started settling. Wait for it.")
    else:
        if not args.price:
            raise SystemExit("First leg of a step needs --price for the whole bet.")
        group = _group(run["id"], st["next_step"], st["next_retry"])
    if args.price and not LOW <= args.price <= HIGH:
        raise SystemExit(f"{args.price:.2f} is outside the {LOW:.2f} to {HIGH:.2f} band.")
    # Is he actually starting? Twice in a week a pick was on a man on the bench.
    if not getattr(args, "backfill", False):
        try:
            import lineups
            lu = lineups.lineup(args.event)
        except Exception:
            lu = None
        if lu:
            confirmed, starters, bench = lu
            starting = {n for side in starters.values() for n in side if n}
            benched = {n for side in bench.values() for n in side if n}
            if args.player not in starting:
                where = "on the bench" if args.player in benched else "not in the squad"
                if confirmed and not getattr(args, "force", False):
                    raise SystemExit(f"{args.player} is {where} in the confirmed line-up. "
                                     "Not logged. (--force to log anyway.)")
                print(f"  WARNING: {args.player} is {where} in the "
                      f"{'confirmed' if confirmed else 'predicted'} line-up")
            else:
                print(f"  {args.player} is in the {'confirmed' if confirmed else 'predicted'} starting XI")
        else:
            print("  line-up not out yet: check it before kick-off (python lineups.py)")
    ns = argparse.Namespace(
        event=args.event, player=args.player, stat=args.stat, line=args.line,
        price=args.price, stake=st["pot"], kind="multi", group=group,
        suggested=False, backfill=getattr(args, "backfill", False),
        note=f"challenge run {run['id']}")
    bettrack.log(ns)
    print(f"  step {st['next_step']} of run {run['id']}, staking £{st['pot']:.2f}")


def team(args) -> None:
    """A team-market leg (shots on target, corners, cards), settled from match stats."""
    run, st = current()
    if not run:
        raise SystemExit("No run yet: python challenge.py start --stake 10")
    if not st["alive"]:
        raise SystemExit(f"Run {run['id']} is over. Start the next: python challenge.py start")
    fx, source = bettrack._report_fixture(args.event)
    if not fx:
        raise SystemExit(f"Event {args.event} is not in any built report.")
    F = fx["fixture"]
    names = [t["name"] for t in fx["teams"]]
    if args.team not in names:
        raise SystemExit(f"Team must be one of: {', '.join(names)}")
    late = (F.get("kickoff") or 0) <= bettrack.now()
    if late and not args.backfill:
        raise SystemExit("Already kicked off. Add --backfill if the bet was placed before kick-off.")
    recs = fx["records"][names.index(args.team)]
    vals = [r["stats"].get("ALL", {}).get(args.stat) for r in recs]
    vals = [v for v in vals if v is not None][-10:]
    k = sum((v > args.line) if not args.under else (v < args.line) for v in vals)
    bets = bettrack.load()
    group = st["open"] or _group(run["id"], st["next_step"], st["next_retry"])
    bet = next((b for b in bets if b["group"] == group), None)
    if bet is None:
        if not args.price:
            raise SystemExit("First leg of a step needs --price for the whole bet.")
        if not LOW <= args.price <= HIGH:
            raise SystemExit(f"{args.price:.2f} is outside the {LOW:.2f} to {HIGH:.2f} band.")
        bet = {"group": group, "kind": "single", "logged_at":
               datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
               "price": args.price, "stake": st["pot"], "backfilled": bool(late),
               "placed": True, "legs": [], "result": None, "profit": None,
               "note": f"challenge run {run['id']}"}
        bets.append(bet)
    else:
        bet["kind"] = "multi"
    bet["legs"].append({
        "event_id": args.event, "fixture": f"{F['home']} v {F['away']}",
        "kickoff": F.get("kickoff") or 0, "player": args.team, "player_id": None,
        "team": args.team, "team_leg": True, "stat": args.stat, "period": "ALL",
        "line": args.line, "over": not args.under, "model_k": k, "model_n": len(vals),
        "model_p": round(bettrack.adjusted(k, len(vals)), 3), "source": source,
        "value": None, "result": None})
    bettrack.save(bets)
    side = "under" if args.under else "over"
    print(f"  logged [{group}] {args.team} {args.stat} {side} {args.line:g} "
          f"- last {len(vals)} {k}/{len(vals)}" + (" (backfilled)" if late else ""))
    print(f"  step {st['next_step']} of run {run['id']}, staking £{st['pot']:.2f}")


def status(args=None) -> None:
    run, st = current()
    if not run:
        print("No challenge run yet.")
        return
    print(f"Run {run['id']} (started {run['started'][:10]}, £{run['stake']:.2f}, "
          f"{run.get('bank') or 'all'}): "
          + ("ALIVE" if st["alive"] else "CASHED OUT" if st.get("cashed") else "BUST"))
    for x in st["steps"]:
        legs = " + ".join(f"{l['player']} {l['stat']} {l['line']:g}+" for l in x["legs"])
        price = f"{x['price']:.2f}" if x["price"] else "?"
        print(f"  step {x['step']}: £{x['stake']:.2f} @ {price}  {x['result']:5}  {legs}")
    if st["alive"]:
        print(f"Pot £{st['pot']:.2f}" + (f", banked £{st['banked']:.2f}" if st["banked"] else "")
              + (f". Waiting on {st['open']}." if st["open"] else f". Next: step {st['next_step']}."))
    s = load()
    walks = [walk(r, bettrack.load()) for r in s["runs"]]
    total = sum(w["profit"] for w in walks)
    target = s.get("target")
    print(f"Challenge total: £{total:+.2f} over {len(s['runs'])} run(s)"
          + (f", target £{target:.0f} (£{max(0, target - total):.2f} to go)" if target else ""))
    if len(s["runs"]) > 1:
        best = max((walk(r, bettrack.load()) for r in s["runs"]),
                   key=lambda w: sum(1 for x in w["steps"] if x["result"] == "win"))
        wins = sum(1 for x in best["steps"] if x["result"] == "win")
        print(f"Best run so far: {wins} step(s) won.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("start")
    a.add_argument("--stake", type=float, default=10.0)
    a.add_argument("--bank", choices=["all", "half"], default="all")
    a.add_argument("--force", action="store_true")
    a.add_argument("--cashout", type=int, help="end the run and bank it after this many wins")
    a.add_argument("--target", type=float, help="total profit the challenge is aiming for")
    b = sub.add_parser("log")
    b.add_argument("--event", type=int, required=True)
    b.add_argument("--player", required=True)
    b.add_argument("--stat", required=True)
    b.add_argument("--line", type=float, required=True)
    b.add_argument("--price", type=float)
    b.add_argument("--backfill", action="store_true")
    b.add_argument("--force", action="store_true")
    t = sub.add_parser("team", help="team market leg: shots on target, corners, cards")
    t.add_argument("--event", type=int, required=True)
    t.add_argument("--team", required=True)
    t.add_argument("--stat", required=True)
    t.add_argument("--line", type=float, required=True, help="e.g. 3.5 for 4+")
    t.add_argument("--under", action="store_true")
    t.add_argument("--price", type=float)
    t.add_argument("--backfill", action="store_true")
    sub.add_parser("status")
    args = ap.parse_args()
    {"start": start, "log": log, "team": team, "status": status}[args.cmd](args)


if __name__ == "__main__":
    main()
