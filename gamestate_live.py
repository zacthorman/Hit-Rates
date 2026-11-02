#!/usr/bin/env python3
"""
The "Game state" tab on every report page: reports/gamestate.json.

    python gamestate_live.py            # every football, NBA and NFL fixture in the next 4 days

29 Oct 2026 redesign (Zac: "when there's a lot of text, people aren't going
to read that"). The same numbers as before, drawn instead of written:

  football  The result: likely score, a home / draw / away bar, xG and the
            goals tiles (over 1.5 / 2.5 / 3.5, both to score).
            How it plays: the one-line script, a possession bar, and the
            reasoning behind a "Why" tap.
            Leans: green chips for lines the game state rates above their
            record, red for good records it rates down. Paddy Power markets only.
            Lines to target: the bets it backs most, with Paddy's price.
  NBA, NFL  The projected score, who is out, then each reason as a card
            with its conclusion first.

Every caveat about the models sits in one "About these numbers" fold at the
bottom. Run by publish.sh after fmodel_live.py. Never fatal.
"""
from __future__ import annotations

import html
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "reports" / "gamestate.json"
DAYS = 4
esc = html.escape


def _grid(lh, la, n=11):
    pois = lambda k, l: math.exp(-l) * l ** k / math.factorial(k)  # noqa: E731
    return {(i, j): pois(i, lh) * pois(j, la) for i in range(n) for j in range(n)}


def _pct(p) -> str:
    return f"{p * 100:.0f}%"


def _fair(p) -> str:
    return f"{1 / p:.2f}" if p and p > 0.01 else "&mdash;"


def _so(text: str) -> str:
    """'so their shots go elsewhere' -> 'Their shots go elsewhere': the conclusion, said plainly."""
    t = (text or "").strip()
    if t[:3].lower() == "so ":
        t = t[3:]
    return t[:1].upper() + t[1:]


def _short(name: str) -> str:
    return (name or "").replace(" & Hove Albion", "").replace(" FC", "").strip()


def result_card(entry, meta) -> str:
    import context
    b = context.brief(entry, meta)
    sc = b.get("score")
    if not sc:
        return ""
    g = _grid(sc["lh"], sc["la"])
    o15 = sum(p for (i, j), p in g.items() if i + j > 1.5)
    o25 = sum(p for (i, j), p in g.items() if i + j > 2.5)
    o35 = sum(p for (i, j), p in g.items() if i + j > 3.5)
    btts = sum(p for (i, j), p in g.items() if i > 0 and j > 0)
    tag, cls = (("Open game", "hot") if o25 >= 0.58 else ("Tight game", "cold") if o25 <= 0.45
                else ("Average for goals", ""))
    h, a = _short(meta["home"]), _short(meta["away"])
    tiles = "".join(
        f"<div class='gs-tile'><span class='k'>{label}</span><b>{_pct(p)}</b>"
        f"<span class='meter'><i style='width:{p * 100:.0f}%'></i></span><span class='f'>fair {_fair(p)}</span></div>"
        for label, p in (("Over 1.5", o15), ("Over 2.5", o25), ("Over 3.5", o35), ("Both score", btts)))
    return (
        "<section class='gs-card gs-result'><h3>The result</h3>"
        f"<div class='gs-score'><span class='t t1'>{esc(h)}</span><b>{sc['home']}&ndash;{sc['away']}</b>"
        f"<span class='t t2'>{esc(a)}</span></div>"
        f"<div class='gs-bar3'><i class='h' style='width:{sc['ph'] * 100:.1f}%'></i>"
        f"<i class='d' style='width:{sc['pd'] * 100:.1f}%'></i><i class='a' style='width:{sc['pa'] * 100:.1f}%'></i></div>"
        f"<div class='gs-bar3-l'><span>{esc(h)} <b>{_pct(sc['ph'])}</b></span><span>Draw <b>{_pct(sc['pd'])}</b></span>"
        f"<span>{esc(a)} <b>{_pct(sc['pa'])}</b></span></div>"
        f"<div class='gs-chips'><span class='gs-chip'>xG <b>{sc['lh']:.2f}</b> &ndash; <b>{sc['la']:.2f}</b></span>"
        f"<span class='gs-chip {cls}'>{tag}</span></div>"
        f"<div class='gs-tiles'>{tiles}</div></section>")


