#!/usr/bin/env python3
"""
Confluence: a line is only put forward when several separate pieces of
evidence say the price is too long (3 Nov 2026).

    python confluence.py report     # the backtest tiers and the live record
    python confluence.py live       # what qualifies in the next 30 hours

The idea is Zac's: one number on its own decides nothing, so stack every
independent source and only bet where they agree. Each source votes yes when
its own chance for the line is above the chance the price implies:

  player lines (pplog)                team lines (teamlog)
    model    player model's chance      proj    team-stats projection, Poisson
    site     hit-rate model's chance    model   team model's chance
    learned  learned correction         form10  last 10 cleared the line
    form10   last 10, shrunk            form5   last 5
    form5    last 5, shrunk             sharp   Betfair / Pinnacle fair chance
    adj      opponent adjustment        lay     longer than Betfair's lay
    xi       in the confirmed XI        drift   sharp price moving our way
    sharp, lay, drift as for team lines

What the settled record (20 Oct to 3 Nov, every line priced 6.0 or shorter,
level stakes) said, and so the rules, frozen on 3 Nov:

  * More agreement is better in every sport, in both halves of the record.
    Football player lines go from -44% (all) to -24% (4+ agree): Paddy
    Power's margin on those props is too wide for agreement to beat, so they
    are never put forward on agreement alone.
  * The sharp price is a veto. Where Betfair or Pinnacle disagree, stacking
    our own sources lost 13%: the market knew something they did not.
  * STRONG: the sharp price agrees and 2+ other sources do too.
    116 bets over 82 games, one per player or side per game, +20% at the last
    price (90% range, resampled by game, -2% to +42%), positive in both
    halves (+39% then +15%). Almost all team lines (corners, cards, goals).
  * ON TRIAL, where no sharp price exists: NBA player lines with 5+ sources
    agreeing, team lines with 4+. 282 bets over 86 games, +9% (90% range -3%
    to +21%), positive in both halves (+2% then +12%).
  * Weighting the sources (a logistic fit on the first week, tested on the
    second) did no better than counting, and for the NFL much worse, so the
    rule counts. Two weeks is too little to fit weights on.

The thresholds were chosen after looking, so the backtest flatters them. The
live record, from FREEZE on, is the one that counts: it is kept apart and
shown first.
"""
from __future__ import annotations

import html
import math
import sys
import time

FREEZE = 1793750400          # 4 Nov 2026 00:00 UK: the live record starts here
MAX_PRICE = 6.0
BACKTEST = {"strong": (116, 0.200), "trial": (282, 0.089)}

LABEL = {"sharp": "Sharp price", "lay": "Beats the lay", "drift": "Price moving our way",
         "model": "Model", "site": "Hit-rate model", "learned": "Learned", "form10": "Last 10",
         "form5": "Last 5", "adj": "Matchup", "xi": "In the XI", "proj": "Team stats"}
ORDER = ["sharp", "lay", "drift", "proj", "model", "site", "learned", "adj", "form10", "form5", "xi"]


def _shrink(k, n, prior, w=6):
    return (k + prior * w) / (n + w) if n else None


def _pois_over(lam, line):
    k = int(math.floor(line))
    s, t = 0.0, math.exp(-lam)
    for i in range(k + 1):
        s += t
        t *= lam / (i + 1)
    return 1 - s


def _sharp_votes(r, snap, imp, V):
    sh = r.get("sharp_first") if snap == "first" else r.get("sharp_last")
    if sh and sh.get("p") is not None:
        V["sharp"] = sh["p"] > imp
        if sh.get("beats_lay") is not None:
            V["lay"] = bool(sh["beats_lay"])
    sf, sl = r.get("sharp_first"), r.get("sharp_last")
    if sf and sl and sf.get("p") and sl.get("p"):
        V["drift"] = sl["p"] - sf["p"] > 0.005


