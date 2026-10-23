"""
One small page of what is on soon, built from the reports already on disk.

    python tonight.py                    the next 6 hours
    python tonight.py --hours 12         a longer window
    python tonight.py --all              everything still to come

Why this exists, and why it is deliberately not another report.

A built report is one to twenty megabytes: the whole dataset is inlined so the
page can rebuild any view without a server. That is the right trade for a
laptop and a browser and completely the wrong one for a phone on 4G at a bus
stop -- and it also means nothing but a real browser can read it. A fetcher
truncates it to the first fixture and sees no numbers at all, which is exactly
what happened the evening this was written: the reports had been published
hours before kickoff and were still unusable, because the only thing that
could read them was a machine that was asleep.

So this renders the answers rather than the data. It runs the same engine --
weekend.legs_for, best_acca, builders_for, parlay -- over the payloads already
sitting in reports/, and writes a static page of maybe forty kilobytes with no
JavaScript in it. That page is legible on a phone, legible to a fetcher, and
needs nothing running anywhere once it is published.

It is a view, not a source. Every number here came out of a report, so it is
exactly as fresh as the last build and no fresher, and the header says when
that was.
"""

import argparse
import html
import time
from pathlib import Path

import make_index
import parlay
import value_cap
import weekend

ROOT = Path(__file__).resolve().parent

# How many single legs to print per fixture. Enough to choose from, few enough
# that the page stays a page. The scan behind it has already ranked them.
SINGLES_PER_FIXTURE = 6

# Below this, a leg is not worth a slot.
#
# Ranking singles purely on evidence fills the list with 1.11 shots: "1+
# tackles, 28 from 31" is a near-certainty and therefore always wins an
# evidence sort, and it is also not a bet -- four of them multiply to less
# than evens and the margin eats the lot. parlay.py already draws this line
# for the same reason, so the same number is used here rather than a second
# opinion about it.
MIN_PRICE = parlay.MIN_LEG_PRICE

# The multi is offered at several shapes rather than one, because "a treble"
# and "something paying about eight" are different questions and the honest
# answer to the second is sometimes four legs rather than three.
ACCA_SHAPES = ((3, 3.0), (3, 6.0), (4, 10.0))


def fmt_leg(leg) -> str:
    """A leg written the way a coupon writes it."""
    who = leg.get("player") or leg.get("team") or "?"
    stat = (leg.get("stat") or "").lower()
    if leg.get("alt"):
        market = f"{leg['threshold']:.0f}+ {stat}"
    else:
        market = f"{'over' if leg.get('over') else 'under'} {leg.get('line')} {stat}"
    period = leg.get("period")
    when = "" if period in (None, "ALL") else f" ({'first half' if period == '1ST' else 'second half'})"
    return f"{who} {market}{when}"


def legs_of(entry, meta) -> list:
    """Every priceable leg on one fixture, each one only once.

    The three sources overlap: an alt line and a single can describe the same
    bet from different directions, and printing "Zaire-Emery 1+ tackles"
    twice in a six-row table is how a short list stops looking trustworthy.
    """
    out, seen = [], set()
    for leg in (weekend.legs_for(entry, meta)
                + parlay.single_legs_for(entry, meta)
                + parlay.alt_legs_for(entry, meta)):
        key = (leg.get("player"), leg.get("team"), leg.get("stat"),
               leg.get("period"), leg.get("line"), leg.get("over"))
        if key in seen:
            continue
        seen.add(key)
        out.append(leg)
    # Same calibrated prices the picks use, so a leg reads the same here.
    return weekend.calibrate(out)


def odds(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) and x == x and x != float("inf") else "&mdash;"