def plays_card(entry, meta, gs) -> str:
    import context
    try:
        b = context.brief(entry, meta)
        st = context.story(entry, meta, gs, b)
    except Exception:  # noqa: BLE001
        st = {"sides": [], "lines": []}
    parts = ["<section class='gs-card gs-plays'><h3>How it plays</h3>"]
    if gs and gs.get("script"):
        parts.append(f"<p class='gs-script'>{esc(gs['script'])}</p>")
    if gs and gs.get("poss"):
        t = [_short(x) for x in gs["teams"]]
        p0, p1 = gs["poss"]
        parts.append(
            "<div class='gs2-poss'><div class='gs2-poss-l'><span>Possession</span></div>"
            f"<div class='gs-bar2'><i class='h' style='width:{p0:.0f}%'><em>{p0:.0f}%</em></i>"
            f"<i class='a' style='width:{p1:.0f}%'><em>{p1:.0f}%</em></i></div>"
            f"<div class='gs-bar3-l'><span>{esc(t[0])} <small>usually {gs['usual'][0]:.0f}%</small></span>"
            f"<span>{esc(t[1])} <small>usually {gs['usual'][1]:.0f}%</small></span></div></div>")
    sides = []
    for side in st.get("sides") or []:
        sh = side.get("shape") or {}
        words = side.get("words") or []
        bits = []
        if sh.get("formation"):
            bits.append(f"<span class='gs-chip'>{esc(sh['formation'])}{'' if sh.get('confirmed') else ' (predicted)'}</span>")
        bits += [f"<span class='gs-chip soft'>{esc(w)}</span>" for w in words[:3]]
        if bits:
            sides.append(f"<div class='gs-side'><b>{esc(_short(side.get('name') or ''))}</b><div class='gs-chips'>{''.join(bits)}</div></div>")
    if sides:
        parts.append("<div class='gs-sides'>" + "".join(sides) + "</div>")
    if st.get("lines"):
        evs = st.get("evidence") or [None] * len(st["lines"])
        label = {"tested": "Tested", "partly": "Partly tested", "untested": "Not tested yet"}
        items = "".join(
            f"<li><b>{esc(_so(so))}</b><span>{esc(r)}</span>"
            + (f"<span class='gs-ev {ev[0]}'>{label.get(ev[0], ev[0])}</span><span class='gs-ev-t'>{esc(ev[1])}</span>"
               if ev else "")
            + "</li>" for (r, so), ev in zip(st["lines"], evs))
        parts.append(f"<details class='gs-why'><summary>Why</summary><ol>{items}</ol></details>")
    parts.append("</section>")
    return "".join(parts)


def leans_card(meta, gs) -> str:
    if not gs or not (gs.get("leans") or gs.get("against")):
        return ""
    import bettable
    sells = lambda r: bettable.check({"player": r["player"], "stat": r["stat"], "alt": True,  # noqa: E731
                                      "threshold": r["line"], "period": "ALL"}, meta, "football")[0]
    def chips(rows, cls):
        return "".join(
            f"<span class='gs-lean {cls}' title='record {r['k']}/{r['n']}'><b>{r['chance'] * 100:.0f}%</b> "
            f"{esc(r['player'])} {r['line']}+ {esc(r['stat'].lower())}<small>{esc(_short(r['team']))} &middot; record {r['k']}/{r['n']}</small></span>"
            for r in rows if sells(r))
    up, down = chips(gs.get("leans") or [], "up"), chips(gs.get("against") or [], "down")
    if not up and not down:
        return ""
    return ("<section class='gs-card gs-leans'><h3>Who it favours</h3>"
            + (f"<p class='gs-lab up'>Rated above their record</p><div class='gs-leanrow'>{up}</div>" if up else "")
            + (f"<p class='gs-lab down'>Good record, weaker tonight</p><div class='gs-leanrow'>{down}</div>" if down else "")
            + "</section>")