def votes(r: dict, snap: str = "last") -> dict | None:
    """Which sources say this line's price is too long, at snapshot snap."""
    s = r.get(snap) or {}
    price = s.get("price")
    if not price or price <= 1.01 or price > MAX_PRICE:
        return None
    imp, over, V = 1 / price, bool(r.get("over", True)), {}
    team = r.get("scope") is not None
    if team:
        e = r.get("expected")
        if e and r.get("basis") == "projection":
            p = _pois_over(e, r["line"])
            V["proj"] = (p if over else 1 - p) > imp
        if r.get("model_p") is not None:
            V["model"] = r["model_p"] > imp
        rec = r.get("recent")
        if rec:
            h = [(v > r["line"]) if over else (v < r["line"]) for v in rec]
            V["form10"] = _shrink(sum(h), len(h), imp) > imp
            V["form5"] = _shrink(sum(h[-5:]), len(h[-5:]), imp, 4) > imp
    else:
        for k, key in (("model", "chance"), ("site", "site_chance"), ("learned", "learned_chance")):
            if s.get(key) is not None:
                V[k] = s[key] > imp
        if r.get("k10") is not None and r.get("n10"):
            V["form10"] = _shrink(r["k10"], r["n10"], imp) > imp
        if r.get("k5") is not None and r.get("n5"):
            V["form5"] = _shrink(r["k5"], r["n5"], imp, 4) > imp
        if r.get("adj") is not None:
            V["adj"] = (r["adj"] > 1.0) if over else (r["adj"] < 1.0)
        if s.get("confirmed_xi") is not None:
            V["xi"] = bool(s["confirmed_xi"])
    _sharp_votes(r, snap, imp, V)
    kind = "team" if team else f"player-{r.get('sport')}"
    return {"price": price, "kind": kind, "V": V, "yes": [k for k in ORDER if V.get(k)]}


def tier(v: dict | None) -> str | None:
    """'strong', 'trial' or None, by the rules frozen on 3 Nov 2026."""
    if not v:
        return None
    V = v["V"]
    if V.get("sharp") is False:
        return None                                   # the veto
    agree = sum(1 for x in V.values() if x)
    if V.get("sharp"):
        return "strong" if agree - 1 >= 2 else None
    if v["kind"] == "player-basketball" and agree >= 5:
        return "trial"
    if v["kind"] == "team" and agree >= 4:
        return "trial"
    return None


def _rows() -> list[dict]:
    import pplog
    import teamlog
    return pplog.all_rows() + [r for p in teamlog._files() for r in teamlog._read(p)]


def _who(r: dict) -> str:
    return r.get("player") or r.get("team") or ""


def describe(r: dict) -> str:
    stat = (r.get("stat") or "").lower()
    if r.get("player") and r.get("label"):
        return f"{r['player']} {r['label']} {stat}".replace("  ", " ")
    side = r.get("team") if r.get("scope") not in (None, "match") else "Match"
    return f"{side} {'over' if r.get('over', True) else 'under'} {r['line']:g} {stat}"


def _best(rows) -> list[dict]:
    """One qualifying line per player or side per game: strongest tier, then most agreement."""
    best = {}
    for r in rows:
        v = votes(r)
        t = tier(v)
        if not t:
            continue
        key = (r.get("event_id"), _who(r), r.get("scope"))
        rank = (t == "strong", len(v["yes"]))
        if key not in best or rank > best[key][0]:
            best[key] = (rank, dict(row=r, votes=v, tier=t))
    return [x for _, x in best.values()]


def live(now: float | None = None, until: float | None = None) -> list[dict]:
    """Unstarted lines that qualify now, strongest first."""
    now = now or time.time()
    until = until or now + 30 * 3600
    out = _best(r for r in _rows()
                if r.get("result") is None and now < (r.get("kickoff") or 0) < until)
    out.sort(key=lambda x: (x["tier"] != "strong", -len(x["votes"]["yes"]), x["row"]["kickoff"]))
    return out


def record(since: float = FREEZE, until: float | None = None, rows=None) -> dict:
    """Settled lines that qualified at their last pre-kick-off price, picked as live() picks them."""
    out = {t: {"n": 0, "won": 0, "profit": 0.0} for t in ("strong", "trial")}
    rows = _rows() if rows is None else rows
    sel = _best(r for r in rows if r.get("result") in ("win", "lose")
                and (r.get("kickoff") or 0) >= since and (until is None or r["kickoff"] < until))
    for x in sel:
        g, r = out[x["tier"]], x["row"]
        g["n"] += 1
        g["won"] += r["result"] == "win"
        g["profit"] += (x["votes"]["price"] - 1) if r["result"] == "win" else -1
    return out


def _rec_line(g: dict) -> str:
    if not g["n"]:
        return "none settled yet"
    roi = g["profit"] / g["n"]
    cls = "pos" if roi > 0 else "neg" if roi < 0 else ""
    return f"{g['won']}/{g['n']} won, <b class='{cls}'>{roi * 100:+.0f}%</b>"