def leg_row(leg, entry=None) -> str:
    hits, total = leg.get("hits"), leg.get("total")
    record = f"{hits}/{total}" if total else "&mdash;"
    # The venue split is printed because it repeatedly changes the answer, and
    # a rate quoted without it has quietly averaged two different teams.
    where = {"home": " at home", "away": " away"}.get(leg.get("venue"), "")
    st = leg.get("strength") or {}
    strength_note = ""
    if st.get("team") is not None:
        fx = leg.get("fixture") or {}
        opp = fx.get("away") if leg.get("team") == fx.get("home") else fx.get("home")
        bits = [f"{st['team']} v {html.escape(str(opp or 'opponent'))} {st['opp']}"]
        if st.get("win") is not None:
            bits.append(f"{st['win'] * 100:.0f}% to win")
        if (st.get("similarN") or 0) >= 2:
            bits.append(f"{st['similarHits']} of {st['similarN']} v similar")
        else:
            bits.append("nothing comparable in the record")
        strength_note = f"<br><span class='sub'>{' &middot; '.join(bits)}</span>"
    chance = weekend.chance(leg) if (leg.get("pStrength") or leg.get("pShrunk") or leg.get("pExchange")) else None
    record += f"<br><span class='sub'>{chance * 100:.0f}%</span>" if chance else ""
    q = leg.get("exchange")
    if q:
        bits = [f"Betfair {q['p'] * 100:.0f}%"]
        if q.get("back"):
            bits.append(f"back {q['back']:.2f}")
        if leg.get("value") is not None:
            v = leg["value"]
            bits.append(f"<b>{'+' if v >= 0 else '&minus;'}{abs(v) * 100:.1f}% value</b>")
        elif leg.get("disagree") is not None:
            bits.append(f"model {abs(leg['disagree']) * 100:.0f} pts off the market")
        strength_note += f"<br><span class='sub'>{' &middot; '.join(bits)}</span>"
    if entry is not None:
        try:
            import context
            a = context.opp_allows(leg, entry)
            if a:
                strength_note += f"<br><span class='allow'>{html.escape(a['text'])}</span>"
            g = leg.get("gs")
            if g:
                bits = [f"opponent &times;{g['oppf']:.2f}"]
                if abs(g["factor"] - 1) >= 0.02:
                    bits.append(f"game state &times;{g['factor']:.2f}")
                kind = g.get("kind") or "model"
                before = (f"; {g['plain'] * 100:.0f}% before the game state"
                          if abs(g["plain"] - g["model"]) >= 0.005 else "")
                strength_note += (f"<br><span class='gs'>Backtested {html.escape(kind)} <b>{g['model'] * 100:.0f}%</b> "
                                  f"({', '.join(bits)}{before}). "
                                  f"With the record: <b>{g['chance'] * 100:.0f}%</b></span>")
            mn = context.minutes_note(entry, leg) if leg.get("player") else None
            if mn:
                strength_note += f"<br><span class='sub'>Minutes: {html.escape(mn)}</span>"
        except Exception:
            pass
    try:
        import why
        w = why.reasons(leg)
        lines = ([f"+ {html.escape(t)}" for t in w["for"][:2]]
                 + [f"&minus; {html.escape(t)}" for t in w["against"][:2]])
        if lines:
            strength_note += "<br><span class='sub'>" + "<br>".join(lines) + "</span>"
    except Exception:
        pass
    return (
        f"<tr><td>{html.escape(fmt_leg(leg))}{where}{strength_note}</td>"
        f"<td class='n'>{record}</td>"
        f"<td class='n'>{odds(leg.get('fair'))}</td>"
        f"<td class='n'>{odds(leg.get('need'))}</td></tr>"
    )


def _form_table(side) -> str:
    rows = "".join(
        f"<tr><td class='sub'>{html.escape(f['date'])}</td><td class='sub'>{html.escape(f['comp'])}</td>"
        f"<td>{'v' if f['venue'] == 'H' else '@'} {html.escape(f['opp'])}</td>"
        f"<td class='n'>{f['gf']}-{f['ga']}</td><td class='n'><span class='res {f['res']}'>{f['res']}</span></td></tr>"
        for f in reversed(side["form"]))
    return f"<table class='form'><tbody>{rows}</tbody></table>"


def _side_block(side, comp) -> str:
    """One team's card: form, the last ten in counts, xG, table, what comes next, who is out."""
    esc = html.escape
    c = side["counts"]
    lines = []
    if c["n"]:
        lines.append(f"Last {c['n']}: won {c['won']}, scored in {c['scored']}, conceded in {c['conceded']}, "
                     f"clean sheets {c['clean']}, BTTS {c['btts']}, 3+ goals {c['over25']} "
                     f"({c['gf']} for, {c['ga']} against)")
    x = side.get("xg")
    if x:
        lines.append(f"xG last {x['n']}: {x['for']:.1f} for, {x['against']:.1f} against "
                     f"({x['for_pg']:.2f} and {x['against_pg']:.2f} a game)")
    tb = side.get("table")
    if tb and tb.get("played"):
        pos = f", {tb['pos']}{context_ordinal(tb['pos'])} of {tb['of']}" if tb.get("pos") else ""
        lines.append(f"{esc(comp)}: {tb['points']} pts from {tb['played']}{pos}")
    if side.get("next"):
        nxt = " &middot; ".join(
            f"{'v' if n['venue'] == 'H' else '@'} {esc(n['opp'])} ({esc(n['comp'])}, {esc(n['date'])})"
            for n in side["next"])
        lines.append(f"Next: {nxt}")
    if side.get("absences"):
        out = ", ".join(
            f"{esc(a['name'])} ({esc(a['status'].split(' (')[0].lower())}, {a['starts']}/{a['of']} starts)"
            for a in side["absences"][:5])
        lines.append(f"Missing: {out}")
    body = "".join(f"<p class='sub line'>{l}</p>" for l in lines)
    return f"<div class='side'><h4>{esc(side['name'] or '')}</h4>{_form_table(side)}{body}</div>"


