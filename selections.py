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
  4. one bet per player, two per game, eight a day per sport, most model edge first.

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
# Back-test on Paddy's real first prices, 13 to 25 Oct 2026 (research/selections_bt.py)
BACKTEST = "39 bets over 7 days, 62% won, +22% return (range +6% to +49%)"


def _day(ts: float) -> str:
    # a US slate runs past midnight UK time: count the night from 06:00 UTC
    return datetime.datetime.utcfromtimestamp(ts - 6 * 3600).strftime("%Y-%m-%d")


def candidates(rows: list[dict], snap: str = "last") -> list[dict]:
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
        out.append(dict(r, _price=price, _model=m, _edge=m * price - 1))
    return out


def pick(rows: list[dict], snap: str = "last") -> list[dict]:
    best = {}
    for c in candidates(rows, snap):
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
        picks = tonight(now, until)
        rec = record()
    except Exception as exc:  # never cost the page
        return f"<p class='sub'>Best selections unavailable ({esc(str(exc))})</p>"
    live = (f"Live since 26 Oct: {rec['won']}/{rec['n']} won, {rec['profit']:+.2f} units, {rec['roi']:+.0%}."
            if rec["n"] else "Live record starts tonight.")
    head = (f"<div class='vbox'><p class='call'><b>The short list.</b> NBA and NFL player lines at Paddy Power where "
            f"the model beats the price by 3%+, the price is 1.60 to 2.30, and he has cleared the line in 7+ of his "
            f"last 10 and 3+ of his last 5. One per player, two per game, eight a day per sport.</p>"
            f"<p class='sub'>On Paddy's real prices, 13 to 25 Oct: {BACKTEST}. {live} "
            "Singles at level stakes; small samples, so judge it on weeks, not nights.</p>")
    if not picks:
        return head + "<p class='sub'>Nothing qualifies yet. Lines arrive through the day; check after the next update.</p></div>"
    rows = []
    for r in picks:
        ko = time.strftime("%a %H:%M", time.localtime(r["kickoff"]))
        rows.append(f"<tr><td>{esc(_bet(r))}<div class='sub'>{ko} &middot; {esc(r['fixture'])} &middot; "
                    f"{SPORTS[r['sport']]}</div></td>"
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
    picks = tonight()
    if not picks:
        print("Nothing qualifies in the next 30 hours.")
    for r in picks:
        ko = time.strftime("%a %H:%M", time.localtime(r["kickoff"]))
        print(f"{ko}  {_bet(r):55s} {r['_price']:.2f}  L10 {r['k10']}/{r['n10']}  L5 {r['k5']}/{r['n5']}  "
              f"model {r['_model']:.0%} (edge {r['_edge']:+.0%})  {r['fixture']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