CSS = """
.cf-row { display:flex; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid var(--line); }
.cf-row:last-child { border-bottom:0; }
.cf-sel { font-weight:600; }
.cf-sub { font-size:12.5px; color:var(--muted); margin-top:2px; }
.cf-chips { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
.cf-chip { font-size:11px; font-weight:600; padding:1px 7px; border-radius:99px; background:rgba(21,128,61,.12); color:#15803d; }
.cf-chip.sh { background:rgba(31,63,143,.12); color:#1f3f8f; }
@media (prefers-color-scheme:dark) { .cf-chip { color:#4ade80; background:rgba(74,222,128,.14); } .cf-chip.sh { color:#9db8ff; background:rgba(110,140,255,.16); } }
.cf-tier { display:inline-block; font-size:10.5px; font-weight:700; letter-spacing:.05em; text-transform:uppercase;
           padding:1px 7px; border-radius:5px; margin-right:6px; vertical-align:1px; }
.cf-tier.strong { background:#f5a524; color:#241600; } .cf-tier.trial { background:rgba(127,127,127,.18); }
.cf-price { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
.cf-price b { font-size:17px; }
"""


def box(now: float, until: float, limit: int = 12) -> str:
    """The Tonight page section."""
    esc = html.escape
    try:
        picks = live(now, until)
        rec = record()
    except Exception as exc:            # never cost the page
        print(f"confluence.box: {exc!r}")
        return "<p class='sub'>The confluence check could not run this time. It returns at the next update.</p>"
    head = ("<p class='sub'>Only lines where several separate pieces of evidence agree the price is too long. "
            "<b>Strong</b>: Betfair or Pinnacle agree, plus 2 or more of our own. <b>On trial</b>: no sharp price, "
            "so 5+ of ours for NBA players, 4+ for team lines. If the sharp price disagrees, the line is never shown. "
            "Football player lines are left out: their margin is too wide.</p>"
            f"<p class='sub'>Live since 4 Nov: strong {_rec_line(rec['strong'])}; on trial {_rec_line(rec['trial'])}. "
            f"Backtest (20 Oct to 3 Nov, chosen after looking): strong {BACKTEST['strong'][0]} bets "
            f"{BACKTEST['strong'][1] * 100:+.0f}%, on trial {BACKTEST['trial'][0]} bets {BACKTEST['trial'][1] * 100:+.0f}%.</p>")
    if not picks:
        return head + "<p class='none'>Nothing has enough agreement right now.</p>"
    import value_books
    rows = []
    for x in picks[:limit]:
        r, v = x["row"], x["votes"]
        ko = time.strftime("%a %H:%M", time.localtime(r["kickoff"]))
        book = value_books.BOOK_NAME.get(r.get("book") or "PP", "Paddy Power")
        chips = "".join(f"<span class='cf-chip{' sh' if k in ('sharp', 'lay', 'drift') else ''}'>{LABEL[k]}</span>"
                        for k in v["yes"])
        rows.append(
            f"<div class='cf-row'><div><div class='cf-sel'><span class='cf-tier {x['tier']}'>"
            f"{'Strong' if x['tier'] == 'strong' else 'On trial'}</span>{esc(describe(r))}</div>"
            f"<div class='cf-sub'>{ko} &middot; {esc(r.get('fixture') or '')} &middot; {len(v['yes'])} agree</div>"
            f"<div class='cf-chips'>{chips}</div></div>"
            f"<div class='cf-price'><b>{v['price']:.2f}</b><div class='cf-sub'>{esc(book)}</div></div></div>")
    more = f"<p class='sub'>{len(picks) - limit} more qualify; the strongest are shown.</p>" if len(picks) > limit else ""
    return head + "".join(rows) + more + "<p class='sub'>Check the price before betting: it must still be this or longer.</p>"


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "report"
    if cmd == "live":
        for x in live():
            r, v = x["row"], x["votes"]
            print(f"{x['tier']:6} {v['price']:5.2f} {describe(r)} ({r.get('fixture')}) [{', '.join(v['yes'])}]")
        return 0
    rec = record()
    for t in ("strong", "trial"):
        g = rec[t]
        print(f"{t}: live {g['n']} settled, {g['won']} won, {g['profit']:+.1f} units; backtest "
              f"{BACKTEST[t][0]} bets {BACKTEST[t][1]:+.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
