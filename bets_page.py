"""
Render the best bets summary: numbers first, everything else a click away.

    python bets_page.py

Three tabs. Summary: the handful of numbers that say whether the picks work,
two or three wins worth remembering, and the best open picks to do next.
Challenge: the rolling 1.80 to 2.20 log, every run and step. Detail: the
calibration and market tables for when something needs investigating.
"""
from __future__ import annotations

import html
import json
import time
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


def money(x, dp=0) -> str:
    return f"{'-' if x < 0 else '+' if x > 0 else ''}&pound;{abs(x):.{dp}f}"


def pct(x) -> str:
    return "&ndash;" if x is None else f"{x:.0%}"


def leg_txt(l: dict) -> str:
    """One leg in plain words, from either a site pick or a tracked bet."""
    who = l.get("player") or l.get("team")
    stat = (l.get("stat") or "").lower()
    if l.get("alt") and l.get("threshold"):
        mk = f'{int(l["threshold"])}+ {stat}'
    elif l.get("over") is False:
        mk = f'under {l["line"]:g} {stat}'
    else:
        line = l["line"]
        mk = f'{int(line + 0.5)}+ {stat}' if float(line) % 1 else f'{line:g}+ {stat}'
    # The period matters as much as the line: "2+ corners" and "2+ first-half
    # corners" are priced 1.01 and 1.40. Leaving it off sent a pick to the
    # coupon as the wrong market.
    half = {"1ST": " (1st half)", "2ND": " (2nd half)"}.get(l.get("period") or "ALL", "")
    mk += half
    rec = ""
    if l.get("total"):
        rec = f'{l["hits"]}/{l["total"]}'
    elif l.get("model_n"):
        rec = f'{l["model_k"]}/{l["model_n"]}'
    got = "" if l.get("value") is None else f' &middot; got {l["value"]:g}'
    return (f'<b>{esc(who)}</b> {esc(mk)}'
            f'<span class="muted"> &middot; {esc(l.get("fixture", ""))}'
            + (f' &middot; {rec}' if rec else "") + f'{got}</span>')


# ------------------------------------------------------------------ summary

def notable_wins(items: list[dict], limit: int = 3) -> list[dict]:
    """The longest-priced site picks that landed: the ones worth remembering."""
    won = [i for i in items if i["result"] == "win" and i.get("fair")]
    # Prefer multi-leg wins, then price. A 1.3 banker landing is not a story.
    won.sort(key=lambda i: (len(i["legs"]) > 1, i["fair"]), reverse=True)
    seen, out = set(), []
    for i in won:
        key = tuple((l.get("player") or l.get("team"), l["stat"], l["line"]) for l in i["legs"])
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
        if len(out) == limit:
            break
    return out


def best_to_do(items: list[dict], limit: int = 5) -> list[dict]:
    """Open site picks for the next two days, headline picks first, soonest first."""
    now = time.time()
    soon = [i for i in items if i["result"] is None
            and all(now < l["kickoff"] < now + 48 * 3600 for l in i["legs"])]
    rank = {"Pick: evens double": 0, "Pick: single": 1, "Pick: banker": 2,
            "Pick: builder": 3, "Pick: acca": 4, "Pick: parlay": 5}
    seen, out = set(), []
    soon.sort(key=lambda i: (rank.get(i["category"], 9), min(l["kickoff"] for l in i["legs"])))
    for i in soon:
        key = tuple((l.get("player") or l.get("team"), l["stat"], l["line"]) for l in i["legs"])
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
        if len(out) == limit:
            break
    return out


def pick_card(i: dict, badge: str) -> str:
    cat = i["category"].replace("Pick: ", "").replace("Fixture single", "single")
    price = f'fair {i["fair"]:.2f}' if i.get("fair") else ""
    ko = when(min(l["kickoff"] for l in i["legs"]))
    legs = "".join(f"<li>{leg_txt(l)}</li>" for l in i["legs"])
    return (f'<div class="card"><div class="head"><span class="pill {badge}">{esc(cat)}</span>'
            f'<span class="muted">{esc(price)}</span><span class="muted right">{esc(ko)}</span></div>'
            f'<ul>{legs}</ul></div>')


