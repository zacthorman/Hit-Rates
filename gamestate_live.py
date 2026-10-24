#!/usr/bin/env python3
"""
The "Game state" tab on every football report page: reports/gamestate.json.

    python gamestate_live.py            # every football fixture in the next 4 days

Per fixture, one block of HTML the page drops into the tab:
  1. The result and goals from the score model (the style model for
     same-league games, research/open_eval.py; Elo + recent xG for European
     ties), with over/under and both-to-score from the same two numbers, and
     whether it reads as an open or a tight game.
  2. How the game should go (tonight.story_block): shapes, styles, the
     reasons and what follows from them.
  3. The game state's leans (tonight.gs_block): lines the matchup rates above
     or below their records.
  4. Lines to target: the bets the game state backs most, with the chance,
     the fair price, and the exchange price where there is one.
Run by publish.sh after fmodel_live.py. Never fatal.
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


def _grid(lh, la, n=11):
    pois = lambda k, l: math.exp(-l) * l ** k / math.factorial(k)  # noqa: E731
    return {(i, j): pois(i, lh) * pois(j, la) for i in range(n) for j in range(n)}


def header(entry, meta) -> str:
    import context
    esc = html.escape
    b = context.brief(entry, meta)
    sc = b.get("score")
    if not sc:
        return "<p class='none'>No score model for this game.</p>"
    g = _grid(sc["lh"], sc["la"])
    o15 = sum(p for (i, j), p in g.items() if i + j > 1.5)
    o25 = sum(p for (i, j), p in g.items() if i + j > 2.5)
    o35 = sum(p for (i, j), p in g.items() if i + j > 3.5)
    btts = sum(p for (i, j), p in g.items() if i > 0 and j > 0)
    tag = ("an open game" if o25 >= 0.58 else "a tight game" if o25 <= 0.45 else "about average for goals")
    pct = lambda p: f"{p * 100:.0f}%"  # noqa: E731
    fair = lambda p: f"{1 / p:.2f}" if p > 0.01 else "&mdash;"  # noqa: E731
    return (
        "<div class='gs-head'>"
        f"<p class='call'><b>Most likely:</b> {esc(meta['home'])} {sc['home']}&ndash;{sc['away']} {esc(meta['away'])} "
        f"<span class='sub'>({esc(sc.get('source', ''))})</span></p>"
        "<table class='gs-t'><thead><tr><th></th><th class='n'>Chance</th><th class='n'>Fair</th></tr></thead><tbody>"
        f"<tr><td>{esc(meta['home'])} win</td><td class='n'>{pct(sc['ph'])}</td><td class='n'>{fair(sc['ph'])}</td></tr>"
        f"<tr><td>Draw</td><td class='n'>{pct(sc['pd'])}</td><td class='n'>{fair(sc['pd'])}</td></tr>"
        f"<tr><td>{esc(meta['away'])} win</td><td class='n'>{pct(sc['pa'])}</td><td class='n'>{fair(sc['pa'])}</td></tr>"
        f"<tr><td>Over 1.5 goals</td><td class='n'>{pct(o15)}</td><td class='n'>{fair(o15)}</td></tr>"
        f"<tr><td>Over 2.5 goals</td><td class='n'>{pct(o25)}</td><td class='n'>{fair(o25)}</td></tr>"
        f"<tr><td>Over 3.5 goals</td><td class='n'>{pct(o35)}</td><td class='n'>{fair(o35)}</td></tr>"
        f"<tr><td>Both teams to score</td><td class='n'>{pct(btts)}</td><td class='n'>{fair(btts)}</td></tr>"
        "</tbody></table>"
        f"<p class='sub'>Expected goals {esc(meta['home'])} {sc['lh']:.2f}, {esc(meta['away'])} {sc['la']:.2f}: "
        f"<b>{tag}</b>. Over/under and both-to-score come from these two numbers. Checked against Betfair's own "
        "prices on 85 games, the exchange was clearly better on goals; against closing bookmaker odds on 2,579 league "
        "games it was worse on the result too, and backing its disagreements lost 3&ndash;13%. Use these as a read "
        "of the game, not as a price to bet against the market.</p></div>")


def targets(entry, meta, gs) -> str:
    import context
    import tonight
    import weekend
    esc = html.escape
    rows = []
    for l in tonight.legs_of(entry, meta):
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
            continue  # only lines the game state pushes up, and that are likely
        ex = l.get("exchange") or {}
        back = ex.get("back") if ex.get("kind") == "exchange" else None
        rows.append((ch - base, ch, base, l, back, g.get("kind", "")))
    rows.sort(key=lambda r: (-r[1] * (1 + 4 * r[0])))
    if not rows:
        return "<p class='none'>Nothing here that the game state rates clearly above its record.</p>"
    out = []
    for lift, ch, base, l, back, kind in rows[:8]:
        edge = ""
        if back:
            e = ch * back - 1
            edge = f"<b>{back:.2f}</b> ({'+' if e >= 0 else ''}{e * 100:.0f}%)"
        out.append(f"<tr><td>{esc(tonight.fmt_leg(l))}<div class='sub'>record {l.get('hits')}/{l.get('total')} "
                   f"&middot; {esc(kind)}</div></td><td class='n'>{base * 100:.0f}% &rarr; <b>{ch * 100:.0f}%</b></td>"
                   f"<td class='n'>{1 / ch:.2f}</td><td class='n'>{edge or '&mdash;'}</td></tr>")
    return ("<table class='gs-t'><thead><tr><th>Line</th><th class='n'>Record &rarr; game state</th>"
            "<th class='n'>Fair</th><th class='n'>Exchange</th></tr></thead><tbody>" + "".join(out) + "</tbody></table>"
            "<p class='sub'>Lines the matchup and game state rate higher than their own record, most likely first. "
            "A line is worth backing when a bookmaker's price is longer than its fair price; the exchange column "
            "shows the price and the edge at it where Betfair has the market.</p>")


def block(entry, meta) -> str:
    import context
    import tonight
    gs = None
    try:
        gs = context.game_state(meta)
    except Exception:  # noqa: BLE001
        pass
    parts = ["<div class='gs-tab'>"]
    for title, fn in (("The result and goals", lambda: header(entry, meta)),
                      ("How the game will go", lambda: tonight.story_block(entry, meta, gs)),
                      ("What the game state leans to", lambda: tonight.gs_block(gs)),
                      ("Lines to target", lambda: targets(entry, meta, gs))):
        try:
            body = fn()
        except Exception as exc:  # noqa: BLE001
            body = f"<p class='sub'>Unavailable ({html.escape(str(exc))})</p>"
        if body:
            parts.append(f"<h3>{title}</h3>{body}")
    parts.append("</div>")
    return "".join(parts)


def main() -> int:
    import context
    import make_index
    t0, now = time.time(), time.time()
    entries, seen = [], set()
    for path in sorted((ROOT / "reports").glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        for e, m in make_index.read_entries(path):
            if ((e.get("fixture") or {}).get("sport") or "football") != "football":
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
    for e, m in entries:
        out["events"][str(m["id"])] = {"html": block(e, m)}
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"  gamestate.json: {len(out['events'])} football game(s) in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
