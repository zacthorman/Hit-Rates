#!/usr/bin/env python3
"""Best selections: the short list to actually bet, NBA and NFL player lines at Paddy Power.

    python selections.py            # tonight's list in the terminal
    python selections.py log        # record tonight's list (publish.sh), settle earlier ones
    python selections.py report     # the record

The filter, written down from the hand-picked slips that kept landing (26 Oct
2026), and back-tested on Paddy Power's real prices since 13 Oct
(research/SELECTIONS_RESEARCH.md):

  1. a Paddy price between 1.60 and 2.30 (no odds-on bankers, no long shots);
  2. the NBA / NFL model's chance beats that price by 3% or more;
  3. recent form at that exact line: 7+ of the last 10 and 3+ of the last 5;
  4. not against missing team-mates: no under on a player whose side is
     missing regulars, no over when fewer are missing than usual (added 26 Oct
     after research/signals.py; unders with team-mates missing lost 12%);
  5. one bet per player, two per game, eight a day per sport, most model edge first.

Football is left out: no version of it made money on real prices.
Every list is logged before kick-off and settled from pplog, never edited.
"""
from __future__ import annotations

import collections
import datetime
import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pplog  # noqa: E402
import ruletrack  # noqa: E402

LOG = ROOT / "selections" / "log.jsonl"
START = datetime.datetime(2026, 10, 26, 15, 0, tzinfo=datetime.timezone.utc).timestamp()
SPORTS = {"basketball": "NBA", "american-football": "NFL"}
MIN_PRICE, MAX_PRICE = 1.60, 2.30
MIN_EDGE = 0.03
L10, L5, MIN_N10 = 0.70, 0.60, 6
PER_GAME, PER_DAY = 2, 8
# Back-test on Paddy's real first prices to 25 Oct 2026, team-mates rule included (research/SIGNALS.md)
BACKTEST = "45 bets over 6 days, 58% won, +11% return (range -2% to +36%)"


def _day(ts: float) -> str:
    # a US slate runs past midnight UK time: count the night from 06:00 UTC
    return datetime.datetime.utcfromtimestamp(ts - 6 * 3600).strftime("%Y-%m-%d")


THRESH = ROOT / "selections_thresholds.json"
_UM = None


def _ctx_live(r: dict):
    """miss_key / start_rate for a coming game, from reports/usmodel.json."""
    global _UM
    if _UM is None:
        try:
            _UM = json.loads((ROOT / "reports" / "usmodel.json").read_text())
        except (OSError, ValueError):
            _UM = {}
    ev = (_UM.get("events") or {}).get(str(r["event_id"]))
    if ev:
        n = pplog._norm(r["player"])
        for name, pl in ev.get("players", {}).items():
            if pplog._norm(name) == n:
                return pl.get("ctx")
    return None


def teammates_against(r: dict, ctx) -> bool:
    """True when recently missing team-mates point the other way: an under on a
    player whose side is missing regulars (more of the ball for him), or an over
    when fewer are missing than usual. Back-tested 26 Oct 2026: unders with
    team-mates missing lost 12% on Paddy's real prices (research/SIGNALS.md)."""
    if not ctx or ctx.get("miss_key") is None:
        return False
    try:
        th = json.loads(THRESH.read_text())
    except (OSError, ValueError):
        return False
    m = (th.get(f"{'nba' if r['sport'] == 'basketball' else 'nfl'}|{r['stat']}|{int(bool(r['over']))}") or {}).get("miss_key")
    if m is None or ctx["miss_key"] == m:
        return False
    return ctx["miss_key"] < m if r["over"] else ctx["miss_key"] > m


def candidates(rows: list[dict], snap: str = "last", ctx_fn=None) -> list[dict]:
    ctx_fn = ctx_fn or _ctx_live
    hist = ruletrack._hist_model()
    out = []
    for r in rows:
        if r.get("sport") not in SPORTS:
            continue
        s = r.get(snap) or r.get("first") or {}
        price = s.get("price")
        if not price or not (MIN_PRICE <= price <= MAX_PRICE):
            continue
        n10, n5 = r.get("n10") or 0, r.get("n5") or 0
        if n10 < MIN_N10 or not n5 or r["k10"] / n10 < L10 or r["k5"] / n5 < L5:
            continue
        m = ruletrack._model(r, hist)
        if m is None or m * price - 1 < MIN_EDGE:
            continue
        if teammates_against(r, ctx_fn(r)):
            continue
        out.append(dict(r, _price=price, _model=m, _edge=m * price - 1))
    return out


