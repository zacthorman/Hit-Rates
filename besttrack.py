"""
Track every best bet the SITE publishes, settle it, and explain what hits.

    python besttrack.py snapshot   # record the site's current best bets (pre-kick-off only)
    python besttrack.py settle     # settle finished fixtures from SofaScore
    python besttrack.py report     # print the summary
    python besttrack.py leads      # give every logged lead a leg to settle (settle does this too)

bettrack.py records the bets a person placed or Claude suggested. This one
records what the site itself put forward, automatically, every time it
publishes: the picks of the week (single, acca, same-game builder, parlay) and
each fixture's top singles from tonight.html. Nothing is chosen by hand, so
the record cannot be flattered by only logging the good-looking ones.

Rules:
  * a bet is only recorded while every leg is still before kick-off
  * the same bet seen on a later publish is not recorded twice
  * a player who did not play voids his leg; it is not a loss
  * the record is never edited, only appended and settled

The summary (best_bets_summary() below) is what the "Best bets summary" page
renders: how often each kind of bet lands against what the site said, broken
down by market, sport, rate band and bet type, with the misses laid out so
the reason is visible -- a near miss and a blowout are different problems.
Settled legs also feed bettrack's calibration, so the learned shrinkage is
fitted on everything the site has ever recommended, not just what was placed.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

HERE = Path(__file__).parent
STORE = HERE / "best_bets.json"
WINDOW_HOURS = 48
TOP_SINGLES = 3


def load() -> list[dict]:
    return json.loads(STORE.read_text()) if STORE.exists() else []


def save(items: list[dict]) -> None:
    STORE.write_text(json.dumps(items, indent=1))


# -------------------------------------------------------------- snapshot

def _leg(leg: dict, meta: dict, sport: str) -> dict:
    fx = leg.get("fixture") or meta or {}
    return {
        "event_id": fx.get("id"), "fixture": f"{fx.get('home')} v {fx.get('away')}",
        "competition": fx.get("competition"), "kickoff": fx.get("kickoff") or 0,
        "sport": sport, "team": leg.get("team"), "player": leg.get("player"),
        "stat": leg.get("stat"), "period": leg.get("period") or "ALL",
        "line": leg.get("line"), "over": bool(leg.get("over", True)),
        "alt": bool(leg.get("alt")), "threshold": leg.get("threshold"),
        "hits": leg.get("hits"), "total": leg.get("total"),
        "fair": leg.get("fair"), "venue": leg.get("venue"),
        # The calibrated chance the pick was ranked on, and the strength
        # context behind it, so a later calibration check can score the
        # number the site actually used rather than reconstruct it.
        "chance": leg.get("chance") or leg.get("pStrength") or leg.get("pShrunk"),
        # Before the self-correction: what learner.py learns from, so it
        # never fits its own output.
        "chance_base": leg.get("chanceBase") or leg.get("pBase"),
        # The exchange at snapshot time: its chance, the back price you could
        # have taken, and the model's own chance before the blend. With these
        # the record can say whether the picks made money, not only whether
        # they landed.
        "exchange_p": (leg.get("exchange") or {}).get("p") if leg.get("exchange") else None,
        "exchange_back": (leg.get("exchange") or {}).get("back") if leg.get("exchange") else None,
        "chance_model": leg.get("chanceModel") or leg.get("pModel"),
        "chance_anchored": leg.get("chanceAnchored") or leg.get("pAnchored"),
        "exchange_kind": (leg.get("exchange") or {}).get("kind") if leg.get("exchange") else None,
        "value_at_pick": leg.get("value"),
        "fair_record": leg.get("fairRecord"),
        "elo": ([(leg.get("strength") or {}).get("team"), (leg.get("strength") or {}).get("opp")]
                if leg.get("strength") else None),
        # The bookmaker price the pick was built at (weekend.attach_books, 23
        # Oct 2026): which book, its price, and whether it was inside the
        # BOOK_MAX_OVER window so the pick actually used it. With these the
        # record can score the picks at prices you could get, not only at
        # our fair price. Added 26 Oct 2026; older records have none.
        "book_name": (leg.get("book") or {}).get("name"),
        "book_price": (leg.get("book") or {}).get("price"),
        "book_used": _book_used(leg),
        "value": None, "result": None,
    }


def _book_used(leg: dict):
    """Whether the pick took the book's price (weekend._book_ok), or None if
    no book priced the leg."""
    if not leg.get("book"):
        return None
    try:
        import weekend
        return bool(weekend._book_ok(leg))
    except Exception:
        return None


def _key(item: dict) -> str:
    legs = sorted(f"{l['event_id']}|{l['player'] or l['team']}|{l['stat']}|{l['period']}|"
                  f"{l['line']}|{l['over']}" for l in item["legs"])
    return item["category"] + "::" + "::".join(legs)


def snapshot(args=None) -> int:
    import make_index
    import parlay
    import tonight
    import value_cap
    import weekend

    now = time.time()
    entries = []
    for path in sorted((HERE / "reports").glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        entries.extend(make_index.read_entries(path))
    # One copy of each fixture: the newest report's.
    seen, unique = set(), []
    for e, m in sorted(entries, key=lambda x: -(HERE / "reports" / x[1]["report"]).stat().st_mtime):
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        unique.append((e, m))
    upcoming = [(e, m) for e, m in unique
                if now < (m["kickoff"] or 0) <= now + WINDOW_HOURS * 3600]

    new: list[dict] = []

    def add(category, legs_raw, sport, fair=None, meta=None, extra=None):
        legs = [_leg(l, meta, sport) for l in legs_raw if l]
        if not legs or any((l["kickoff"] or 0) <= now for l in legs):
            return
        item = {"category": category, "sport": sport, "snapshot_at": int(now),
                "fair": fair, "legs": legs, "result": None, **(extra or {})}
        new.append(item)

    picks = weekend.picks(upcoming, days=WINDOW_HOURS / 24) or {"sports": []}
    for s in picks["sports"]:
        sport = s["sport"]
        if s.get("single"):
            add("Pick: single", [s["single"]], sport, s["single"].get("fair"))
        if s.get("double"):
            add("Pick: evens double", s["double"]["legs"], sport, s["double"].get("combined"),
                extra={"priced": s["double"].get("priced"),
                       "fair_ours": s["double"].get("combinedFair")})
        if s.get("banker"):
            add("Pick: banker", [s["banker"]], sport, s["banker"].get("fair"))
        if s.get("acca"):
            add("Pick: acca", s["acca"]["legs"], sport, s["acca"].get("combined"),
                extra={"priced": s["acca"].get("priced"),
                       "fair_ours": s["acca"].get("combinedFair")})
        if s.get("builder"):
            b = s["builder"]
            add("Pick: builder", b["legs"], sport, b.get("fair"), b.get("fixture"))
        if s.get("parlay"):
            p = s["parlay"]
            add("Pick: parlay", p["legs"], sport, p.get("fair"), p.get("fixture"))

    for entry, meta in upcoming:
        sport = weekend.sport_of(entry)
        # One leg per player, as tonight.html shows them (value_cap.py).
        own = value_cap.cap_per_player(
            sorted([l for l in tonight.legs_of(entry, meta)
                    if isinstance(l.get("fair"), (int, float)) and l["fair"] >= tonight.MIN_PRICE],
                   key=lambda l: (-weekend.sort_value(l), -(l.get("total") or 0))))[:TOP_SINGLES]
        for l in own:
            add("Fixture single", [l], sport, l.get("fair"), meta)
        # The player lines tonight.html shows, exactly as shown, so they are
        # judged like every other pick the site puts forward.
        try:
            import playerlines
            import bettable
            for l in playerlines.suggest(entry, meta):
                if bettable.ok(l, meta, sport):
                    add("Player line", [l], sport, l.get("fair"), meta)
        except Exception as exc:
            print(f"  player lines not recorded for {meta.get('home')} v {meta.get('away')}: {exc}")

    items = load()
    have = {_key(i) for i in items}
    added = track_leads(items)
    for item in new:
        k = _key(item)
        if k in have:
            continue
        have.add(k)
        items.append(item)
        added += 1
    save(items)
    print(f"best bets: {added} new recorded, {len(items)} in the record")
    return added


# --------------------------------------------------------------- the leads
#
# tonight.py logs each fixture's lead to lead_log.json and its results card
# settles it against this record. But the lead is chosen on the game-state
# chance, and the fixture singles above on weekend.sort_value, so a lead
# could fall outside the top three and never be recorded: 15 of the first
# 53 leads (21-22 Oct 2026) had nothing to settle them. So every logged lead
# whose exact leg is not already here is added as a "Lead". lead_log.json
# only takes a lead before kick-off, so the pre-kick-off rule still holds;
# snapshot_at is when the lead was written, not when it was copied here.

LEAD_LOG = HERE / "lead_log.json"
LEAD_KEY = ("event_id", "team", "player", "stat", "period", "line", "over")
# Older lead_log rows carry no sport; these are the competitions they came from.
SPORT_BY_COMPETITION = {"NBA": "basketball", "NFL": "american-football",
                        "MLB": "baseball", "MLB Postseason": "baseball"}


def _lead_sport(row: dict, known: dict) -> str:
    if row.get("sport"):
        return row["sport"]
    if row["event_id"] in known:
        return known[row["event_id"]]
    comp = row.get("competition") or ""
    if "darts" in comp.lower():
        return "darts"
    return SPORT_BY_COMPETITION.get(comp, "football")


def track_leads(items: list[dict]) -> int:
    """Add a "Lead" item for every logged lead with no leg in the record. Returns how many."""
    try:
        log = json.loads(LEAD_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    have = {tuple(l.get(k) for k in LEAD_KEY) for i in items for l in i["legs"]}
    known = {l["event_id"]: l["sport"] for i in items for l in i["legs"] if l.get("sport")}
    added = 0
    for row in sorted(log.values(), key=lambda r: r["kickoff"]):
        k = tuple(row.get(f) for f in LEAD_KEY)
        if k in have or not row.get("written") or row["written"] >= row["kickoff"]:
            continue
        home, _, away = row["fixture"].partition(" v ")
        leg = _leg({f: row.get(f) for f in LEAD_KEY if f != "event_id"} | {"fair": row.get("fair")},
                   {"id": row["event_id"], "home": home, "away": away,
                    "competition": row.get("competition"), "kickoff": row["kickoff"]},
                   _lead_sport(row, known))
        leg["chance"] = row.get("chance") or None
        items.append({"category": "Lead", "sport": leg["sport"], "snapshot_at": int(row["written"]),
                      "fair": row.get("fair"), "legs": [leg], "result": None})
        have.add(k)
        added += 1
    return added


def leads(args=None) -> int:
    items = load()
    added = track_leads(items)
    if added:
        save(items)
    print(f"best bets: {added} lead(s) given a leg to settle")
    return added


# ---------------------------------------------------------------- settle

def _team_value(leg, ev, stats):
    import hitrates
    home = (ev.get("homeTeam") or {}).get("name")
    idx = 0 if leg["team"] == home else 1
    period = leg["period"]
    if leg["stat"] in ("Goals", "Points"):
        key = {"ALL": "current", "1ST": "period1", "2ND": "period2"}.get(period, "current")
        hs = (ev.get("homeScore") or {}).get(key)
        as_ = (ev.get("awayScore") or {}).get(key)
        if hs is None or as_ is None:
            return None
        return float((hs, as_)[idx])
    bucket = stats.get(period, {})
    if leg["stat"] in bucket:
        return float(bucket[leg["stat"]][idx])
    if period in ("1ST", "2ND"):
        # The feed leaves a half's card row out when nobody was booked in it. An
        # empty bucket means no half stats at all, so leave the leg unsettled.
        if "card" in leg["stat"].lower() and bucket:
            return 0.0
        return None
    # Match-level markets and card rows the feed leaves out when both are 0.
    own = {k: v[idx] for k, v in stats.get("ALL", {}).items()}
    opp = {k: v[1 - idx] for k, v in stats.get("ALL", {}).items()}
    own["Goals"] = float(((ev.get("homeScore") or {}).get("current"), (ev.get("awayScore") or {}).get("current"))[idx] or 0)
    opp["Goals"] = float(((ev.get("homeScore") or {}).get("current"), (ev.get("awayScore") or {}).get("current"))[1 - idx] or 0)
    rec = {"stats": {"ALL": own}, "against": {"ALL": opp}}
    hitrates._add_match_markets(rec)
    if leg["stat"] in rec["stats"]["ALL"]:
        return float(rec["stats"]["ALL"][leg["stat"]])
    if "card" in leg["stat"].lower() and stats:
        return 0.0
    return None


def _player_value(leg, sport):
    import hitrates
    import markets
    import sofascore_api as api
    import time
    # The line-ups must have been read after the match, not before it. This
    # took any copy up to six hours old, and lineups_auto.py saves one about
    # an hour before kick-off, with no statistics in it. Every football
    # player in it then settled on zero: on 20 Oct 2026 the pp log graded
    # 0 of 46 fouls lines and 0 of 66 fouled lines a win, and -460 units.
    # Settling waits until three hours after kick-off, so anything saved
    # before that is from before the final whistle and is fetched again.
    after = max(0.05, (time.time() - leg["kickoff"]) / 3600 - 3)
    data = api.get_json(f"event/{leg['event_id']}/lineups", max_age_hours=after, verbose=False) or {}
    fill = markets.ZERO_FILL_BY_SPORT.get(sport, hitrates.PLAYER_ZERO_FILL) or hitrates.PLAYER_ZERO_FILL
    for side in ("home", "away"):
        for p in (data.get(side) or {}).get("players", []) or []:
            if (p.get("player") or {}).get("name") == leg["player"]:
                # No statistics at all is a player who never came on (or a
                # copy from before the match): a void, never a zero.
                st = p.get("statistics") or {}
                if not st:
                    return "dnp"
                # An unused substitute is listed with a statistics block but
                # no minutes: a void, not a zero. 20 Oct 2026: 52 of the
                # Champions League fouls and shots lines were graded lost
                # this way (Akhomach, Kerkez and others on the bench).
                mins_key = {"football": "minutesPlayed", "basketball": "secondsPlayed"}.get(sport)
                if mins_key and not st.get(mins_key):
                    return "dnp"
                # Who started and for how long, for the pp log (31 Oct 2026):
                # Paddy prices football props as if every player starts, so a
                # backtest has to be able to keep only the starters.
                leg["started"] = not p.get("substitute", False)
                if mins_key:
                    leg["minutes"] = round(st.get(mins_key, 0) / (60 if mins_key == "secondsPlayed" else 1), 1)
                vals = hitrates._player_stat_values(p.get("statistics") or {}, zero_fill=fill)
                return vals.get(leg["stat"], 0.0) if vals else "dnp"
    return "dnp"


def settle(args=None) -> int:
    import hitrates
    import sofascore_api as api
    items = load()
    if track_leads(items):
        save(items)
    now = time.time()
    done = 0
    events: dict = {}
    for item in items:
        if item["result"] is not None:
            continue
        for leg in item["legs"]:
            if leg["result"] is not None or leg["kickoff"] > now - 3 * 3600:
                continue
            eid = leg["event_id"]
            if eid not in events:
                ev = api.get_json(f"event/{eid}", max_age_hours=1, verbose=False) or {}
                ev = ev.get("event", ev)
                stats = hitrates.extract_match_stats(api.event_statistics(eid)) \
                    if (ev.get("status") or {}).get("type") == "finished" else None
                events[eid] = (ev, stats)
            ev, stats = events[eid]
            status = (ev.get("status") or {}).get("type")
            if status in ("canceled", "postponed"):
                leg["result"] = "void"
                continue
            if status != "finished":
                continue
            v = _player_value(leg, leg["sport"]) if leg["player"] else _team_value(leg, ev, stats or {})
            if v is None:
                continue
            if v == "dnp":
                leg["result"] = "void"
            else:
                leg["value"] = v
                won = v > leg["line"] if leg["over"] else v < leg["line"]
                leg["result"] = "win" if won else "lose"
            done += 1
        if all(l["result"] is not None for l in item["legs"]):
            live = [l for l in item["legs"] if l["result"] != "void"]
            item["result"] = ("void" if not live else
                              "win" if all(l["result"] == "win" for l in live) else "lose")
    save(items)
    print(f"best bets: settled {done} leg(s), "
          f"{sum(1 for i in items if i['result'] is None)} bet(s) still open")
    # Split against one-side parlays on tickets from 24 Oct 2026 on
    # (parlay_watch.py, LEG-WATCH.md). Reads the record only; never lets a
    # fault in it cost the settle.
    # Written beside the store being settled, so anything that points STORE
    # elsewhere (the tests do) takes the watch with it.
    try:
        import parlay_watch
        print(parlay_watch.text(parlay_watch.update(items, path=Path(STORE).with_name(parlay_watch.OUT_NAME))))
    except Exception as exc:
        print(f"  parlay watch skipped: {type(exc).__name__}: {exc}")
    return done


# ------------------------------------------------------------- analysis

def calib_legs() -> list[dict]:
    """Settled site legs in bettrack's shape, so calibration learns from them."""
    out = []
    for item in load():
        for l in item["legs"]:
            if l["result"] in ("win", "lose") and l.get("total"):
                out.append({"model_k": l["hits"], "model_n": l["total"], "result": l["result"],
                            "player": l["player"] or l["team"], "stat": l["stat"],
                            "line": l["line"], "fixture": l["fixture"], "value": l["value"]})
    return out