def context_ordinal(n) -> str:
    import context
    return context._ordinal(n)


def gs_block(gs) -> str:
    """How the game should go, and the bets that changes."""
    esc = html.escape
    if not gs:
        return ""
    parts = ["<div class='gsbox'><p class='call'><b>Game state</b> <span class='sub'>("
             + esc(gs["xi"]) + ("; weights from a walk-forward backtest, see GS_BACKTEST.md)" if gs.get("fitted")
                               else "; no backtest fit found, adjustments off)") + "</span></p>"]
    if gs.get("poss"):
        t = gs["teams"]
        parts.append(
            f"<p class='sub line'>Expected possession: {esc(t[0])} {gs['poss'][0]:.0f}% "
            f"(usually {gs['usual'][0]:.0f}%), {esc(t[1])} {gs['poss'][1]:.0f}% (usually {gs['usual'][1]:.0f}%). "
            f"Recent xG: {esc(t[0])} {gs['xg'][0]:.2f} for, {gs['xga'][0]:.2f} against; "
            f"{esc(t[1])} {gs['xg'][1]:.2f} for, {gs['xga'][1]:.2f} against.</p>")
    parts.append(f"<p class='argue gsarg'>{esc(gs['script'])}</p>")
    if gs.get("leans"):
        rows = "".join(
            f"<li>{esc(r['player'])} {r['line']}+ {esc(r['stat'].lower())} <span class='sub'>({esc(r['team'])})</span>: "
            f"record {r['k']}/{r['n']}, model <b>{r['chance'] * 100:.0f}%</b> "
            f"(opponent &times;{r['oppf']:.2f}, game state &times;{r['ball']:.2f}; {r['avg']:.1f} &rarr; {r['mu']:.1f} a game)</li>"
            for r in gs["leans"])
        parts.append(f"<p class='call'><b>Tonight leans to</b> <span class='sub'>(the matchup and game state rate these above their records)</span></p><ul class='facts'>{rows}</ul>")
    if gs.get("against"):
        rows = "".join(
            f"<li>{esc(r['player'])} {r['line']}+ {esc(r['stat'].lower())} <span class='sub'>({esc(r['team'])})</span>: "
            f"record {r['k']}/{r['n']} looks good, but model {r['chance'] * 100:.0f}% tonight "
            f"(opponent &times;{r['oppf']:.2f}, game state &times;{r['ball']:.2f})</li>"
            for r in gs["against"])
        parts.append(f"<p class='call'><b>Tonight works against</b></p><ul class='facts'>{rows}</ul>")
    parts.append("</div>")
    return "".join(parts)


def case_block(entry, meta, lead, gs=None) -> str:
    """The reel-style argument for a fixture: the call, the bet, why, then the evidence."""
    try:
        import context
        b = context.brief(entry, meta)
    except Exception as exc:          # never cost the page its other sections
        return f"<p class='sub'>Context unavailable ({html.escape(str(exc))})</p>"
    esc = html.escape
    comp = context._short(meta.get("competition"))
    parts = ["<div class='case'>"]
    sc = b.get("score")
    if sc:
        parts.append(
            f"<p class='call'><b>Call:</b> {esc(meta['home'])} {sc['home']}-{sc['away']} {esc(meta['away'])}"
            f" <span class='sub'>&middot; home {sc['ph'] * 100:.0f}% &middot; draw {sc['pd'] * 100:.0f}% "
            f"&middot; away {sc['pa'] * 100:.0f}% &middot; {sc['lh'] + sc['la']:.1f} goals expected "
            f"&middot; {esc(sc['source'])}</span></p>")
    allows, why_for = None, None
    if lead:
        try:
            allows = context.opp_allows(lead, entry)
        except Exception:
            allows = None
        try:
            import why
            why_for = why.reasons(lead).get("for")
        except Exception:
            why_for = None
        parts.append(f"<p class='call'><b>Lead:</b> {esc(fmt_leg(lead))} &middot; fair "
                     f"<b>{odds(lead.get('fair'))}</b>, need <b>{odds(lead.get('need'))}</b></p>")
    argument = context.case(lead, b, allows, why_for)
    if gs and gs.get("poss"):
        argument += " " + gs["script"]
        g = (lead or {}).get("gs")
        if g:
            argument += (f" The backtested {g.get('kind') or 'model'} makes this bet {g['model'] * 100:.0f}%; "
                         f"with the record, {g['chance'] * 100:.0f}%.")
    parts.append(f"<p class='argue'>{esc(argument)}</p>")
    parts.append(gs_block(gs))
    if b.get("facts"):
        parts.append("<ul class='facts'>" + "".join(f"<li>{esc(f)}</li>" for f in b["facts"]) + "</ul>")
    sides = [s for s in (b.get("home"), b.get("away")) if s]
    parts.append("<div class='sides'>" + "".join(_side_block(s, comp) for s in sides) + "</div>")
    parts.append("</div>")
    return "".join(parts)


