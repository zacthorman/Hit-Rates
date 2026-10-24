#!/usr/bin/env python3
"""
Soft v sharp: every Paddy Power line checked against Betfair Exchange.

    python sharp.py stamp     # publish.sh, after pplog/teamlog snapshot
    python sharp.py report    # print what is live and the record so far

The value-bot idea (23 Oct 2026). The model has not beaten the market on its
own (research/vs_market.py), but it does not have to: Betfair's price, with
its tiny margin and real money on both sides, is about the best forecast
there is. Where Paddy Power pays more than Betfair's fair price, the bet is
value whatever our model says. Our model, the line-up and the price move are
then extra signals stacked on top, and the paper trade page scores each
combination separately so stakes can follow what has actually paid.

What counts as Betfair's chance (only prices someone could take):
  * two-way markets (corners 8.5 / 10.5, cards 2.5 / 3.5): the margin-free
    chance market_prices.py already works out from both sides;
  * the corners bands ("9 or less", "13 or more"): the 9.5 and 12.5 lines;
  * one-runner-per-player markets (to score, shots on target 1+ and 2+,
    shown a card, anytime touchdown): 1 / mid of back and lay, only when the
    lay is within 25% of the back. A back with no lay is not a price.
"Beats the lay" is the strong case: Paddy Power longer than Betfair's lay
price, so the bet could be laid off on the exchange for a profit.

Written into the pplog / team log rows themselves (sharp_first, sharp_last),
so settling them needs nothing new.
"""
from __future__ import annotations

import json
import math
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_SPREAD = 1.25      # lay / back on a one-runner market
MIN_EDGE = 0.02        # shown on the page from here
MAX_PRICE = 10.0

PLAYER_MARKETS = {  # Betfair type -> (pplog stat, line)
    "TO_SCORE": ("Goals", 0.5),
    "SHOTS_ON_TARGET_P1": ("Shots on target", 0.5),
    "SHOTS_ON_TARGET_P2": ("Shots on target", 1.5),
    "SHOWN_A_CARD": ("Card", 0.5),
    "TO_SCORE_A_TOUCHDOWN": ("Anytime touchdown", 0.5),
}
MATCH_OU = {  # Betfair type -> (team log stat, line)
    "OVER_UNDER_85_CORNR": ("Corner kicks", 8.5),
    "OVER_UNDER_105_CORNR": ("Corner kicks", 10.5),
    "OVER_UNDER_25_CARDS": ("Yellow cards", 2.5),
    "OVER_UNDER_35_CARDS": ("Yellow cards", 3.5),
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if c.isascii() and (c.isalpha() or c == " ")).lower().split())


def _short(n: str) -> str:
    """'erling braut haaland' -> 'e haaland': a second key for name variants."""
    p = norm(n).split()
    return f"{p[0][0]} {p[-1]}" if len(p) >= 2 else " ".join(p)


# ------------------------------------------------------------------ Betfair's chances

def index(data: dict | None = None) -> dict:
    """fixture id -> {(who, stat, line, over): {"p", "back", "lay", "how"}}.
    who is a normalised player name (also under its short form) or 'match'."""
    if data is None:
        import market_prices
        data = market_prices.load(max_hours=6)
    out = {}
    for fid, ev in ((data or {}).get("events") or {}).items():
        got = {}
        for m in ev.get("markets") or []:
            t = m.get("type")
            if t in PLAYER_MARKETS:
                stat, line = PLAYER_MARKETS[t]
                for r in m.get("runners") or []:
                    b, l = r.get("back"), r.get("lay")
                    if not b or not l or b < 1.02 or l / b > MAX_SPREAD:
                        continue
                    v = {"p": round(2 / (b + l), 4), "back": b, "lay": l, "how": "exchange"}
                    for who in {norm(r["name"]), _short(r["name"])}:
                        got[(who, stat, line, True)] = v
            elif t in MATCH_OU:
                stat, line = MATCH_OU[t]
                for r in m.get("runners") or []:
                    if r.get("p") is None or not r.get("back") or not r.get("lay"):
                        continue
                    over = r["name"].lower().startswith("over")
                    got[("match", stat, line, over)] = {"p": r["p"], "back": r["back"], "lay": r["lay"],
                                                        "how": "exchange"}
            elif t == "CORNER_ODDS":
                for r in m.get("runners") or []:
                    if r.get("p") is None:
                        continue
                    nm = r["name"].lower()
                    if nm.startswith("9 or less"):
                        got.setdefault(("match", "Corner kicks", 9.5, False), {"p": r["p"], "back": r.get("back"),
                                                                               "lay": r.get("lay"), "how": "bands"})
                        got.setdefault(("match", "Corner kicks", 9.5, True), {"p": round(1 - r["p"], 4),
                                                                              "back": None, "lay": None, "how": "bands"})
                    elif nm.startswith("13 or more"):
                        got.setdefault(("match", "Corner kicks", 12.5, True), {"p": r["p"], "back": r.get("back"),
                                                                               "lay": r.get("lay"), "how": "bands"})
                        got.setdefault(("match", "Corner kicks", 12.5, False), {"p": round(1 - r["p"], 4),
                                                                                "back": None, "lay": None, "how": "bands"})
        # two-way unders from overs and back, where only one side priced
        for (who, stat, line, over), v in list(got.items()):
            if who == "match" and (who, stat, line, not over) not in got:
                got[(who, stat, line, not over)] = {"p": round(1 - v["p"], 4), "back": None, "lay": None,
                                                    "how": v["how"]}
        if got:
            out[str(fid)] = got
    return out


