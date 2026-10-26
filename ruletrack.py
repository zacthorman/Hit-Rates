#!/usr/bin/env python3
"""Fixed betting rules on trial: what each would have bet, and how it went.

    python ruletrack.py report    # RULES_TRACK.md: the record per rule, history and live
    python ruletrack.py tonight   # print tonight's qualifying bets

Why (23 Oct 2026): a good night is not an edge. Two nights of picks landed,
but blind-betting the same categories won the same nights, and the model's
own value flags had lost. So the ideas worth testing are written down here
once, frozen, and scored on every game that comes after. Nothing in a rule may
change once its trial starts; a changed rule is a new rule with a new start.

The rules, chosen on 13 NBA and 2 NFL games of Paddy Power lines (research/
uscheck.py, research/RULES_RESEARCH.md):

  nba_under_main        NBA player under on a main line (Paddy offers both
                        sides), first price 1.60 to 2.20. On the paired lines
                        the over landed 43.8% against a margin-free 49%, so
                        Paddy's main overs look priced short and the unders long.
  nba_under_model       the same, and the NBA player model agrees: its own
                        chance times the price is 1.05 or more.
  nfl_receiving_model   NFL receiving yards or receptions over at 2.20 or
                        shorter, the NFL player model agreeing by 5%+.
  beats_betfair         any Paddy Power player line paying 2%+ more than
                        Betfair's fair price for it (sharp.py), at 10.0 or
                        shorter. The value-bot idea; our model plays no part.
  control_nba_over_main the mirror of the first rule, expected to lose. If it
                        does not, the first rule is not what it looks like.

One bet per player, stat and game in each rule (the line priced nearest
evens), £1 at the first price logged. Also scored at the last price before
kick-off, and closing line value: how far the price moved after the bet was
flagged. Beating the closing price consistently is the best early sign of a
real edge, long before the results can say so.

"History" is the games the rule was chosen on, so it is in sample and proves
nothing. "Live" is everything after the freeze and is the test. Judge a rule
on live only, after about 40 games, by its range not its middle.

Reads pplog/ (and research/uscheck_*.csv for history the log cannot give).
"""
from __future__ import annotations

import csv
import datetime
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pplog  # noqa: E402

FROZEN = datetime.datetime(2026, 10, 23, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
OUT = ROOT / "RULES_TRACK.md"
NBA, NFL = "basketball", "american-football"
RECEIVING = {"Receiving yards", "Receiving receptions"}
SHOW = 8  # bets listed per rule on the page, most model edge first

# Rules added later start their own live record from when they were added.
RULE_START = {
    "learned_value": datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.timezone.utc).timestamp(),
}

RULES = {
    "nba_under_main": "NBA under, main line, 1.60 to 2.20",
    "nba_under_model": "NBA under, main line, 1.60 to 2.20, model agrees",
    "nfl_receiving_model": "NFL receiving over, 2.20 or shorter, model agrees",
    "beats_betfair": "Paddy pays 2%+ over Betfair's fair price, 10.0 or shorter",
    "learned_value": "Learned value: the corrected chance (learn.py) 3 to 15% over Paddy's price, 3.0 or shorter",
    "control_nba_over_main": "Control: NBA over, main line, 1.60 to 2.20 (should lose)",
}


def _hist_model() -> dict:
    """Model chances for games logged before pplog recorded them (uscheck CSVs)."""
    out = {}
    for sp in ("nba", "nfl"):
        f = ROOT / "research" / f"uscheck_{sp}.csv"
        if not f.exists():
            continue
        with f.open() as fh:
            for r in csv.DictReader(fh):
                out[(int(r["event_id"]), pplog._norm(r["player"]), r["stat"], float(r["line"]),
                     bool(int(r["over"])))] = float(r["p_model"])
    return out


_UM = None


def _model(r: dict, hist: dict):
    """The NBA / NFL model's own chance for this bet, before kick-off: as
    logged (pplog from 23 Oct), else the research rebuild for older games,
    else, for a game still to come, read now from reports/usmodel.json."""
    global _UM
    for snap in ("first", "last"):
        s = r.get(snap) or {}
        if s.get("source") == "usmodel" and s.get("model_chance") is not None:
            return s["model_chance"]
    h = hist.get((r["event_id"], pplog._norm(r["player"]), r["stat"], r["line"], bool(r["over"])))
    if h is not None or r.get("result") is not None or r["sport"] not in (NBA, NFL):
        return h
    if _UM is None:
        _UM = pplog._usmodel()
    s = r.get("last") or {}
    site_over = s.get("chance", 0.5) if r["over"] else 1 - s.get("chance", 0.5)
    us = pplog._usmodel_p(_UM, r["sport"], str(r["event_id"]), r["player"], r["stat"], r["line"], site_over)
    if us is None:
        return None
    return us[1] if r["over"] else 1 - us[1]


