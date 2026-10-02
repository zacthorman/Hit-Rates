"""
Render bets.json into bets.html: every tracked best bet, open and settled,
with the calibration table from bettrack.py. Published beside index.html.

    python bets_page.py
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import bettrack

HERE = Path(__file__).parent
OUT = HERE / "best-bets-summary.html"


def esc(x) -> str:
    return html.escape(str(x))


def when(ts) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%a %d %b %H:%M")


def leg_html(l: dict) -> str:
    res = l.get("result")
    badge = {"win": "win", "lose": "lose", "void": "void"}.get(res, "open")
    got = "" if l.get("value") is None else f" &middot; got <b>{l['value']:g}</b>"
    return (f'<li><span class="pill {badge}">{esc(res or "open")}</span> '
            f'<b>{esc(l["player"])}</b> {esc(l["stat"])} <b>{l["line"]:g}+</b>'
            f'<span class="muted"> &middot; {esc(l["fixture"])} &middot; {when(l["kickoff"])} '
            f'&middot; site {l["model_k"]}/{l["model_n"]}, treated as {l["model_p"]:.0%}</span>{got}</li>')


def bet_html(b: dict) -> str:
    res = b.get("result") or "open"
    tags = [b["kind"]]
    if not b.get("placed"):
        tags.append("suggested")
    if b.get("backfilled"):
        tags.append("logged after kick-off")
    price = f' @ {b["price"]:.2f}' if b.get("price") else ""
    profit = "" if b.get("profit") is None else f' <span class="{"pos" if b["profit"] >= 0 else "neg"}">{b["profit"]:+.2f}u</span>'
    legs = "".join(leg_html(l) for l in b["legs"])
    return (f'<div class="card"><div class="head"><span class="pill {res}">{esc(res)}</span> '
            f'<b>{esc(b["group"])}</b>{price}{profit} '
            f'<span class="muted">{esc(" · ".join(tags))}</span></div><ul>{legs}</ul></div>')


def _pct(x):
    return "&mdash;" if x is None else f"{x:.0%}"


def _table(rows, first="Group"):
    if not rows:
        return '<p class="muted">Nothing settled yet.</p>'
    body = "".join(
        f'<tr><td>{esc(r["group"])}</td><td>{r["won"]}/{r["legs"]}</td><td>{_pct(r["said"])}</td>'
        f'<td><b class="{"neg" if r["gap"] <= -0.1 else "pos" if r["gap"] >= 0.05 else ""}">{_pct(r["hit"])}</b></td>'
        f'<td class="muted">{"likely real" if r["surprise"] < 0.1 and r["gap"] < 0 else ""}</td></tr>'
        for r in rows)
    return (f'<table><tr><th>{first}</th><th>Landed</th><th>Site said</th><th>Actually hit</th><th></th></tr>'
            f'{body}</table>')


def site_section() -> str:
    import besttrack
    s = besttrack.best_bets_summary()
    items = besttrack.load()
    open_items = sorted([i for i in items if i["result"] is None],
                        key=lambda i: min(l["kickoff"] for l in i["legs"]))
    findings = "".join(f"<li>{esc(n)}</li>" for n in s["findings"])
    bybet = "".join(
        f'<tr><td>{esc(r["group"])}</td><td>{r["won"]}/{r["bets"]}</td><td>{_pct(r["said"])}</td>'
        f'<td><b>{_pct(r["won"]/r["bets"] if r["bets"] else None)}</b></td></tr>' for r in s["by_bet"]) \
        or '<tr><td colspan="4" class="muted">Nothing settled yet.</td></tr>'
    misses = "".join(
        f'<li><span class="pill lose">{esc(l["_how"])}</span> <b>{esc(l["player"] or l["team"])}</b> '
        f'{"over" if l["over"] else "under"} {l["line"]:g} {esc(l["stat"])} &middot; got <b>{l["value"]:g}</b>'
        f'<span class="muted"> &middot; {esc(l["fixture"])} &middot; site {l["hits"]}/{l["total"]}</span></li>'
        for l in s["misses"]) or '<li class="muted">No misses yet.</li>'

    def leg_txt(l):
        who = l["player"] or l["team"]
        mk = f'{int(l["threshold"])}+ {l["stat"].lower()}' if l["alt"] and l["threshold"] else \
             f'{"over" if l["over"] else "under"} {l["line"]:g} {l["stat"].lower()}'
        return f'{esc(who)} {esc(mk)} <span class="muted">({l["hits"]}/{l["total"]}, {esc(l["fixture"])})</span>'
    opens = "".join(
        f'<div class="card"><div class="head"><span class="pill open">open</span> <b>{esc(i["category"])}</b>'
        + (f' &middot; fair {i["fair"]:.2f}' if i.get("fair") else "")
        + f' <span class="muted">{when(min(l["kickoff"] for l in i["legs"]))}</span></div><ul>'
        + "".join(f"<li>{leg_txt(l)}</li>" for l in i["legs"]) + "</ul></div>"
        for i in open_items[:40]) or '<p class="muted">Nothing open.</p>'
    legs_line = (f'{s["legs_won"]}/{s["legs_settled"]}' if s["legs_settled"] else "0/0")
    return f"""