def what_works(s: dict) -> str:
    rows = [r for r in s["by_market"] if r["legs"] >= 5]
    if not rows:
        return ""
    best = max(rows, key=lambda r: r["gap"])
    worst = min(rows, key=lambda r: r["gap"])
    out = [f'<li><b>Best market:</b> {esc(best["group"])}, {best["won"]}/{best["legs"]} '
           f'({pct(best["hit"])} vs {pct(best["said"])} expected)</li>']
    if worst is not best and worst["gap"] < -0.05:
        out.append(f'<li><b>Leaking:</b> {esc(worst["group"])}, {worst["won"]}/{worst["legs"]} '
                   f'({pct(worst["hit"])} vs {pct(worst["said"])} expected)</li>')
    return "<ul class='plain'>" + "".join(out) + "</ul>"


def summary_tab(s: dict, items: list[dict], ch: dict) -> str:
    hit = s["legs_won"] / s["legs_settled"] if s["legs_settled"] else None
    tiles = f"""<div class="stats">
<div class="stat"><span>Legs landed</span><b>{pct(hit)}</b><small>{s["legs_won"]}/{s["legs_settled"]}</small></div>
<div class="stat"><span>Site said</span><b>{pct(s["said"])}</b><small>{"honest" if hit is not None and s["said"] and abs(hit - s["said"]) <= .05 else "over-confident" if hit is not None and s["said"] and hit < s["said"] else "under-selling" if hit is not None else ""}</small></div>
<div class="stat"><span>Bets landed</span><b>{s["bets_won"]}/{s["bets_settled"]}</b><small>{pct(s["bets_won"] / s["bets_settled"]) if s["bets_settled"] else ""}</small></div>
<div class="stat"><span>Challenge</span><b class="{"pos" if ch["total"] >= 0 else "neg"}">{money(ch["total"])}</b><small>{ch["label"]}</small></div>
</div>"""
    wins = "".join(pick_card(i, "win") for i in notable_wins(items)) or \
        '<p class="muted">No wins settled yet.</p>'
    todo = "".join(pick_card(i, "open") for i in best_to_do(items)) or \
        '<p class="muted">Nothing in the next 48 hours.</p>'
    return f"""{tiles}{what_works(s)}
<h2>Best ones to do</h2>{todo}
<h2>Wins worth noting</h2>{wins}"""


# ---------------------------------------------------------------- challenge

def challenge_data() -> dict:
    try:
        import challenge
    except Exception:
        return {"runs": [], "total": 0.0, "label": "not started", "target": None}
    state = challenge.load()
    bets = bettrack.load()
    walks = [(r, challenge.walk(r, bets)) for r in state["runs"]]
    total = sum(w["profit"] for _, w in walks)
    label = "not started"
    if walks:
        r, w = walks[-1]
        label = (f'run {r["id"]}, step {w["next_step"]}' if w["alive"] else
                 f'run {r["id"]} cashed' if w.get("cashed") else f'run {r["id"]} bust')
    return {"runs": walks, "total": total, "label": label, "target": state.get("target")}