def qualifying(rows: list[dict]) -> dict[str, list[dict]]:
    """Rule -> rows it would have bet, one per player, stat and game."""
    hist = _hist_model()
    sides = defaultdict(set)
    for r in rows:
        sides[(r["event_id"], pplog._norm(r["player"]), r["stat"], r["line"])].add(bool(r["over"]))
    picks = defaultdict(dict)
    prices = defaultdict(dict)
    for r in rows:
        f = r.get("first") or {}
        if f.get("price"):
            prices[(r["event_id"], r["player"], r["stat"], r["line"])][bool(r["over"])] = f["price"]

    def add(rule, r):
        k = (r["event_id"], pplog._norm(r["player"]), r["stat"])
        cur = picks[rule].get(k)
        if cur is None or abs(r["first"]["price"] - 2.0) < abs(cur["first"]["price"] - 2.0):
            picks[rule][k] = r

    for r in rows:
        f = r.get("first") or {}
        price = f.get("price")
        if not price:
            continue
        main = len(sides[(r["event_id"], pplog._norm(r["player"]), r["stat"], r["line"])]) == 2
        m = _model(r, hist)
        agrees = m is not None and m * price >= 1.05
        r["_model_edge"] = (m * price - 1) if m is not None else None
        if r["sport"] == NBA and main and 1.6 <= price <= 2.2:
            if not r["over"]:
                add("nba_under_main", r)
                if agrees:
                    add("nba_under_model", r)
            else:
                add("control_nba_over_main", r)
        if r["sport"] == NFL and r["over"] and r["stat"] in RECEIVING and price <= 2.2 and agrees:
            add("nfl_receiving_model", r)
        # learned_value (26 Oct): the chance after learn.py's correction, only
        # where a correction has been adopted for that sport, side or stat.
        try:
            import learn
            pm = learn.model_side(r, hist)
            if pm is not None:
                pr = prices.get((r["event_id"], r["player"], r["stat"], r["line"])) or {}
                fair = None
                if len(pr) == 2:
                    a_, b_ = 1 / pr[bool(r["over"])], 1 / pr[not bool(r["over"])]
                    fair = a_ / (a_ + b_)
                f0 = r.get("first") or {}
                if f0.get("learned_chance") is not None:
                    pl, src = f0["learned_chance"], f0.get("learned_src", "logged")
                elif r.get("result") is None:
                    pl, src = learn.adjust(r["sport"], r["stat"], bool(r["over"]), pm, price, fair)
                else:
                    # settled before chances were logged: today's fit, in sample (History only)
                    pl, src = learn.adjust(r["sport"], r["stat"], bool(r["over"]), pm, price, fair)
                if src != "model" and price <= 3.0 and 0.03 <= pl * price - 1 <= 0.15:
                    r["_learned_edge"] = pl * price - 1
                    add("learned_value", r)
        except Exception:  # noqa: BLE001
            pass
        sh = r.get("sharp_first") or {}
        if sh.get("edge") is not None and sh["edge"] >= 0.02 and price <= 10:
            add("beats_betfair", r)
    return {k: list(v.values()) for k, v in picks.items()}


def _score(bets: list[dict]) -> dict:
    done = [b for b in bets if b.get("result") in ("win", "lose")]
    if not done:
        return {"n": 0}
    pf = [(b["first"]["price"] - 1) if b["result"] == "win" else -1.0 for b in done]
    pl = [(b["last"]["price"] - 1) if b["result"] == "win" else -1.0 for b in done]
    clv = [b["first"]["price"] / b["last"]["price"] - 1 for b in done if b["last"].get("price")]
    games = defaultdict(list)
    for b, p in zip(done, pf):
        games[b["event_id"]].append(p)
    g = list(games.values())
    rng = random.Random(7)
    boots = []
    for _ in range(2000):
        s = [rng.choice(g) for _ in g]
        n = sum(len(x) for x in s)
        boots.append(sum(sum(x) for x in s) / n)
    boots.sort()
    return {"n": len(done), "games": len(g), "won": sum(b["result"] == "win" for b in done),
            "profit": sum(pf), "roi": sum(pf) / len(done), "roi_close": sum(pl) / len(done),
            "clv": sum(clv) / len(clv) if clv else 0.0,
            "beat_close": sum(1 for c in clv if c > 0) / len(clv) if clv else 0.0,
            "lo": boots[100], "hi": boots[1899]}