def _possessive(text: str) -> str:
    """'Hawks's' -> 'Hawks'' and 'Stade Rennais's' -> 'Stade Rennais''."""
    import re
    return re.sub(r"(\w)s's\b", r"\1s'", text)


def lead_only(lead) -> str:
    """Outside football the case is just the lead: the argument and story are football's."""
    if not lead:
        return "<p class='none'>Nothing for us here: no leg cleared the bar on the evidence.</p>"
    return (f"<p class='call'><b>Lead:</b> {html.escape(fmt_leg(lead))} &middot; fair "
            f"<b>{odds(lead.get('fair'))}</b>, need <b>{odds(lead.get('need'))}</b></p>")


def nba_story_block(entry, meta) -> str:
    esc = html.escape
    try:
        import context
        st = context.nba_story(entry, meta)
    except Exception as exc:
        return f"<p class='sub'>Game story unavailable ({esc(str(exc))})</p>"
    if not st.get("lines"):
        return "<p class='none'>No team model or game state for this game yet.</p>"
    parts = ["<div class='story'>"]
    sc = st.get("score")
    if sc:
        parts.append(f"<p class='call'><b>Most likely:</b> {esc(meta['home'])} {sc['home']:.0f}, "
                     f"{esc(meta['away'])} {sc['away']:.0f} <span class='sub'>(total {sc['total']:.0f}; "
                     f"team model)</span></p>")
    items = "".join(f"<li>{esc(_possessive(r))} <b>{esc(_possessive(so[0].upper() + so[1:]))}</b></li>" for r, so in st["lines"])
    parts.append(f"<p class='call'><b>Why</b></p><ol class='why'>{items}</ol>")
    parts.append("<p class='sub'>Pace, ratings, blowout rate and rest are from each side's last 10 (usgame.py). "
                 "The NBA team model is the simple one: in the backtest the game-state version did not beat "
                 "it on validation, so these lines explain the game rather than move the chances.</p></div>")
    return "".join(parts)


def story_block(entry, meta, gs) -> str:
    """How the game will go: shapes, styles, the likely script, and the reasoning."""
    esc = html.escape
    try:
        import context
        b = context.brief(entry, meta)
        st = context.story(entry, meta, gs, b)
    except Exception as exc:
        return f"<p class='sub'>Match story unavailable ({esc(str(exc))})</p>"
    parts = ["<div class='story'>"]
    sc = b.get("score")
    if sc:
        parts.append(f"<p class='call'><b>Most likely:</b> {esc(meta['home'])} {sc['home']}-{sc['away']} "
                     f"{esc(meta['away'])} <span class='sub'>(home {sc['ph'] * 100:.0f}%, draw "
                     f"{sc['pd'] * 100:.0f}%, away {sc['pa'] * 100:.0f}%)</span></p>")
    for side in st["sides"]:
        sh = side.get("shape") or {}
        bits = []
        if sh.get("formation"):
            bits.append(f"{esc(sh['formation'])}{'' if sh.get('confirmed') else ' (predicted)'}")
        if sh.get("pivot"):
            kind = "double pivot" if len(sh["pivot"]) == 2 else ("single pivot" if len(sh["pivot"]) == 1 else "midfield three")
            bits.append(f"{kind}: {esc(', '.join(sh['pivot']))}")
        if sh.get("attack_mids"):
            bits.append(f"behind the striker: {esc(', '.join(sh['attack_mids']))}")
        words = side.get("words") or []
        how = ("They " + "; ".join(esc(w) for w in words) + ".") if words else "No style stands out against the rest of the site."
        parts.append(f"<p class='line'><b>{esc(side['name'] or '')}</b> "
                     f"<span class='sub'>{' &middot; '.join(bits)}</span><br>{how}</p>")
    if st["lines"]:
        items = "".join(f"<li>{esc(_possessive(r))} <b>{esc(_possessive(so[0].upper() + so[1:]))}</b></li>" for r, so in st["lines"])
        parts.append(f"<p class='call'><b>Why</b></p><ol class='why'>{items}</ol>")
    else:
        parts.append("<p class='none'>No clash between the two styles stands out enough to call.</p>")
    parts.append("<p class='sub'>Style words are used only when a side is in the top or bottom quarter of "
                 "every team on the site. Player chances are the backtested player model's.</p></div>")
    return "".join(parts)