def pick(rows: list[dict], snap: str = "last", ctx_fn=None) -> list[dict]:
    best = {}
    for c in candidates(rows, snap, ctx_fn):
        k = (c["event_id"], pplog._norm(c["player"]))
        if k not in best or c["_edge"] > best[k]["_edge"]:
            best[k] = c
    byday = collections.defaultdict(list)
    for c in best.values():
        byday[(c["sport"], _day(c["kickoff"]))].append(c)
    out = []
    for d, cs in byday.items():
        cs.sort(key=lambda c: -c["_edge"])
        games, n = collections.Counter(), 0
        for c in cs:
            if n >= PER_DAY or games[c["event_id"]] >= PER_GAME:
                continue
            out.append(c)
            games[c["event_id"]] += 1
            n += 1
    return sorted(out, key=lambda c: (c["kickoff"], -c["_edge"]))


def tonight(now: float | None = None, until: float | None = None) -> list[dict]:
    now = now or time.time()
    until = until or now + 30 * 3600
    rows = [r for r in pplog.all_rows() if r.get("result") is None and now < (r.get("kickoff") or 0) < until]
    return pick(rows)


# ------------------------------------------------------------------ team news
# The model already counts ruled-out team-mates (usfeatures' missing-usage
# features, fed by ESPN's report when usmodel_live runs). The last-10 / last-5
# form does not, and news can land after the last run, so every pick shows
# who on his side has been ruled out in the last two days and what that does.
USAGE_STATS = ("Points", "Assists", "Points and assists", "Points and rebounds", "Points rebounds and assists",
               "Rebounds and assists", "Three pointers made", "Receiving yards", "Receiving receptions",
               "Rushing yards", "Passing yards", "Rushing and receiving yards")
KEY_POINTS = {"basketball": 10.0, "american-football": 30.0}  # his usual Paddy line to count as a key man


def _news(sport: str, max_age: float) -> list[dict]:
    try:
        import usmodel_live as UL
        d = UL.espn_injuries("nba" if sport == "basketball" else "nfl", max_age=max_age)
    except Exception:  # noqa: BLE001
        return []
    out = []
    now = time.time()
    for team in d.get("injuries", []):
        for inj in team.get("injuries", []):
            status = str(inj.get("status") or "")
            if status.lower() not in ("out", "doubtful", "questionable", "day-to-day", "injured reserve"):
                continue
            try:
                t = datetime.datetime.strptime(inj.get("date", "")[:16], "%Y-%m-%dT%H:%M").replace(
                    tzinfo=datetime.timezone.utc).timestamp()
            except ValueError:
                continue
            out.append(dict(team=team.get("displayName", ""), name=(inj.get("athlete") or {}).get("displayName", ""),
                            status=status, t=t, new=now - t < 48 * 3600))
    return out


def _key_line(rows: list[dict], sport: str) -> dict:
    """Each player's most recent Paddy line on his main volume stat: who matters."""
    stat = "Points" if sport == "basketball" else None
    best = {}
    for r in rows:
        if r.get("sport") != sport:
            continue
        if stat and r["stat"] != stat:
            continue
        if not stat and r["stat"] not in ("Receiving yards", "Rushing yards", "Passing yards"):
            continue
        k = pplog._norm(r["player"])
        if k not in best or r["kickoff"] > best[k][0]:
            best[k] = (r["kickoff"], r["line"])
    return {k: v[1] for k, v in best.items()}


def annotate(picks: list[dict], max_age: float = 3 * 3600) -> list[dict]:
    if not picks:
        return picks
    rows = pplog.all_rows()
    for sport in {p["sport"] for p in picks}:
        news = _news(sport, max_age)
        keyl = _key_line(rows, sport)
        for p in (x for x in picks if x["sport"] == sport):
            mates = [n for n in news if n["team"] == p.get("team") and pplog._norm(n["name"]) != pplog._norm(p["player"])
                     and n["status"].lower() in ("out", "doubtful", "injured reserve") and n["new"]
                     and keyl.get(pplog._norm(n["name"]), 0) >= KEY_POINTS[sport]]
            own = next((n for n in news if pplog._norm(n["name"]) == pplog._norm(p["player"])), None)
            notes, warn = [], False
            st = own["status"] if own else (p.get("injury") or "")
            if st and st.lower() not in ("active", "out"):
                notes.append(f"he is {st.lower()}: check he plays (a scratch is a void)")
            if mates and p["stat"] in USAGE_STATS:
                who = ", ".join(f"{m['name']} ({m['status'].lower()})" for m in mates)
                if p["over"]:
                    notes.append(f"{who}: more of the ball for him, helps the over")
                else:
                    notes.append(f"{who}: more of the ball for him, works against the under")
                    warn = True
            elif mates:
                notes.append(", ".join(f"{m['name']} ({m['status'].lower()})" for m in mates) + " out on his side")
            p["_news"], p["_warn"] = notes, warn
    return picks


def _key(r: dict) -> str:
    return f"{r['event_id']}|{pplog._norm(r['player'])}|{r['stat']}|{r['line']}|{int(bool(r['over']))}"