def challenge_tab(ch: dict) -> str:
    if not ch["runs"]:
        return '<p class="muted">No challenge run yet. <code>python challenge.py start --stake 10</code></p>'
    r, w = ch["runs"][-1]
    wins = sum(1 for x in w["steps"] if x["result"] == "win")
    best = max(sum(1 for x in ww["steps"] if x["result"] == "win") for _, ww in ch["runs"])
    target = ch["target"]
    tiles = f"""<div class="stats">
<div class="stat"><span>Pot</span><b>&pound;{w["pot"]:.2f}</b><small>{esc(ch["label"])}</small></div>
<div class="stat"><span>Steps won</span><b>{wins}{f"/{r['cashout']}" if r.get("cashout") else ""}</b><small>this run</small></div>
<div class="stat"><span>Total</span><b class="{"pos" if ch["total"] >= 0 else "neg"}">{money(ch["total"], 2)}</b><small>{f"of &pound;{target:.0f} target" if target else "all runs"}</small></div>
<div class="stat"><span>Best run</span><b>{best}</b><small>steps won</small></div>
</div>"""
    rows = ""
    for run, ww in reversed(ch["runs"]):
        state = "alive" if ww["alive"] else "cashed" if ww.get("cashed") else "bust"
        cls = {"alive": "open", "cashed": "win", "bust": "lose"}[state]
        for x in ww["steps"]:
            legs = " + ".join(leg_txt(l) for l in x["legs"])
            price = f'{x["price"]:.2f}' if x["price"] else "?"
            rows += (f'<tr><td>{run["id"]}.{x["step"]}</td><td>&pound;{x["stake"]:.2f}</td>'
                     f'<td>{price}</td><td><span class="pill {x["result"]}">{esc(x["result"])}</span></td>'
                     f'<td>{legs}</td></tr>')
        rows += (f'<tr class="sep"><td colspan="5"><span class="pill {cls}">run {run["id"]} {state}</span>'
                 f'<span class="muted"> started {esc(run["started"][:10])}, &pound;{run["stake"]:.0f}'
                 + (f', cash out after {run["cashout"]} wins' if run.get("cashout") else "")
                 + (f', {money(ww["profit"], 2)}' if not ww["alive"] else "") + '</span></td></tr>')
    return f"""{tiles}
<p class="muted">One bet at 1.80 to 2.20 per step, the whole return rolled into the next.</p>
<table class="log"><tr><th>Step</th><th>Stake</th><th>Price</th><th></th><th>Bet</th></tr>{rows}</table>"""


# ------------------------------------------------------------------- detail

def _table(rows, first):
    if not rows:
        return '<p class="muted">Nothing settled yet.</p>'
    body = "".join(
        f'<tr><td>{esc(r["group"])}</td><td>{r["won"]}/{r["legs"]}</td><td>{pct(r["said"])}</td>'
        f'<td><b class="{"neg" if r["gap"] <= -0.1 else "pos" if r["gap"] >= 0.05 else ""}">{pct(r["hit"])}</b></td></tr>'
        for r in rows)
    return (f'<table><tr><th>{first}</th><th>Landed</th><th>Said</th><th>Hit</th></tr>{body}</table>')


def detail_tab(s: dict, cal: dict) -> str:
    calrows = "".join(f'<tr><td>{esc(x["raw"])}</td><td>{x["legs"]}</td><td>{x["said"]:.0%}</td>'
                      f'<td><b>{x["happened"]:.0%}</b></td></tr>' for x in cal["bands"]) or \
        '<tr><td colspan="4" class="muted">Nothing settled yet.</td></tr>'
    seen, uniq = set(), []
    for l in s["misses"]:
        key = (l.get("player") or l.get("team"), l["stat"], l["line"], l["fixture"])
        if key not in seen:
            seen.add(key)
            uniq.append(l)
    misses = "".join(f'<li><span class="pill lose">{esc(l["_how"])}</span> {leg_txt(l)}</li>'
                     for l in uniq[:8]) or '<li class="muted">No misses yet.</li>'
    findings = "".join(f"<li>{esc(n)}</li>" for n in s["findings"])
    return f"""
<h2>Is the hit rate honest?</h2>
<table><tr><th>Record said</th><th>Legs</th><th>Average</th><th>Hit</th></tr>{calrows}</table>
<h2>By market</h2>{_table(s["by_market"], "Market")}
<h2>By bet type</h2>{_table(s["by_category"], "Bet")}
<h2>By sport</h2>{_table(s["by_sport"], "Sport")}
<h2>Recent misses</h2><ul class="plain">{misses}</ul>
<details><summary>Notes</summary><ul>{findings}</ul></details>"""