def player_row(leg) -> str:
    """One playerlines.py suggestion: the player's own rung, and why."""
    trend = leg.get("trend")
    note = [f"avg {leg['avg']:.1f} last {leg['recentN']}"]
    if trend and abs(trend - 1) >= 0.1:
        note.append(f"last 3 {'up' if trend > 1 else 'down'} {abs(trend - 1) * 100:.0f}%")
    if leg.get("lineupStatus"):
        note.append(leg["lineupStatus"])
    return (
        f"<tr><td>{html.escape(fmt_leg(leg))}"
        f"<br><span class='sub'>{html.escape(leg.get('team') or '')} &middot; "
        f"{' &middot; '.join(html.escape(n) for n in note)}</span></td>"
        f"<td class='n'>{leg['recentHits']}/{leg['recentN']}"
        f"<br><span class='sub'>{leg['hits']}/{leg['total']} all</span></td>"
        f"<td class='n'>{leg['chance'] * 100:.0f}%</td>"
        f"<td class='n'>{odds(leg.get('fair'))}</td></tr>"
    )


def builder_block(builder) -> str:
    """A same-game builder, with the correlation discount shown rather than hidden."""
    if not builder:
        return "<p class='none'>No same-game builder here: no set of legs on one team both qualified and co-occurred often enough to price.</p>"
    rows = "".join(f"<li>{html.escape(fmt_leg(l))}</li>" for l in builder["legs"])
    fair = builder.get("fair")
    naive = builder.get("naive")
    need = builder.get("need")
    hits, total = builder.get("hits"), builder.get("total")

    gap = ""
    if isinstance(fair, (int, float)) and isinstance(naive, (int, float)) and naive > fair:
        gap = (f" Multiplying the legs would say <b>{naive:.2f}</b>; they actually "
               f"landed together {hits} times in {total}, so the real price is "
               f"<b>{fair:.2f}</b>. That gap is the correlation, and it is the whole "
               f"reason a builder looks better than it is.")

    return (
        f"<ul class='legs'>{rows}</ul>"
        f"<p class='price'>Landed together <b>{hits}/{total}</b> &middot; "
        f"fair <b>{fair:.2f}</b> &middot; "
        f"needs <b>{need:.2f}</b> to be a bet on the evidence.{gap}</p>"
    )


def acca_block(acca, wanted, target) -> str:
    if not acca or not acca.get("legs"):
        return ""
    rows = "".join(
        f"<li>{html.escape(fmt_leg(l))} "
        f"<span class='sub'>{l.get('hits')}/{l.get('total')} &middot; "
        f"fair {l['fair']:.2f} &middot; "
        f"{html.escape((l.get('fixture') or {}).get('home','?'))} v "
        f"{html.escape((l.get('fixture') or {}).get('away','?'))}</span></li>"
        for l in acca["legs"]
    )
    combined = acca.get("combined")
    short = acca.get("short")
    note = (f" Short of the {target:.2f} asked for &mdash; nothing on the board "
            f"multiplies that far at this many legs." if short else "")
    return (
        f"<h3>{wanted} legs, aiming at {target:.2f}</h3>"
        f"<ol class='legs'>{rows}</ol>"
        f"<p class='price'>Fair combined <b>{combined:.2f}</b>.{note}</p>"
    )


# ---------------------------------------------------- researched picks
#
# Hand-researched picks for a night, from research_picks.json beside this
# file: the model's legs checked against team news, line-ups and referees.
# Shown at the top of the page until the file's `expires` (unix time), then
# silently dropped, so a stale file can never pass itself off as tonight's.

def research_block(now: float) -> str:
    import json
    path = ROOT / "research_picks.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if now >= (data.get("expires") or 0):
        return ""
    esc = html.escape
    parts = [f"<section class='research'><h2>{esc(data.get('title', 'Researched picks'))}</h2>",
             f"<p class='comp'>Written {esc(data.get('written', ''))}. {esc(data.get('intro', ''))}</p>"]
    for group in data.get("groups") or []:
        rows = "".join(
            f"<tr><td>{esc(p['selection'])}<br><span class='sub'>{esc(p['fixture'])}"
            f" &middot; {esc(p.get('why', ''))}</span></td>"
            f"<td class='n'>{p['chance'] * 100:.0f}%</td>"
            f"<td class='n'>{odds(p.get('fair'))}</td></tr>"
            for p in group.get("picks") or [])
        parts.append(
            f"<h3>{esc(group.get('kickoff', ''))}</h3>"
            f"<table><thead><tr><th>Selection</th><th class='n'>Chance</th>"
            f"<th class='n'>Fair</th></tr></thead><tbody>{rows}</tbody></table>")
        if group.get("avoid"):
            parts.append(f"<p class='price'>{esc(group['avoid'])}</p>")
    multi = data.get("multi")
    if multi:
        legs = "".join(f"<li>{esc(l)}</li>" for l in multi.get("legs") or [])
        parts.append(f"<h3>One multiple</h3><ol class='legs'>{legs}</ol>"
                     f"<p class='price'>About <b>{odds(multi.get('fair'))}</b> fair. "
                     f"{esc(multi.get('note', ''))}</p>")
    if data.get("caveats"):
        items = "".join(f"<li>{esc(c)}</li>" for c in data["caveats"])
        parts.append(f"<div class='warn'><ul class='legs'>{items}</ul></div>")
    parts.append("</section>")
    return "".join(parts)