def _load() -> list[dict]:
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def log(args=None) -> int:
    """Append tonight's list (pre-kick-off only, never twice), settle from pplog."""
    LOG.parent.mkdir(exist_ok=True)
    have = {e["key"]: e for e in _load()}
    now = time.time()
    # a player already listed for a game keeps his first listing
    listed = {(e["event_id"], pplog._norm(e["player"])) for e in have.values()}
    new = []
    for c in tonight(now):
        if (c["event_id"], pplog._norm(c["player"])) in listed:
            continue
        new.append(dict(key=_key(c), t=int(now), event_id=c["event_id"], fixture=c["fixture"], sport=c["sport"],
                        kickoff=c["kickoff"], player=c["player"], stat=c["stat"], line=c["line"], over=bool(c["over"]),
                        label=c["label"], price=c["_price"], model=round(c["_model"], 4), k10=c["k10"], n10=c["n10"],
                        k5=c["k5"], n5=c["n5"], result=None, value=None))
    entries = list(have.values()) + new
    res = {_key(r): r for r in pplog.all_rows() if r.get("result")}
    settled = 0
    for e in entries:
        if e["result"] is None and e["key"] in res:
            e["result"], e["value"] = res[e["key"]]["result"], res[e["key"]].get("value")
            settled += 1
    LOG.write_text("".join(json.dumps(e) + "\n" for e in entries))
    print(f"selections: {len(new)} listed, {settled} settled, {len(entries)} on record")
    return 0


def record() -> dict:
    s = [e for e in _load() if e["result"] in ("win", "lose")]
    n = len(s)
    won = sum(e["result"] == "win" for e in s)
    profit = sum((e["price"] - 1) if e["result"] == "win" else -1 for e in s)
    return dict(n=n, won=won, profit=profit, roi=profit / n if n else 0.0,
                days=len({_day(e["kickoff"]) for e in s}))


def _bet(r: dict) -> str:
    stat = r["stat"].lower()
    lab = r["label"]
    return f"{r['player']} {lab.lower()} {stat}"


def box(now: float, until: float) -> str:
    esc = html.escape
    try:
        picks = annotate(tonight(now, until))
        rec = record()
    except Exception as exc:  # never cost the page
        return f"<p class='sub'>Best selections unavailable ({esc(str(exc))})</p>"
    live = (f"Live since 26 Oct: {rec['won']}/{rec['n']} won, {rec['profit']:+.2f} units, {rec['roi']:+.0%}."
            if rec["n"] else "Live record starts tonight.")
    head = (f"<div class='vbox'><p class='call'><b>The short list.</b> NBA and NFL player lines at Paddy Power where "
            f"the model beats the price by 3%+, the price is 1.60 to 2.30, and he has cleared the line in 7+ of his "
            f"last 10 and 3+ of his last 5. One per player, two per game, eight a day per sport.</p>"
            f"<p class='sub'>On Paddy's real prices since 13 Oct: {BACKTEST}. {live} "
            "Singles at level stakes; small samples, so judge it on weeks, not nights.</p>")
    if not picks:
        return head + "<p class='sub'>Nothing qualifies yet. Lines arrive through the day; check after the next update.</p></div>"
    rows = []
    for r in picks:
        ko = time.strftime("%a %H:%M", time.localtime(r["kickoff"]))
        rows.append(f"<tr><td>{esc(_bet(r))}<div class='sub'>{ko} &middot; {esc(r['fixture'])} &middot; "
                    f"{SPORTS[r['sport']]}</div>"
                    + "".join(f"<div class='sub' style='color:{'var(--bad,#c0392b)' if r.get('_warn') else 'inherit'}'>"
                              f"&#9888; {esc(n)}</div>" for n in r.get("_news", []))
                    + "</td>"
                    f"<td class='n'>{r['_price']:.2f}</td>"
                    f"<td class='n'>{r['k10']}/{r['n10']}, {r['k5']}/{r['n5']}</td>"
                    f"<td class='n'>{r['_model']:.0%}<div class='sub'>fair {1 / r['_model']:.2f}</div></td></tr>")
    return (head + "<table><thead><tr><th>Bet</th><th class='n'>Paddy</th><th class='n'>Last 10 / 5</th>"
            "<th class='n'>Model</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "log":
        return log()
    if cmd == "report":
        r = record()
        print(f"{r['n']} settled over {r['days']} day(s): {r['won']} won, {r['profit']:+.2f} units, {r['roi']:+.1%}")
        return 0
    picks = annotate(tonight(), max_age=20 * 60)
    if not picks:
        print("Nothing qualifies in the next 30 hours.")
    for r in picks:
        ko = time.strftime("%a %H:%M", time.localtime(r["kickoff"]))
        print(f"{ko}  {_bet(r):55s} {r['_price']:.2f}  L10 {r['k10']}/{r['n10']}  L5 {r['k5']}/{r['n5']}  "
              f"model {r['_model']:.0%} (edge {r['_edge']:+.0%})  {r['fixture']}")
        for n in r.get("_news", []):
            print(f"{'':11s}{'!! ' if r.get('_warn') else '   '}{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