def lookup(ix: dict, row: dict):
    """Betfair's view of one pplog / team log row, or None."""
    ev = ix.get(str(row.get("event_id")))
    if not ev:
        return None
    if row.get("scope") is not None:  # team log
        if row["scope"] != "match":
            return None
        return ev.get(("match", row["stat"], float(row["line"]), bool(row["over"])))
    if not row.get("over"):
        return None
    for who in (norm(row.get("pp_player") or ""), norm(row.get("player") or ""),
                _short(row.get("player") or "")):
        v = who and ev.get((who, row["stat"], float(row["line"]), True))
        if v:
            return v
    return None


def snap(row: dict, v: dict, now: float) -> dict:
    price = (row.get("last") or {}).get("price")
    s = {"t": round(now), "p": v["p"], "back": v.get("back"), "lay": v.get("lay"), "how": v["how"],
         "price": price, "edge": round(v["p"] * price - 1, 4) if price else None}
    s["beats_lay"] = bool(price and v.get("lay") and price > v["lay"])
    return s


# ------------------------------------------------------------------ stamping the logs

def stamp(args=None) -> int:
    import pplog
    import teamlog
    ix = index()
    if not ix:
        print("sharp: no fresh Betfair prices")
        return 0
    now = time.time()
    n = 0
    for mod in (pplog, teamlog):
        for path in mod._files():
            rows = mod._read(path)
            changed = False
            for r in rows:
                if r.get("result") is not None or r.get("kickoff", 0) <= now:
                    continue
                v = lookup(ix, r)
                if not v:
                    continue
                s = snap(r, v, now)
                r.setdefault("sharp_first", s)
                r["sharp_last"] = s
                changed = True
                n += 1
            if changed:
                mod._write(path, rows)
    print(f"sharp: {n} Paddy Power line(s) checked against Betfair")
    return n


# ------------------------------------------------------------------ signals

def _poisson_over(lam: float, line: float) -> float:
    k = int(math.floor(line))
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))


def model_p(r: dict, snap_name: str = "last"):
    """Our own chance for the row: the player model's, or for a team log row
    the expected count as a Poisson (rough; corners and cards are wider)."""
    s = r.get(snap_name) or {}
    if s.get("chance") is not None:
        return s["chance"]
    if r.get("expected"):
        p = _poisson_over(r["expected"], r["line"])
        return p if r["over"] else 1 - p
    return None


def signals(r: dict, xi: dict | None = None) -> dict:
    """The stack for one row: which of the independent signals agree."""
    sh = r.get("sharp_last") or {}
    price = (r.get("last") or {}).get("price") or sh.get("price")
    mp = model_p(r)
    first = (r.get("sharp_first") or {}).get("p")
    out = {
        "sharp": bool(sh.get("edge") is not None and sh["edge"] >= MIN_EDGE),
        "lay": bool(sh.get("beats_lay")),
        "model": bool(mp is not None and price and mp * price > 1.0),
        "drift": bool(first is not None and sh.get("p") is not None and sh["p"] > first + 0.005),
    }
    if r.get("player") and r.get("sport") == "football":
        if xi is not None:  # live: the line-ups as they stand
            ev = xi.get(str(r.get("event_id"))) or {}
            out["xi"] = bool(ev.get("confirmed") and norm(r["player"]) in (ev.get("players") or {}))
        else:               # settled: what the log knew at its last snapshot
            out["xi"] = bool((r.get("last") or {}).get("confirmed_xi"))
    out["count"] = sum(1 for k in ("sharp", "lay", "model", "drift", "xi") if out.get(k))
    return out