def targets_card(entry, meta, gs) -> str:
    import context
    import tonight
    import weekend
    rows = []
    for l in tonight.legs_of(entry, meta):      # Paddy Power markets only, with its price
        if not isinstance(l.get("fair"), (int, float)):
            continue
        try:
            g = context.gs_adjust(l, entry, gs)
        except Exception:  # noqa: BLE001
            g = None
        base = weekend.chance(l) if (l.get("pStrength") or l.get("pShrunk") or l.get("pExchange")) else None
        if base is None:
            h, n = l.get("hits"), l.get("total")
            base = (h + 2) / (n + 4) if isinstance(h, int) and n else None
        if not g or base is None:
            continue
        ch = g["chance"]
        if ch < 0.55 or ch - base < 0.02:
            continue
        rows.append((ch - base, ch, base, l))
    rows.sort(key=lambda r: (-r[1] * (1 + 4 * r[0])))
    if not rows:
        return ""
    out = []
    for lift, ch, base, l in rows[:6]:
        pp = l.get("pp_price")
        val = ""
        if pp:
            e = ch * pp - 1
            val = f"<span class='gs-pp {'pos' if e >= 0 else ''}'>Paddy <b>{pp:.2f}</b></span>"
        out.append(f"<div class='gs-target'><div><b>{esc(tonight.fmt_leg(l))}</b>"
                   f"<small>record {l.get('hits')}/{l.get('total')}</small></div>"
                   f"<div class='gs-tnum'><span class='from'>{base * 100:.0f}%</span> &rarr; <b>{ch * 100:.0f}%</b>"
                   f"<small>fair {1 / ch:.2f}</small>{val}</div></div>")
    return ("<section class='gs-card gs-targets'><h3>Lines it backs</h3>"
            "<p class='gs-lab'>Record &rarr; with the game state</p>" + "".join(out) + "</section>")


# ------------------------------------------------------------ matchups (the paper trail)

_BOOKS: dict = {}


def _books() -> dict:
    """Paddy Power, Bet365 (with Oddschecker's market median) and the player
    model, read once per run."""
    if not _BOOKS:
        for k, f in (("pp", "paddypower.json"), ("b365", "bet365.json"), ("fm", "fmodel.json")):
            try:
                _BOOKS[k] = json.loads((ROOT / "reports" / f).read_text()).get("events") or {}
            except (OSError, ValueError):
                _BOOKS[k] = {}
    return _BOOKS


def _book_lines(book: str, fid, name: str, stat: str) -> dict:
    """{k: line dict} for one player's overs on one stat at one book."""
    import pplog
    ev = (_books().get(book) or {}).get(str(fid)) or {}
    n = pplog._norm(name)
    sur = n.split()[-1:] if n else []
    out = {}
    for l in ev.get("lines") or []:
        key = l.get("key") or pplog._norm(l.get("player", ""))
        if key != n and not (sur and key.split()[-1:] == sur and key[:1] == n[:1]):
            continue
        rd = pplog.read_line(l)
        if not rd or rd[0] != stat or not rd[2]:
            continue
        out[int(round(rd[1] + 0.5))] = l
    return out


def _model_p(fid, name: str, stat: str, k: int):
    import pplog
    ev = (_books().get("fm") or {}).get(str(fid)) or {}
    for nm, pl in (ev.get("players") or {}).items():
        if pplog._norm(nm) == pplog._norm(name):
            v = ((pl.get("lines") or {}).get(stat) or {}).get(str(k))
            return v if isinstance(v, (int, float)) else None
    return None