def report(args=None) -> str:
    rows = pplog.all_rows()
    q = qualifying(rows)
    lines = ["# Rules on trial", "",
             f"Regenerated by `ruletrack.py report`, {time.strftime('%d %b %Y %H:%M')}. "
             "Rules frozen 23 Oct 2026, 13:00 BST. £1 a bet at the first price logged. "
             "**History is in sample (the rules were chosen on it). Judge on Live only**, "
             "after about 40 games, by the range, not the middle.", "",
             "| Rule | Period | Bets | Games | Won | Profit | ROI | 90% range | ROI at close | Beat close | CLV |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for rule, label in RULES.items():
        bets = q.get(rule, [])
        start = RULE_START.get(rule, FROZEN)
        for name, part in (("History", [b for b in bets if b["kickoff"] < start]),
                           ("Live", [b for b in bets if b["kickoff"] >= start])):
            s = _score(part)
            if not s["n"]:
                lines.append(f"| {label} | {name} | 0 | | | | | | | | |")
                continue
            lines.append(f"| {label} | {name} | {s['n']} | {s['games']} | {s['won']} | {s['profit']:+.2f} | "
                         f"{s['roi']:+.1%} | {s['lo']:+.0%} to {s['hi']:+.0%} | {s['roi_close']:+.1%} | "
                         f"{s['beat_close']:.0%} | {s['clv']:+.1%} |")
    lines += ["", "Beat close: share of bets where the price shortened after it was logged. "
              "CLV: average first price over last price, minus one. Both positive over many games is the "
              "early sign of an edge; results take far longer to say the same."]
    text = "\n".join(lines) + "\n"
    OUT.write_text(text)
    print(text)
    return text


def tonight(now: float | None = None, until: float | None = None) -> dict[str, list[dict]]:
    now = now or time.time()
    until = until or now + 24 * 3600
    rows = [r for r in pplog.all_rows() if r.get("result") is None and now < (r.get("kickoff") or 0) < until]
    return {k: sorted(v, key=lambda r: r["kickoff"]) for k, v in qualifying(rows).items() if not k.startswith("control")}


def shortlist(bets: list[dict]) -> list[dict]:
    """For betting rather than testing: one bet per player (his lines move
    together), most model edge first. The edge only orders the list; on the
    history bigger edges did no better (research/RULES_RESEARCH.md)."""
    seen, out = set(), []
    for b in sorted(bets, key=lambda b: -(b.get("_model_edge") or 0)):
        k = (b["event_id"], pplog._norm(b["player"]))
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out


def shortlist_by(bets: list[dict], key: str) -> list[dict]:
    seen, out = set(), []
    for b in sorted(bets, key=lambda b: -(b.get(key) or 0)):
        k = (b["event_id"], pplog._norm(b["player"]))
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out


def box(now: float, until: float) -> str:
    """The tonight-page box: tonight's bets per rule, with each rule's live record."""
    import html
    esc = html.escape
    try:
        q = tonight(now, until)
        allq = qualifying(pplog.all_rows())
    except Exception as exc:  # never cost the page
        return f"<p class='sub'>Rules on trial unavailable ({esc(str(exc))})</p>"
    out = ["<div class='vbox'><p class='call meh'><b>On trial, not proven.</b> Fixed rules scored on every "
           "game since 23 Oct. Small, equal stakes until the live record says otherwise "
           "(RULES_TRACK.md).</p>"]
    for rule, label in RULES.items():
        if rule.startswith("control"):
            continue
        live = _score([b for b in allq.get(rule, []) if b["kickoff"] >= RULE_START.get(rule, FROZEN)])
        rec = (f"live {live['n']} bets, {live['games']} games, {live['roi']:+.0%}, beat close {live['beat_close']:.0%}"
               if live["n"] else "no live results yet")
        bets = q.get(rule, [])
        out.append(f"<p><b>{esc(label)}</b> <span class='sub'>({rec})</span></p>")
        if not bets:
            out.append("<p class='sub'>Nothing qualifies tonight.</p>")
            continue
        if rule == "nba_under_main":
            out.append(f"<p class='sub'>{len(bets)} qualify tonight. Logged for the test; the model-agrees "
                       "list below is the short list to bet from.</p>")
            continue
        bets = shortlist(bets) if rule != "learned_value" else shortlist_by(bets, "_learned_edge")
        out.append("<table><thead><tr><th>Bet</th><th class='n'>Price</th><th class='n'>Model</th></tr></thead><tbody>")
        for b in bets[:SHOW]:
            ko = time.strftime("%H:%M", time.localtime(b["kickoff"]))
            me = b.get("_learned_edge") if rule == "learned_value" else b.get("_model_edge")
            out.append(f"<tr><td>{esc(b['player'])} {esc(b['label'])} {esc(b['stat'].lower())}"
                       f"<div class='sub'>{ko} &middot; {esc(b['fixture'])}</div></td>"
                       f"<td class='n'>{b['last']['price']:.2f}</td>"
                       f"<td class='n'>{'' if me is None else f'{me:+.0%}'}</td></tr>")
        if len(bets) > SHOW:
            out.append(f"<tr><td class='sub'>and {len(bets) - SHOW} more</td><td></td><td></td></tr>")
        out.append("</tbody></table>")
    out.append("</div>")
    return "".join(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "report":
        report()
    elif cmd == "tonight":
        for rule, bets in tonight().items():
            print(f"\n{RULES[rule]}: {len(bets)}")
            sl = shortlist_by(bets, "_learned_edge") if rule == "learned_value" else shortlist(bets)
            for b in sl[:25]:
                print(f"  {(b.get('_learned_edge') if rule == 'learned_value' else b.get('_model_edge')) or 0:+5.0%}", end="")
                print(f"  {time.strftime('%a %H:%M', time.localtime(b['kickoff']))}  {b['fixture'][:38]:38} "
                      f"{b['player']:24} {b['label']:12} {b['stat']:26} {b['last']['price']:.2f}")