def _tail(k, n, p):
    """P(X <= k) for Binomial(n, p): how surprising a shortfall is.

    Summed in log space: math.comb(n, i) outgrows a float once n passes about
    a thousand, which the record did on 19 Oct 2026 and which crashed
    bets_page.py with an OverflowError."""
    if n <= 0:
        return 1.0
    p = min(max(p, 1e-12), 1 - 1e-12)
    lp, lq = math.log(p), math.log1p(-p)
    lg = math.lgamma(n + 1)
    return min(1.0, sum(math.exp(lg - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                        for i in range(k + 1)))


def _market_kind(l):
    s = (l["stat"] or "").lower()
    if "yards" in s:
        return "Yards"
    if any(w in s for w in ("receptions", "attempts", "completions", "carries")):
        return "Counts (catches, carries, attempts)"
    if "card" in s or "foul" in s:
        return "Cards and fouls"
    if "corner" in s:
        return "Corners"
    if "shot" in s:
        return "Shots"
    if s in ("goals", "points", "both teams to score", "match goals", "touchdowns"):
        return "Goals and scoring"
    return "Other"


def group_table(legs, keyf):
    groups: dict = {}
    for l in legs:
        groups.setdefault(keyf(l), []).append(l)
    rows = []
    for key, ls in groups.items():
        n = len(ls)
        won = sum(l["result"] == "win" for l in ls)
        said = sum(l["hits"] / l["total"] for l in ls) / n
        rows.append({"group": key, "legs": n, "won": won, "said": said, "hit": won / n,
                     "gap": won / n - said, "surprise": _tail(won, n, min(said, .999))})
    rows.sort(key=lambda r: -r["legs"])
    return rows


def best_bets_summary() -> dict:
    items = load()
    legs = [l for i in items for l in i["legs"] if l["result"] in ("win", "lose") and l.get("total")]
    bets = [i for i in items if i["result"] in ("win", "lose")]
    out = {"open": sum(1 for i in items if i["result"] is None),
           "bets_settled": len(bets), "bets_won": sum(i["result"] == "win" for i in bets),
           "legs_settled": len(legs), "legs_won": sum(l["result"] == "win" for l in legs),
           "said": (sum(l["hits"] / l["total"] for l in legs) / len(legs)) if legs else None}
    out["by_category"] = group_table(
        [dict(l, _cat=i["category"]) for i in items for l in i["legs"]
         if l["result"] in ("win", "lose") and l.get("total")], lambda l: l["_cat"])
    out["by_bet"] = []
    cats: dict = {}
    for i in bets:
        cats.setdefault(i["category"], []).append(i)
    for c, bs in sorted(cats.items()):
        fair = [1 / b["fair"] for b in bs if b.get("fair")]
        out["by_bet"].append({"group": c, "bets": len(bs), "won": sum(b["result"] == "win" for b in bs),
                              "said": sum(fair) / len(fair) if fair else None})
    out["by_market"] = group_table(legs, _market_kind)
    out["by_sport"] = group_table(legs, lambda l: {"american-football": "NFL"}.get(l["sport"], l["sport"].title()))
    out["by_side"] = group_table(legs, lambda l: ("Player " if l["player"] else "Team ") + ("overs" if l["over"] else "unders"))
    out["by_band"] = group_table(legs, lambda l: f"{int(l['hits']/l['total']*10)*10}%+ record")
    misses = [l for l in legs if l["result"] == "lose"]
    for l in misses:
        gap = abs((l["value"] or 0) - l["line"])
        l["_how"] = ("near miss" if gap <= max(1.0, 0.15 * abs(l["line"])) else "clear miss")
    out["near_misses"] = sum(l["_how"] == "near miss" for l in misses)
    out["misses"] = sorted(misses, key=lambda l: -l["kickoff"])[:25]
    out["findings"] = _findings(out)
    return out


def _findings(s) -> list[str]:
    notes = []
    if not s["legs_settled"]:
        return ["Nothing has settled yet. The first findings appear after the first round of games."]
    if s["legs_settled"] < 30:
        notes.append(f"Only {s['legs_settled']} settled legs so far: treat every pattern below as a hint, not a finding.")
    gap = s["legs_won"] / s["legs_settled"] - s["said"]
    notes.append(f"Overall the legs landed {s['legs_won']}/{s['legs_settled']} "
                 f"({s['legs_won']/s['legs_settled']:.0%}) against the {s['said']:.0%} the records said: "
                 + ("the site is over-confident." if gap < -0.05 else
                    "the site is under-selling itself." if gap > 0.05 else "about right."))
    for table, label in (("by_market", "market"), ("by_category", "bet type"), ("by_side", "side")):
        for r in s[table]:
            if r["legs"] >= 5 and r["gap"] <= -0.12:
                notes.append(f"{r['group']} ({label}) is the leak: {r['won']}/{r['legs']} landed "
                             f"({r['hit']:.0%}) against {r['said']:.0%} expected"
                             + (" - unlikely to be bad luck." if r["surprise"] < 0.1 else "."))
            elif r["legs"] >= 5 and r["gap"] >= 0.08:
                notes.append(f"{r['group']} ({label}) is outperforming: {r['hit']:.0%} against {r['said']:.0%}.")
    lost = s["legs_settled"] - s["legs_won"]
    if lost:
        notes.append(f"{s['near_misses']} of {lost} misses were near misses (within ~15% of the line); "
                     f"the rest missed clearly, which points at the line or the sample rather than luck.")
    return notes


def report(args=None) -> None:
    s = best_bets_summary()
    print("\n".join(s["findings"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["snapshot", "settle", "report", "leads"])
    a = ap.parse_args()
    {"snapshot": snapshot, "settle": settle, "report": report, "leads": leads}[a.cmd](a)


if __name__ == "__main__":
    main()