TRAIL_WHY = {
    "Tackles": "The man he faces carries the ball a lot, so he has more to win back: the clearest matchup "
               "effect in 35,000 starter-games, for every position, and strongest for forwards and midfielders "
               "pressing a ball-carrying defender. It improved forecasts on games the fit had not seen.",
    "Shots": "Defenders and midfielders shoot a little more when the attacker they face wins the ball back a "
             "lot. Tested the same way and small; why is not clear. Not used for forwards: it did not hold there.",
    "Fouled": "Defenders and midfielders win a few more fouls when the attacker they face tackles a lot. "
              "Tested, small. Not used for forwards: it did not hold there.",
    "Fouls": "Facing a man who wins a lot of fouls means committing a few more. Tested, tiny. "
             "'He faces a fouler, so he will be fouled' did not predict, so it is never claimed.",
}
TRAIL_MIN = 0.04          # show a matchup when it moves a count by 4% or more
TRAIL_SHOW = 8


def _line_html(fid, name, stat, mult) -> str:
    """His line nearest evens: our chance before and after the matchup, and
    every book's price beside it."""
    import trail_live
    pp, b3 = _book_lines("pp", fid, name, stat), _book_lines("b365", fid, name, stat)
    ks = sorted(set(pp) | set(b3), key=lambda k: abs(((pp.get(k) or b3.get(k))["price"]) - 1.9))
    for k in ks:
        price = (pp.get(k) or b3.get(k))["price"]
        if not 1.3 <= price <= 4.0:
            continue
        base = _model_p(fid, name, stat, k)
        adj = trail_live.adjust(base, stat, k, mult) if base else None
        books = []
        for lab, l in (("Paddy", pp.get(k)), ("Bet365", b3.get(k))):
            if l:
                v = adj is not None and adj * l["price"] >= 1.05
                books.append(f"<span class='bk{' val' if v else ''}'>{lab} <b>{l['price']:.2f}</b></span>")
        l3 = b3.get(k) or {}
        if l3.get("mkt_median") and l3.get("mkt_n"):
            books.append(f"<span class='bk'>Market <b>{l3['mkt_median']:.2f}</b> ({l3['mkt_n']} books)</span>")
        ch = (f"ours {base * 100:.0f}% &rarr; <b>{adj * 100:.0f}%</b> with the matchup" if adj is not None
              else "no model price")
        return f"<div class='gs-line'>{k}+ {esc(stat.lower())}: {ch} {''.join(books)}</div>"
    return ""


def _history_html(entry, t, name, stat) -> str:
    import trail_live
    rows = trail_live.history(entry, t, name, stat)
    if not rows:
        return ""
    drv = (trail_live.fit().get(trail_live.STAT_FIT.get(stat, "")) or {}).get("driver")
    dw = trail_live.DRIVER_WORDS.get(drv, drv or "")
    cells = []
    for r in rows:
        did = "" if r["opp_did"] is None else str(r["opp_did"])
        poss = "" if r["poss"] is None else f"{r['poss']:.0f}%"
        cells.append(f"<tr><td>{esc((r['date'] or '')[5:])}</td><td>{esc(_short(r['opponent'] or ''))}</td>"
                     f"<td class='n'><b>{r['value']}</b></td><td>{esc(r['opp'] or '?')}</td>"
                     f"<td class='n'>{did}</td><td class='n'>{poss}</td></tr>")
    body = "".join(cells)
    return (f"<details class='gs-trailh'><summary>His last {len(rows)} starts: who he faced</summary>"
            f"<table class='gs-tr'><tr><th>Date</th><th>v</th><th>{esc(stat)}</th><th>Faced</th>"
            f"<th>Their {esc(dw)}</th><th>Ball</th></tr>{body}</table></details>")