# --------------------------------------------------------------------- page

CSS = """
:root{--bg:#fbfbfa;--fg:#18181b;--muted:#71717a;--line:#e7e7e4;--card:#fff;--win:#15803d;--lose:#b91c1c;--open:#a16207;--accent:#18181b}
@media (prefers-color-scheme:dark){:root{--bg:#0f0f10;--fg:#ececec;--muted:#8b8b93;--line:#26262a;--card:#17171a;--win:#4ade80;--lose:#f87171;--open:#facc15;--accent:#ececec}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:20px 16px 48px}a{color:inherit}
header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:8px 0 16px}
h1{font-size:22px;margin:0}h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:28px 0 10px;font-weight:600}
.muted{color:var(--muted)}.right{margin-left:auto}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:18px}
.tabs button{background:none;border:0;border-bottom:2px solid transparent;padding:8px 12px;font:inherit;color:var(--muted);cursor:pointer}
.tabs button[aria-selected=true]{color:var(--fg);border-color:var(--accent);font-weight:600}
.panel[hidden]{display:none}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media (max-width:560px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.stat span{display:block;font-size:12px;color:var(--muted)}.stat b{display:block;font-size:26px;line-height:1.2;font-variant-numeric:tabular-nums}
.stat small{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:8px 0}
.head{display:flex;align-items:center;gap:8px;font-size:13px}
.card ul,ul.plain{margin:6px 0 0;padding-left:0;list-style:none}.card li,ul.plain li{margin:3px 0}
.pill{display:inline-block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.03em;padding:1px 8px;border-radius:99px;border:1px solid currentColor}
.win{color:var(--win)}.lose{color:var(--lose)}.open{color:var(--open)}.void{color:var(--muted)}
.pos{color:var(--win)}.neg{color:var(--lose)}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}tr.sep td{border-bottom:2px solid var(--line);padding-top:4px}
table.log td:first-child{font-variant-numeric:tabular-nums;color:var(--muted)}
details{margin-top:20px}summary{cursor:pointer;color:var(--muted)}code{font-size:13px}
.tablewrap{overflow-x:auto}
"""

JS = """
const tabs=[...document.querySelectorAll('.tabs button')];
function show(id){tabs.forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===id));
document.querySelectorAll('.panel').forEach(p=>p.hidden=p.id!==id);
try{history.replaceState(null,'','#'+id)}catch(e){}}
tabs.forEach(b=>b.addEventListener('click',()=>show(b.dataset.tab)));
show(['summary','challenge','detail'].includes(location.hash.slice(1))?location.hash.slice(1):'summary');
"""


def main() -> None:
    import besttrack
    cal = bettrack.fit_and_write()
    s = besttrack.best_bets_summary()
    items = besttrack.load()
    ch = challenge_data()
    updated = datetime.now().astimezone().strftime("%a %d %b %H:%M")
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Best bets</title><style>{CSS}</style></head><body><div class="wrap">
<a href="index.html" class="muted">&larr; All fixtures</a>
<header><h1>Best bets</h1><span class="muted">updated {esc(updated)}</span></header>
<nav class="tabs" role="tablist">
<button data-tab="summary" role="tab">Summary</button>
<button data-tab="challenge" role="tab">Challenge</button>
<button data-tab="detail" role="tab">Detail</button>
</nav>
<section class="panel" id="summary">{summary_tab(s, items, ch)}</section>
<section class="panel" id="challenge" hidden><div class="tablewrap">{challenge_tab(ch)}</div></section>
<section class="panel" id="detail" hidden><div class="tablewrap">{detail_tab(s, cal)}</div></section>
</div><script>{JS}</script></body></html>"""
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT.name}: summary, challenge ({ch['label']}), detail")


if __name__ == "__main__":
    main()