def live(now: float, until: float) -> list[dict]:
    """Every unstarted Paddy Power line in the window that beats Betfair."""
    import pplog
    import teamlog
    xi = pplog._fmodel()
    out = []
    rows = pplog.all_rows() + [r for p in teamlog._files() for r in teamlog._read(p)]
    for r in rows:
        sh = r.get("sharp_last") or {}
        price = (r.get("last") or {}).get("price")
        if (r.get("result") is not None or not (now < r.get("kickoff", 0) < until) or sh.get("edge") is None
                or not price or price > MAX_PRICE):
            continue
        # the Betfair check must be of the same Paddy Power price still showing
        e = sh["p"] * price - 1
        if e < MIN_EDGE:
            continue
        sg = signals(r, xi)
        if r.get("player") and r.get("sport") == "football" and sg.get("xi") is False:
            ev = xi.get(str(r.get("event_id"))) or {}
            if ev.get("confirmed"):
                continue  # line-ups out and he is not starting
        out.append({"row": r, "edge": e, "p": sh["p"], "price": price, "sig": sg,
                    "kelly": e / (price - 1)})
    out.sort(key=lambda b: (-b["sig"]["count"], -b["edge"]))
    return out


def record() -> dict:
    """Settled record of rows that beat Betfair, by how many signals agreed."""
    import pplog
    import teamlog
    rows = pplog.all_rows() + [r for p in teamlog._files() for r in teamlog._read(p)]
    by = {}
    for r in rows:
        if r.get("result") not in ("win", "lose") or not r.get("sharp_last"):
            continue
        sg = signals(r)
        if not sg["sharp"]:
            continue
        price = r["last"]["price"]
        pr = price - 1 if r["result"] == "win" else -1.0
        for k in ("all", f"{min(sg['count'], 3)}+ signals", "beats lay" if sg["lay"] else None,
                  "model agrees" if sg["model"] else None):
            if not k:
                continue
            g = by.setdefault(k, {"n": 0, "w": 0, "profit": 0.0, "exp": 0.0})
            g["n"] += 1
            g["w"] += r["result"] == "win"
            g["profit"] += pr
            g["exp"] += r["sharp_last"]["p"]
    return by


# ------------------------------------------------------------------ the page

SIG_NAMES = (("lay", "beats Betfair's lay"), ("model", "our model agrees"), ("xi", "starting"),
             ("drift", "Betfair moving our way"))