def matchups_card(entry, meta) -> str:
    import trail_live
    mu = trail_live.matchups(entry)
    if not mu:
        return ""
    teams = entry.get("teams") or []
    tix = {(tm or {}).get("side"): i for i, tm in enumerate(teams[:2])}
    items = []
    for side in ("home", "away"):
        for m in mu.get(side) or []:
            effs = {s: e for s, e in m["effects"].items() if e["rate"] is not None and abs(e["mult"] - 1) >= TRAIL_MIN}
            if not effs:
                continue
            items.append((max(abs(e["mult"] - 1) for e in effs.values()), side, m, effs))
    if not items:
        return ""
    items.sort(key=lambda x: -x[0])
    out = []
    for _, side, m, effs in items[:TRAIL_SHOW]:
        team = _short((teams[tix.get(side, 0)] or {}).get("name") or "")
        main = max(effs, key=lambda s: abs(effs[s]["mult"] - 1))
        e = effs[main]
        dw = trail_live.DRIVER_WORDS.get(e["driver"], e["driver"])
        chips = "".join(f"<span class='gs-eff {'up' if v['mult'] > 1 else 'down'}'>{esc(s)} "
                        f"{(v['mult'] - 1) * 100:+.0f}%</span>" for s, v in sorted(effs.items(), key=lambda kv: -abs(kv[1]['mult'] - 1)))
        out.append(
            f"<div class='gs-mu'><div class='gs-mu-h'><span><b>{esc(m['player'])}</b> <small>{esc(team)}, {esc(m['pos'] or '')}</small>"
            f" faces <b>{esc(m['opp'])}</b> <small>{esc(m['opp_pos'] or '')}</small></span></div>"
            f"<small>{esc(m['opp'])}: {e['rate']:.1f} {esc(dw)} a 90, {esc(e['band'])} of direct opponents</small>"
            f"<div>{chips}</div>"
            + "".join(_line_html(meta.get("id"), m["player"], s, effs[s]["mult"]) for s in effs)
            + _history_html(entry, tix.get(side, 0), m["player"], main) + "</div>")
    why = "".join(f"<li><b>{esc(s)}</b> {esc(w)}</li>" for s, w in TRAIL_WHY.items())
    return ("<section class='gs-card gs-trail'><h3>Matchups</h3>"
            "<p class='gs-lab'>Who each starter faces, from where they usually play, and what it is worth</p>"
            + "".join(out)
            + f"<details class='gs-why'><summary>What these are based on</summary><ul>{why}</ul></details></section>")


ABOUT_FOOTBALL = (
    "The result and goals come from the score model (the style model for same-league games, Elo and recent xG "
    "for European ties). Checked against Betfair on 85 games the exchange was better on goals, and against "
    "closing odds on 2,579 league games it was worse on the result too: read it as a picture of the game, not a "
    "price to bet against the market. The game state's weights come from a walk-forward backtest (GS_BACKTEST.md). "
    "Only Paddy Power markets are listed in Lines it backs. Matchups: each outfield starter is paired one to one "
    "with the opponent nearest where he usually plays (average positions over his last 10 games), and the "
    "opponent's habit moves his expected count by what 35,000 starter-games showed it is worth "
    "(research/TRAIL-2026-11-02.md). 'Faces a fouler, so he will be fouled' did not predict and is never claimed. "
    "Chances there are the player model's before and after the matchup, without Super Sub or Sub On Play On; "
    "a price is marked when our chance times it is 1.05 or more. Market is the median of every book Oddschecker lists.")


def block(entry, meta) -> str:
    import context
    gs = None
    try:
        gs = context.game_state(meta)
    except Exception:  # noqa: BLE001
        pass
    parts = []
    for fn in (lambda: result_card(entry, meta), lambda: plays_card(entry, meta, gs),
               lambda: matchups_card(entry, meta),
               lambda: leans_card(meta, gs), lambda: targets_card(entry, meta, gs)):
        try:
            parts.append(fn() or "")
        except Exception as exc:  # noqa: BLE001
            parts.append(f"<section class='gs-card'><p class='sub'>Unavailable ({esc(str(exc))})</p></section>")
    return ("<div class='gs-tab gs2'><div class='gs-grid'>" + "".join(parts) + "</div>"
            f"<details class='gs-about'><summary>About these numbers</summary><p>{esc(ABOUT_FOOTBALL)}</p></details></div>")