# ---------------------------------------------------------- the results card
#
# Each fixture's lead is written to lead_log.json before kick-off (append and
# update until kick-off, never after), and settled against best_bets.json,
# which besttrack.py settles from the result. besttrack.track_leads adds any
# lead the snapshot missed, so every lead logged here has a leg to settle.
# The card shows the last day's leads ticked or crossed, and how many the
# page expected to land, so the page is marked on its own calls.

LEAD_LOG = ROOT / "lead_log.json"
KEY = ("event_id", "team", "player", "stat", "period", "line", "over")


def _leg_key(l) -> tuple:
    return tuple(l.get(k) for k in KEY)


def tonight_chance(l, sport: str | None = None) -> float:
    """The chance a fixture's lead is picked on and logged with.

    The game state's chance where it reaches the leg. Legs it cannot reach
    keep their own chance, so nothing is promoted just for being unreachable,
    and a leg with no calibrated chance at all ranks last on 0.

    Darts is the exception. No darts leg has a game state, strength, shrunk
    or exchange chance, so every darts leg scored 0: the 13 darts leads of
    22 Oct 2026 were logged at 0% and picked on sample size alone. Darts gets
    weekend.chance, the shrunk record its weekend picks already use. On the
    best darts leg per match the site has settled (52 legs) it said 65% and
    71% landed, so it errs cautious; see PROOF-2026-10-22.md.
    """
    g = l.get("gs")
    if g:
        return g["chance"]
    if sport == "darts":
        return weekend.chance(l)
    c = weekend.chance(l) if (l.get("pStrength") or l.get("pShrunk") or l.get("pExchange")) else None
    return c if c is not None else 0


