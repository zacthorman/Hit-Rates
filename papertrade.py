#!/usr/bin/env python3
"""
A paper bankroll: start with £1,000 and let the model bet, on lines it priced
before kick-off at prices that were really on offer, in kick-off order.

    python papertrade.py            # every strategy below, on everything settled so far

Sources (the only records that hold a price you could have taken):
  pplog/YYYY-MM.jsonl   Paddy Power player lines, the model's chance and the
                        Paddy Power price at the last snapshot before kick-off
  exchange_log.json     Betfair lines (team and match goals, both-to-score, ...),
                        the model's chance and the back price, less 2% commission
Rules: singles only; a bet when chance x price clears the strategy's edge; stake
a fraction of the Kelly stake on the bank at the time, capped; voids returned.
Nothing here is fitted on the results it is scored on: the chances are the
ones logged before kick-off.
"""
from __future__ import annotations

import glob
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).parent
START = 1000.0
COMMISSION = 0.02


def candidates():
    out = []
    for f in glob.glob(str(ROOT / "pplog" / "2*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            s = r.get("last") or {}
            if r.get("result") not in ("win", "lose") or not s.get("price") or s.get("chance") is None:
                continue
            out.append({"t": r["kickoff"], "src": "Paddy Power player", "sport": r.get("sport"),
                        "kind": f"{r['stat']}", "p": s["chance"], "price": s["price"],
                        "fmodel": s.get("source") == "fmodel", "won": r["result"] == "win",
                        "what": f"{r['player']} {r['label']} {r['stat']} ({r['fixture']})"})
    try:
        L = json.loads((ROOT / "exchange_log.json").read_text())
        for r in (L.values() if isinstance(L, dict) else L):
            s = r.get("last") or {}
            back = s.get("back")
            p = s.get("blend") if s.get("blend") is not None else s.get("model")
            if r.get("result") not in ("win", "lose") or not back or p is None:
                continue
            out.append({"t": r["kickoff"], "src": "Betfair", "sport": r.get("sport"), "kind": r["stat"],
                        "p": p, "price": 1 + (back - 1) * (1 - COMMISSION), "fmodel": True,
                        "won": r["result"] == "win",
                        "what": f"{r.get('team') or ''} {r['stat']} {'over' if r.get('over') else 'under'} {r.get('line')} ({r['fixture']})"})
    except (OSError, ValueError):
        pass
    return sorted(out, key=lambda c: c["t"])


def run(cands, edge=0.05, kelly=0.25, cap=0.02, only=None, max_price=10.0, flat=None):
    bank, peak, low_dd, n, won, staked = START, START, 0.0, 0, 0, 0.0
    by = {}
    for c in cands:
        if only and not only(c):
            continue
        ev = c["p"] * c["price"] - 1
        if ev < edge or c["price"] > max_price:
            continue
        f = flat if flat else kelly * ev / (c["price"] - 1)
        stake = round(min(f, cap) * bank, 2)
        if stake < 0.1:
            continue
        pnl = stake * (c["price"] - 1) if c["won"] else -stake
        bank += pnl
        n += 1
        won += c["won"]
        staked += stake
        peak = max(peak, bank)
        low_dd = max(low_dd, 1 - bank / peak)
        k = by.setdefault(f"{c['src']}: {c['kind']}", [0, 0.0, 0.0])
        k[0] += 1; k[1] += stake; k[2] += pnl
    return {"bank": bank, "bets": n, "won": won, "staked": staked, "roi": (bank - START) / staked if staked else 0,
            "max_drawdown": low_dd, "by": by}


# ---------------------------------------------------------------- site picks
# The bets the site actually put forward (best_bets.json), matched to the
# Paddy Power price logged for the same line (pplog). One row per line, the
# first time the site picked it. This is the record that answers "are the
# picks profitable", as opposed to "is every line with an edge profitable".

def _nm(x):
    import re
    import unicodedata
    x = unicodedata.normalize("NFKD", str(x or "").lower())
    return re.sub(r"[^a-z]", "", "".join(c for c in x if not unicodedata.combining(c)))


def site_picks():
    pp = {}
    for f in glob.glob(str(ROOT / "pplog" / "2*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            s = r.get("last") or {}
            if not s.get("price") or r.get("player") is None:
                continue
            pp[(r["event_id"], _nm(r["player"]), str(r["stat"]).lower(), float(r["line"]), bool(r["over"]))] = r
    try:
        bb = json.loads((ROOT / "best_bets.json").read_text())
    except (OSError, ValueError):
        return []
    out, seen = [], set()
    for b in sorted(bb, key=lambda b: b.get("snapshot_at") or 0):
        for leg in b.get("legs") or []:
            if not leg.get("player") or leg.get("line") is None:
                continue
            k = (leg["event_id"], _nm(leg["player"]), str(leg["stat"]).lower(), float(leg["line"]), bool(leg.get("over", True)))
            r = pp.get(k)
            if not r or k in seen:
                continue
            seen.add(k)
            out.append({"t": r["kickoff"], "category": b.get("category") or "", "sport": r.get("sport"),
                        "what": f"{r['player']} {r['label']} {r['stat'].lower()} ({r['fixture']})",
                        "p": leg.get("chance") or 0.0, "price": r["last"]["price"],
                        "result": r.get("result")})
    return sorted(out, key=lambda c: c["t"])


def picks_summary(picks, stake_pct=0.01):
    done = [c for c in picks if c["result"] in ("win", "lose")]
    bank, staked, rows = START, 0.0, []
    for c in done:
        st = round(bank * stake_pct, 2)
        pnl = st * (c["price"] - 1) if c["result"] == "win" else -st
        bank += pnl
        staked += st
    n = len(done)
    won = sum(c["result"] == "win" for c in done)
    flat = sum((c["price"] - 1) if c["result"] == "win" else -1 for c in done)
    by = {}
    for c in done:
        g = by.setdefault(f"{c['sport']}: {c['category']}", [0, 0, 0.0, 0.0])
        g[0] += 1; g[1] += c["result"] == "win"; g[2] += (c["price"] - 1) if c["result"] == "win" else -1; g[3] += c["p"]
    return {"n": n, "won": won, "flat_roi": flat / n if n else 0.0, "bank": bank, "pending": len(picks) - n,
            "by": by, "said": sum(c["p"] for c in done) / n if n else 0.0}


def _bands(picks) -> str:
    """Where it goes wrong: the same picks split by price and by claimed edge."""
    done = [c for c in picks if c["result"] in ("win", "lose")]
    if not done:
        return ""
    def table(title, key, cuts):
        g = {}
        for c in done:
            v = key(c)
            if v is None:
                continue
            lab = next((f"{a:g} to {b:g}" if b < 99 else f"{a:g}+" for a, b in cuts if a <= v < b), None)
            if lab is None:
                continue
            x = g.setdefault(lab, [0, 0, 0.0, 0.0, cuts.index(next(ab for ab in cuts if ab[0] <= v < ab[1]))])
            x[0] += 1; x[1] += c["result"] == "win"; x[2] += (c["price"] - 1) if c["result"] == "win" else -1; x[3] += c["p"]
        rows = "".join(f"<tr><td>{k}</td><td class=n>{v[0]}</td><td class=n>{v[1] / v[0] * 100:.0f}%</td>"
                       f"<td class=n>{v[3] / v[0] * 100:.0f}%</td><td class=n>{v[2] / v[0] * 100:+.1f}%</td></tr>"
                       for k, v in sorted(g.items(), key=lambda kv: kv[1][4]))
        return (f"<h2>{title}</h2><table><thead><tr><th></th><th class=n>Bets</th><th class=n>Won</th>"
                f"<th class=n>Site said</th><th class=n>Return</th></tr></thead><tbody>{rows}</tbody></table>")
    return (table("By price", lambda c: c["price"], [(1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 99)])
            + table("By the edge the site claimed", lambda c: (c["p"] * c["price"] - 1) * 100 if c["p"] > 0 else None,
                    [(-99, 0), (0, 5), (5, 10), (10, 20), (20, 999)])
            + "<p class='sub'>Where it goes wrong: a row where Won sits well under Site said is where the "
              "model is overconfident. If the bigger claimed edges do not return more, staking bigger on them "
              "would only lose faster.</p>")


def _sharp() -> str:
    try:
        import sharp
        return sharp.record_html()
    except Exception:
        return ""


def page() -> Path:
    import html
    e = html.escape
    picks = site_picks()
    s = picks_summary(picks)
    rows = "".join(
        f"<tr><td>{e(k)}</td><td class=n>{v[0]}</td><td class=n>{v[1] / v[0] * 100:.0f}%</td>"
        f"<td class=n>{v[3] / v[0] * 100:.0f}%</td><td class=n>{v[2] / v[0] * 100:+.1f}%</td></tr>"
        for k, v in sorted(s["by"].items(), key=lambda kv: -kv[1][0]))
    recent = "".join(
        f"<tr><td>{time.strftime('%d %b', time.localtime(c['t']))}</td><td>{e(c['what'])}</td>"
        f"<td class=n>{c['price']:.2f}</td><td class=n>{c['p'] * 100:.0f}%</td>"
        f"<td class=n>{'&#10003;' if c['result'] == 'win' else '&#10007;' if c['result'] == 'lose' else '&middot;'}</td></tr>"
        for c in picks[::-1][:40])
    out = ROOT / "papertrade.html"
    out.write_text(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Paper trade</title>
<style>:root{{--bg:#fcfcfb;--fg:#0b0b0b;--muted:#75736e;--line:rgba(11,11,11,.12)}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141413;--fg:#fff;--muted:#908e88;--line:rgba(255,255,255,.14)}}}}
body{{margin:0 auto;max-width:760px;padding:20px 16px 60px;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 6px}} .sub{{color:var(--muted);font-size:13px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}} th,td{{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);font-size:11.5px;text-transform:uppercase}} .n{{text-align:right;font-variant-numeric:tabular-nums}}
.big{{font-size:28px;font-weight:700}}</style></head><body>
<h1>Paper trade: the site's picks at Paddy Power prices</h1>
<p class="sub">Every player bet the site put forward (best bets, picks, singles), matched to the Paddy Power price logged
for the same line before kick-off. Updated with every publish. Made {time.strftime('%a %d %b, %H:%M')}.</p>
<p><span class="big">£{s['bank']:,.0f}</span> <span class="sub">from £1,000 at 1% of the bank a bet</span></p>
<p>{s['n']} settled, {s['won']} won ({s['won'] / s['n'] * 100 if s['n'] else 0:.0f}%; the site said {s['said'] * 100:.0f}%),
flat-stake return <b>{s['flat_roi'] * 100:+.1f}%</b>; {s['pending']} still to play.</p>
<h2>By type</h2><table><thead><tr><th>Type</th><th class=n>Bets</th><th class=n>Won</th><th class=n>Site said</th><th class=n>Return</th></tr></thead><tbody>{rows}</tbody></table>
{_bands(picks)}{_sharp()}<h2>Latest</h2><table><thead><tr><th>Date</th><th>Bet</th><th class=n>PP price</th><th class=n>Site said</th><th class=n></th></tr></thead><tbody>{recent}</tbody></table>
<p class="sub">Only lines Paddy Power priced count, and only player lines (team lines are in the team log). A few hundred settled bets are needed
before the return means much; under 100 it is mostly noise.</p></body></html>""", encoding="utf-8")
    return out


def main():
    import sys
    if "--page" in sys.argv:
        print("wrote", page())
        return
    cands = candidates()
    print(f"{len(cands)} settled priced lines "
          f"({sum(c['src'] == 'Paddy Power player' for c in cands)} Paddy Power player, "
          f"{sum(c['src'] == 'Betfair' for c in cands)} Betfair)\n")
    tests = [
        ("Everything the model rates 5%+ value", dict(edge=0.05)),
        ("Everything, 10%+ value", dict(edge=0.10)),
        ("Paddy Power player, player model only, 5%+", dict(edge=0.05, only=lambda c: c["src"] == "Paddy Power player" and c["fmodel"])),
        ("Paddy Power anytime scorers, player model, 5%+, price <= 8", dict(edge=0.05, max_price=8.0, only=lambda c: c["src"] == "Paddy Power player" and c["fmodel"] and c["kind"] == "Goals")),
        ("Betfair only, 5%+", dict(edge=0.05, only=lambda c: c["src"] == "Betfair")),
        ("Blind: every Paddy Power player line the model rates 60%+, 1% stakes (no value filter)", dict(edge=-1, flat=0.01, only=lambda c: c["src"] == "Paddy Power player" and c["fmodel"] and c["p"] >= 0.6)),
    ]
    for name, kw in tests:
        r = run(cands, **kw)
        print(f"{name}\n  £1,000 -> £{r['bank']:,.2f}  ({r['bets']} bets, {r['won']} won, staked £{r['staked']:,.0f}, "
              f"ROI {r['roi'] * 100:+.1f}%, worst drop {r['max_drawdown'] * 100:.0f}%)")
        top = sorted(r["by"].items(), key=lambda kv: -kv[1][0])[:5]
        for k, (n, st, pnl) in top:
            print(f"     {k:38} {n:4} bets  {pnl:+8.2f}  ({pnl / st * 100 if st else 0:+.0f}%)")
        print()


if __name__ == "__main__":
    main()