US_NOTE = {
    "basketball": "Pace, ratings, blowout rate and rest are from each side's last 10 (usgame.py). In the "
                  "backtest the game-state version of the team model did not beat the simple one, so this "
                  "explains the game; it does not move the chances.",
    "american-football": "Game script from nflgame.py. The 22 Oct 2026 backtest (NFL_GS_BACKTEST.md) found it "
                         "improved no NFL market and made passing yards worse on unseen games, so use it to "
                         "read the game, not as a reason to back an over.",
}


def us_block(entry, meta, sport) -> str:
    import context
    import tonight
    try:
        st = context.nba_story(entry, meta) if sport == "basketball" else context.nfl_story(entry, meta)
    except Exception as exc:  # noqa: BLE001
        return f"<div class='gs-tab gs2'><p class='sub'>Unavailable ({esc(str(exc))})</p></div>"
    h, a = esc(meta["home"]), esc(meta["away"])
    parts = []
    sc = st.get("score")
    if sc:
        label = "Team model" if sport == "basketball" else "Points form (a guide, not a model)"
        margin = abs(sc["home"] - sc["away"])
        fav = h if sc["home"] >= sc["away"] else a
        parts.append(
            f"<section class='gs-card gs-result'><h3>{label}</h3>"
            f"<div class='gs-score'><span class='t t1'>{h}</span><b>{sc['home']:.0f}&ndash;{sc['away']:.0f}</b>"
            f"<span class='t t2'>{a}</span></div>"
            f"<div class='gs-chips'><span class='gs-chip'>Total <b>{sc.get('total', sc['home'] + sc['away']):.0f}</b></span>"
            f"<span class='gs-chip'>{fav} by <b>{margin:.0f}</b></span></div>"
            + tonight._out_line(entry, meta).replace("<p class='sub out'>", "<p class='gs-out'>")
            + "</section>")
    if st.get("lines"):
        cards = "".join(f"<div class='gs-reason'><b>{esc(tonight._possessive(_so(so)))}</b>"
                        f"<span>{esc(tonight._possessive(r))}</span></div>" for r, so in st["lines"])
        parts.append(f"<section class='gs-card gs-reasons'><h3>How it plays</h3>{cards}</section>")
    if not parts:
        parts.append("<section class='gs-card'><p class='sub'>No game state for this game yet.</p></section>")
    return ("<div class='gs-tab gs2'><div class='gs-grid'>" + "".join(parts) + "</div>"
            f"<details class='gs-about'><summary>About these numbers</summary><p>{esc(US_NOTE[sport])}</p></details></div>")


def main() -> int:
    import context
    import make_index
    t0, now = time.time(), time.time()
    entries, seen = [], set()
    for path in sorted((ROOT / "reports").glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        for e, m in make_index.read_entries(path):
            if ((e.get("fixture") or {}).get("sport") or "football") not in ("football", "basketball",
                                                                           "american-football"):
                continue
            if m["id"] in seen or not (now - 3 * 3600 < m["kickoff"] < now + DAYS * 86400):
                continue
            seen.add(m["id"])
            entries.append((e, m))
    try:
        context.set_entries(entries)
    except Exception:  # noqa: BLE001
        pass
    out = {"generated": now, "events": {}}
    n = {"football": 0, "basketball": 0, "american-football": 0}
    for e, m in entries:
        sport = (e.get("fixture") or {}).get("sport") or "football"
        n[sport] += 1
        out["events"][str(m["id"])] = {"html": block(e, m) if sport == "football" else us_block(e, m, sport)}
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"  gamestate.json: {n['football']} football, {n['basketball']} NBA, {n['american-football']} NFL "
          f"game(s) in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