<p class="muted">Every best bet the site publishes is recorded automatically before kick-off (picks of the week,
the acca, the same-game builder and parlay, and each fixture's top singles), then settled from the result.
Nothing is picked by hand, so the record cannot be flattered.</p>
<div class="stats">
<div class="stat"><span class="muted">Open best bets</span><b>{s["open"]}</b></div>
<div class="stat"><span class="muted">Legs landed</span><b>{legs_line}</b></div>
<div class="stat"><span class="muted">Site said</span><b>{_pct(s["said"])}</b></div>
<div class="stat"><span class="muted">Bets landed</span><b>{s["bets_won"]}/{s["bets_settled"]}</b></div>
</div>
<h2>What hits, what doesn't, and why</h2><ul>{findings}</ul>
<h2>By bet type</h2>
<table><tr><th>Bet</th><th>Landed</th><th>Priced to land</th><th>Actually landed</th></tr>{bybet}</table>
<h2>By market</h2>{_table(s["by_market"], "Market")}
<h2>By side</h2>{_table(s["by_side"], "Side")}
<h2>By how strong the record looked</h2>{_table(s["by_band"], "Record")}
<h2>By sport</h2>{_table(s["by_sport"], "Sport")}
<h2>Recent misses</h2><ul>{misses}</ul>
<h2>Open best bets</h2>{opens}
"""


def main() -> None:
    cal = bettrack.fit_and_write()
    bets = bettrack.load()
    open_ = [b for b in bets if b["result"] is None]
    done = [b for b in bets if b["result"] is not None]
    open_.sort(key=lambda b: min((l["kickoff"] or 0) for l in b["legs"]))
    done.sort(key=lambda b: max((l["kickoff"] or 0) for l in b["legs"]), reverse=True)
    legs = bettrack._legs()
    won = sum(l["result"] == "win" for l in legs)
    placed = [b for b in done if b.get("placed") and not b.get("backfilled") and b.get("profit") is not None]
    pl = sum(b["profit"] for b in placed)
    rows = "".join(f'<tr><td>{esc(x["raw"])}</td><td>{x["legs"]}</td><td>{x["said"]:.0%}</td>'
                   f'<td><b>{x["happened"]:.0%}</b></td></tr>' for x in cal["bands"]) \
        or '<tr><td colspan="4" class="muted">Nothing settled yet.</td></tr>'
    prov = ("Provisional: fewer than 30 settled legs, so prices still use the default pull "
            f"of {bettrack.DEFAULT_PRIOR:g} phantom hits and misses.") if cal["provisional"] else \
           f"Learned: records are pulled towards 50% by {cal['prior']:g} phantom hits and misses."
    site = site_section()
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Best bets summary</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#6b6b6b;--border:#e3e3e3;--raised:#f6f6f6;--win:#1a7f37;--lose:#c0392b;--open:#8a6d00}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--muted:#9a9a9a;--border:#2a2a2a;--raised:#1a1a1a;--win:#3fb950;--lose:#f0655a;--open:#d4a72c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif}}
.wrap{{max-width:900px;margin:0 auto;padding:20px 16px 40px}} a{{color:inherit}}
h1{{margin:6px 0 4px}} h2{{margin:28px 0 8px;font-size:18px}} .muted{{color:var(--muted)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:14px 0}}
.stat{{background:var(--raised);border:1px solid var(--border);border-radius:10px;padding:10px 12px}}
.stat b{{display:block;font-size:22px}} table{{border-collapse:collapse;width:100%}}
td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}}
.card{{border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin:10px 0;background:var(--raised)}}
.card ul{{margin:6px 0 0;padding-left:18px}} .card li{{margin:3px 0}}
.pill{{display:inline-block;font-size:11px;font-weight:600;text-transform:uppercase;padding:1px 7px;border-radius:99px;border:1px solid currentColor}}
.win{{color:var(--win)}} .lose{{color:var(--lose)}} .open{{color:var(--open)}} .void{{color:var(--muted)}}
.pos{{color:var(--win);font-weight:600}} .neg{{color:var(--lose);font-weight:600}}
</style></head><body><div class="wrap">
<a href="index.html" class="muted">&larr; All fixtures</a>
<h1>Best bets summary</h1>
{site}
<h2 style="margin-top:40px">Your tracked bets</h2>
<p class="muted">Every best bet is logged with the hit rate the site showed at the time, then settled from the box score.
Bets logged after kick-off, and suggestions that were not placed, teach the calibration but stay out of the profit figure.
Updated {datetime.now().astimezone().strftime("%a %d %b %H:%M")}.</p>
<div class="stats">
<div class="stat"><span class="muted">Open bets</span><b>{len(open_)}</b></div>
<div class="stat"><span class="muted">Settled legs</span><b>{len(legs)}</b></div>
<div class="stat"><span class="muted">Legs landed</span><b>{won}/{len(legs)}</b></div>
<div class="stat"><span class="muted">Profit, placed bets</span><b class="{"pos" if pl >= 0 else "neg"}">{pl:+.2f}u</b></div>
</div>
<h2>Is the site's hit rate honest?</h2>
<p class="muted">{esc(prov)}</p>
<table><tr><th>Site said</th><th>Legs</th><th>Average said</th><th>Actually hit</th></tr>{rows}</table>
<h2>Open</h2>{"".join(bet_html(b) for b in open_) or '<p class="muted">Nothing open.</p>'}
<h2>Settled</h2>{"".join(bet_html(b) for b in done) or '<p class="muted">Nothing settled yet.</p>'}
</div></body></html>"""
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT.name}: {len(open_)} open, {len(done)} settled")


if __name__ == "__main__":
    main()