def write_leads(rows, now) -> None:
    import json
    try:
        log = json.loads(LEAD_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log = {}
    for meta, leg, chance in rows:
        if not leg or meta["kickoff"] <= now:
            continue
        log[str(meta["id"])] = {
            "event_id": meta["id"], "fixture": f"{meta['home']} v {meta['away']}",
            "competition": meta.get("competition"), "sport": meta.get("sport"), "kickoff": meta["kickoff"],
            "selection": fmt_leg(leg), "chance": chance, "fair": leg.get("fair"),
            **{k: leg.get(k) for k in KEY if k != "event_id"}, "written": now}
    LEAD_LOG.write_text(json.dumps(log, indent=1), encoding="utf-8")


def results_block(now) -> str:
    import json
    try:
        log = json.loads(LEAD_LOG.read_text(encoding="utf-8"))
        bets = json.loads((ROOT / "best_bets.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    settled = {}
    for b in bets:
        for l in b.get("legs") or []:
            if l.get("result") in ("win", "lose"):
                settled[_leg_key(l)] = l["result"]
    recent = [r for r in log.values() if now - 36 * 3600 <= r["kickoff"] <= now - 2 * 3600]
    if not recent:
        return ""
    rows, won, done, expect = [], 0, 0, 0.0
    for r in sorted(recent, key=lambda r: r["kickoff"]):
        res = settled.get(_leg_key(r))
        mark = {"win": "&#10003;", "lose": "&#10007;"}.get(res, "&middot;")
        if res:
            done += 1
            won += res == "win"
            expect += r.get("chance") or 0
        rows.append(f"<tr><td><span class='mark {res or ''}'>{mark}</span> {html.escape(r['selection'])}"
                    f"<br><span class='sub'>{html.escape(r['fixture'])}</span></td>"
                    f"<td class='n'>{(r.get('chance') or 0) * 100:.0f}%</td></tr>")
    summary = (f"{won} of {done} landed; the page expected {expect:.1f}." if done
               else "Not settled yet.")
    return (f"<section class='results'><h2>Last night's leads</h2><p class='comp'>{summary}</p>"
            f"<table><thead><tr><th>Lead</th><th class='n'>Said</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></section>")


def build(hours: float | None) -> str:
    entries: list[tuple[dict, dict]] = []
    seen: set[tuple] = set()
    newest = 0.0
    for path in sorted((ROOT / "reports").glob("*.html")):
        if path.name.startswith("pick-"):
            continue
        newest = max(newest, path.stat().st_mtime)
        for entry, meta in make_index.read_entries(path):
            key = (meta["home"], meta["away"], meta["kickoff"])
            if key in seen:
                continue
            seen.add(key)
            entries.append((entry, meta))

    try:
        import context
        context.set_entries(entries)
    except Exception:
        pass
    now = time.time()
    horizon = now + hours * 3600 if hours else float("inf")
    window = sorted(
        [(e, m) for e, m in entries if now < m["kickoff"] <= horizon],
        key=lambda pair: pair[1]["kickoff"],
    )

    built = time.strftime("%a %d %b, %H:%M %Z", time.localtime(newest))
    span = f"the next {hours:g} hours" if hours else "everything still to come"

    if not window:
        body = results_block(now) + research_block(now) + (f"<p class='none'>Nothing kicks off in {span}. "
                f"The reports were built {built}.</p>")
        return PAGE.format(built=built, span=span, body=body,
                           stamp=time.strftime("%a %d %b, %H:%M %Z", time.localtime(now)))

    # ---------------------------------------------------------- the multi
    legs = []
    for entry, meta in window:
        legs.extend(legs_of(entry, meta))

    multi = "".join(
        acca_block(weekend.best_acca(legs, wanted=w, target=t), w, t)
        for w, t in ACCA_SHAPES
    )

    # ------------------------------------------------------ the same games
    blocks = []
    lead_log = []
    for entry, meta in window:
        kick = time.strftime("%H:%M", time.localtime(meta["kickoff"]))
        football = ((entry.get("fixture") or {}).get("sport") or "football") == "football"
        basketball = ((entry.get("fixture") or {}).get("sport") or "") == "basketball"
        builders = weekend.builders_for(entry, meta) or []
        best = max(builders, key=lambda b: b.get("evidence", 0)) if builders else None

        pool = sorted(
            [l for l in legs_of(entry, meta)
             if isinstance(l.get("fair"), (int, float))
             and l["fair"] >= MIN_PRICE],
            key=lambda l: (-weekend.sort_value(l), -(l.get("total") or 0)),
        )[:SINGLES_PER_FIXTURE * 4]
        gs = None
        try:
            import context
            gs = context.game_state(meta)
            for l in pool:
                l["gs"] = context.gs_adjust(l, entry, gs)
        except Exception:
            gs = None
        # The game state re-ranks the pool: a leg it lifts can climb into the
        # six, and one it cuts can fall out (tonight_chance, above).
        # One leg per player (value_cap.py): two legs on one player land
        # together, so a second is the same bet twice, not a second bet.
        sport = weekend.sport_of(entry)
        own = value_cap.cap_per_player(sorted(pool, key=lambda l: (-tonight_chance(l, sport) * (l.get("fair") or 1) ** 0.5,
                                                                   -(l.get("total") or 0))))[:SINGLES_PER_FIXTURE]
        lead_log.append(({**meta, "sport": sport},
                         own[0] if own else None, tonight_chance(own[0], sport) if own else None))

        singles = "".join(leg_row(l, entry) for l in own) or "<tr><td colspan='4'>nothing qualified</td></tr>"
        try:
            import playerlines
            plines = "".join(player_row(l) for l in playerlines.suggest(entry, meta))
        except Exception as exc:          # never cost the page its other sections
            plines = f"<tr><td colspan='4'>player lines unavailable ({html.escape(str(exc))})</td></tr>"
        plines = plines or "<tr><td colspan='4'>nothing qualified</td></tr>"
        blocks.append(
            f"<section><h2>{kick} &middot; {html.escape(meta['home'])} v "
            f"{html.escape(meta['away'])}</h2>"
            f"<p class='comp'>{html.escape(meta['competition'])}</p>"
            + (f"<h3>The case</h3>{case_block(entry, meta, own[0] if own else None, gs)}"
               if football else f"<h3>The case</h3>{lead_only(own[0] if own else None)}")
            + f"<h3>Same-game builder</h3>{builder_block(best)}"
            f"<h3>Best singles here</h3>"
            f"<table><thead><tr><th>Selection</th><th class='n'>Record</th>"
            f"<th class='n'>Fair</th><th class='n'>Need</th></tr></thead>"
            f"<tbody>{singles}</tbody></table>"
            f"<h3>Player lines</h3>"
            f"<p class='sub'>Each player's own line: the highest he has cleared in 7 of his "
            f"last 10, with his average 10% clear of it. Back at the fair price or longer.</p>"
            f"<table><thead><tr><th>Selection</th><th class='n'>Last 10</th>"
            f"<th class='n'>Chance</th><th class='n'>Fair</th></tr></thead>"
            f"<tbody>{plines}</tbody></table>"
            + (f"<h3>How the game will go</h3>{story_block(entry, meta, gs)}" if football
               else (f"<h3>How the game will go</h3>{nba_story_block(entry, meta)}" if basketball else ""))
            + "</section>"
        )

    try:
        write_leads(lead_log, now)
    except Exception:
        pass
    body = (results_block(now) + research_block(now)
            + f"<section><h2>Multi across the {len(window)} games</h2>{multi}</section>"
            + "".join(blocks))
    return PAGE.format(built=built, span=span, body=body,
                       stamp=time.strftime("%a %d %b, %H:%M %Z", time.localtime(now)))


PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tonight</title>
<style>
:root {{ --bg:#fcfcfb; --fg:#0b0b0b; --muted:#75736e; --line:rgba(11,11,11,.12); --accent:#d03b3b; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141413; --fg:#fff; --muted:#908e88; --line:rgba(255,255,255,.14); }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:20px 16px 60px; background:var(--bg); color:var(--fg);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  max-width:760px; margin-inline:auto; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
h2 {{ font-size:18px; margin:32px 0 2px; }}
h3 {{ font-size:14px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); margin:20px 0 6px; font-weight:600; }}
section {{ border-top:1px solid var(--line); padding-top:4px; }}
.comp, .sub {{ color:var(--muted); font-size:13px; }}
.stamp {{ color:var(--muted); font-size:13px; margin:0 0 8px; }}
.legs {{ margin:6px 0; padding-left:20px; }}
.legs li {{ margin:3px 0; }}
.price {{ font-size:14px; margin:6px 0 0; }}
.none {{ color:var(--muted); font-size:14px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; margin-top:4px; }}
th, td {{ text-align:left; padding:6px 4px; border-bottom:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase;
  letter-spacing:.04em; }}
.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.case {{ font-size:14px; }}
.call {{ margin:4px 0; }}
.argue {{ margin:8px 0; padding:8px 12px; border-left:3px solid var(--fg); }}
.facts {{ margin:6px 0 10px; padding-left:20px; }}
.facts li {{ margin:2px 0; }}
.sides {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:620px) {{ .sides {{ grid-template-columns:1fr; }} }}
.side h4 {{ margin:8px 0 2px; font-size:14px; }}
.side .line {{ margin:4px 0; }}
table.form td {{ padding:3px 4px; font-size:13px; }}
.res {{ display:inline-block; min-width:20px; text-align:center; border-radius:4px;
  font-weight:700; font-size:12px; color:#fff; }}
.res.W {{ background:#2e8b57; }} .res.D {{ background:#8a8a8a; }} .res.L {{ background:#c0392b; }}
.allow {{ font-size:13px; font-weight:600; }}
.gs {{ font-size:13px; }}
.gsbox {{ margin:10px 0; padding:8px 12px; border:1px solid var(--line); border-radius:6px; }}
.gsarg {{ border-left-color:var(--accent); }}
.mark {{ display:inline-block; width:18px; font-weight:700; }}
.story {{ font-size:14px; }}
.story .line {{ margin:8px 0; }}
.why {{ padding-left:20px; }}
.why li {{ margin:6px 0; }}
.mark.win {{ color:#2e8b57; }} .mark.lose {{ color:#c0392b; }}
.warn {{ border-left:3px solid var(--accent); padding:10px 14px; margin:16px 0;
  font-size:13.5px; color:var(--muted); }}
</style></head><body>
<h1>Tonight</h1>
<p class="stamp">{span} &middot; page made {stamp} &middot; numbers from reports built {built}</p>
<div class="warn">
Fair and Need are what the evidence implies, not what anyone is offering.
For a football team leg that evidence includes team strength (Elo as of
kick-off, shown under the selection) as well as the record; a player leg's
record is pulled towards a coin flip by as much as past picks show it should be.
<b>Need</b> is the price the evidence supports once the sample size is paid for,
and it is the one to bet off. Neither includes the bookmaker's margin, which
runs 5&ndash;8% a market and compounds with every leg you add.
</div>
{body}
<div class="warn">
A multiple is worse than its legs at a bookmaker's price. The margin compounds
with every leg, and the shop sells accumulators because they are the most
profitable thing on the counter. Legs in the same game can move together, so
the same-game builders above are priced from how often their legs landed
together, not by multiplying. Legs in different games do not move together:
in the site's own published legs the correlation between them is effectively
nil, and replayed over past matches, multiplied prices landed about as often
as they said (1.01 times). So multiplying is right for the cross-game prices,
and they are not optimistic on that account. Any error in them comes from the
legs themselves.
</div>
</body></html>
"""


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=6,
                    help="how far ahead to look (default 6)")
    ap.add_argument("--all", action="store_true",
                    help="every upcoming fixture, no time limit")
    args = ap.parse_args(argv)

    page = build(None if args.all else args.hours)
    out = ROOT / "tonight.html"
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({len(page)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