def box(now: float, until: float, team: bool) -> str:
    """The tonight-page box: Paddy Power lines longer than Betfair's price."""
    import html
    esc = html.escape
    try:
        bets = [b for b in live(now, until) if bool(b["row"].get("scope")) == team]
        rec = record()
    except Exception as exc:  # never cost the page
        return f"<p class='sub'>Betfair check unavailable ({esc(str(exc))})</p>"
    g = rec.get("all")
    so_far = (f"{g['n']} settled, {g['w']} won (Betfair said {g['exp']:.0f}), {g['profit']:+.1f} pts at level stakes"
              if g else "nothing settled yet: the record starts now")
    what = "corners and cards lines" if team else "player lines (to score, shots on target, cards)"
    if not bets:
        return (f"<div class='vbox'><p class='none'>No Paddy Power {what} longer than Betfair's price right now.</p>"
                f"<p class='sub'>Record so far: {so_far}.</p></div>")
    rows = []
    for b in bets[:8]:
        r, sg = b["row"], b["sig"]
        ko = time.strftime("%H:%M", time.localtime(r["kickoff"]))
        if team:
            sel = f"{'Over' if r['over'] else 'Under'} {r['line']} {r['stat'].lower()}"
        else:
            sel = f"{r['player']} {r.get('label') or ''}" + ("" if r["stat"] in ("Goals", "Card", "Anytime touchdown")
                                                             else f" {r['stat'].lower()}")
        tags = "".join(f"<span class='tag ok'>{n}</span> " for k, n in SIG_NAMES if sg.get(k))
        rows.append(f"<tr data-k='{max(b['kelly'], 0):.5f}'><td>{esc(sel)}<div class='sub'>{ko} &middot; "
                    f"{esc(r['fixture'])} &middot; PP price at "
                    f"{time.strftime('%H:%M', time.localtime((r.get('last') or {}).get('t') or 0))}</div>{tags}</td><td class='n'>{b['price']:.2f}</td>"
                    f"<td class='n'>{1 / b['p']:.2f}</td><td class='n'>{b['edge'] * 100:+.0f}%</td>"
                    f"<td class='n stake'>&ndash;</td></tr>")
    bid = "sb-team" if team else "sb-player"
    return (
        "<div class='vbox sbox'>"
        f"<p class='budget'>Budget &pound;<input type='number' class='sbudget' id='{bid}' value='10' min='1' step='1' "
        "inputmode='decimal'> <span class='sub'>split by edge</span></p>"
        "<table><thead><tr><th>Bet</th><th class='n'>PP</th><th class='n'>Betfair</th><th class='n'>Edge</th>"
        "<th class='n'>Stake</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        "<p class='sub'>Paddy Power paying more than Betfair's fair price (the middle of its back and lay, "
        "margin off), as of the last publish: check both before betting. More green tags = more independent "
        "reasons agreeing; the best are those that beat Betfair's lay, which could be laid off for a profit. "
        f"Several bets in one game move together. Record so far: {so_far}.</p></div>")


SCRIPT = r"""<script>(function(){
function go(inp){var box=inp.closest('.sbox'),B=parseFloat(inp.value)||0,
 rows=[].slice.call(box.querySelectorAll('tbody tr')),K=rows.reduce(function(s,r){return s+parseFloat(r.dataset.k);},0);
 rows.forEach(function(r){var v=K>0?Math.max(0.5,Math.round(2*B*parseFloat(r.dataset.k)/K)/2):0;
  r.querySelector('.stake').innerHTML='&pound;'+v.toFixed(2);});}
document.querySelectorAll('.sbudget').forEach(function(i){i.addEventListener('input',function(){go(i);});go(i);});
})();</script>"""


def record_html() -> str:
    """For papertrade.html: the soft-v-sharp record by signal stack."""
    import html
    rec = record()
    order = ["all", "1+ signals", "2+ signals", "3+ signals", "model agrees", "beats lay"]
    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td class=n>{g['n']}</td><td class=n>{g['w']}</td>"
        f"<td class=n>{g['exp']:.1f}</td><td class=n>{g['profit'] / g['n'] * 100:+.1f}%</td></tr>"
        for k in order if (g := rec.get(k)))
    body = (f"<table><thead><tr><th>Bets that beat Betfair</th><th class=n>Bets</th><th class=n>Won</th>"
            f"<th class=n>Betfair said</th><th class=n>Return</th></tr></thead><tbody>{rows}</tbody></table>"
            if rows else "<p class='sub'>Nothing settled yet. Logging started 23 Oct 2026.</p>")
    return ("<h2>Soft v sharp: Paddy Power longer than Betfair</h2>" + body +
            "<p class='sub'>Every Paddy Power line Betfair also prices (to score, shots on target, cards, "
            "match corners and cards), bet at level stakes when Paddy Power paid at least 2% more than Betfair's "
            "fair price. Signals counted: beats Betfair's lay, our model agrees, confirmed starter, Betfair's "
            "price moving our way. If this pays and the 3+ row pays most, that is where to stake bigger.</p>")


def report(args=None) -> None:
    now = time.time()
    for b in live(now, now + 48 * 3600)[:30]:
        r = b["row"]
        who = r.get("player") or "Match"
        print(f"{b['edge'] * 100:+5.1f}%  {b['price']:5.2f} v BF {1 / b['p']:5.2f}  sig {b['sig']['count']}  "
              f"{who} {r.get('label') or ('over' if r['over'] else 'under')} {r['line']} {r['stat']}  ({r['fixture']})")
    for k, g in sorted(record().items()):
        print(f"{k}: {g['n']} bets, {g['w']} won (Betfair said {g['exp']:.1f}), {g['profit']:+.1f} pts")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"stamp": stamp, "report": report}[cmd]()


if __name__ == "__main__":
    main()
