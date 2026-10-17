"""
Score the model against Betfair, and tune the blend from the results.

    python exchange_eval.py log       # record every bet Betfair prices now (publish does this)
    python exchange_eval.py settle    # settle finished fixtures from SofaScore
    python exchange_eval.py report    # print the scorecard
    python exchange_eval.py fit       # refit blend weights and margins -> exchange_weights.json
    python exchange_eval.py page      # write market-check.html

Every time the site publishes, each of our bets that Betfair also prices (or
implies) is written to exchange_log.json with four chances side by side:

    model     ours alone, before the market touches it
    anchored  ours with this round's usual lean against the market taken off
    market    Betfair's, margin removed
    blend     what the site actually uses

plus the back price on offer. The first sighting is kept, and the last one
before kick-off, so the log can answer two questions, one quickly and one
slowly:

  Closing line value, from the first day. If the price we flagged as value
  shortens by kick-off, the market moved our way: that is the earliest
  honest sign of an edge, and it needs no results. If our value bets drift
  out, the model is seeing ghosts, whatever the hit rate says.

  Results, as fixtures finish. Log loss and Brier for each of the four
  chances, by market family; calibration; and what backing every value bet
  at the price on offer, after commission, would have returned.

`fit` then sets, for every family with enough settled bets, the blend weight
that would have scored best (shrunk towards the default while the sample is
small) and, for back-only lists, the margin that actually sits in those
prices. weekend.py and market_prices.py read exchange_weights.json, so the
blend tunes itself as results come in.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "exchange_log.json"
WEIGHTS = HERE / "exchange_weights.json"
PAGE = HERE / "market-check.html"

FIT_MIN = 30          # settled bets before a family's weight is refitted
FIT_PRIOR = 50        # pseudo-bets pulling a fitted weight towards the default
VALUE_BANDS = (0.0, 0.03, 0.06, 0.10)


# ----------------------------------------------------------------- legs

def upcoming_legs(days: int = 3) -> list[dict]:
    """Every leg the picks would see over the next few days, calibrated and
    blended exactly as weekend.picks does it."""
    import make_index as mi
    import parlay
    import weekend
    files = [f for f in sorted(mi.REPORTS.glob("*.html")) if not f.name.startswith(("pick-", "_"))]
    files.sort(key=lambda p: ("-v-" in p.stem or p.stem.startswith("mixed-"), p.stat().st_mtime), reverse=True)
    now = time.time()
    seen, out = set(), []
    for path in files:
        for entry, meta in mi.read_entries(path):
            k = (meta["home"], meta["away"], meta["kickoff"])
            if k in seen:
                continue
            seen.add(k)
            if not (now < (meta.get("kickoff") or 0) <= now + days * 86400):
                continue
            sport = weekend.sport_of(entry)
            meta = dict(meta, sport=sport)
            legs = (weekend.legs_for(entry, meta) + parlay.single_legs_for(entry, meta)
                    + parlay.alt_legs_for(entry, meta))
            out.extend(legs)
    by_sport: dict = {}
    for l in out:
        by_sport.setdefault(l["fixture"]["sport"], []).append(l)
    for legs in by_sport.values():
        weekend.calibrate(legs)
    return out


def key_of(l: dict) -> str:
    fx = l.get("fixture") or {}
    return "|".join(str(x) for x in (fx.get("id"), l.get("player") or l.get("team"), l.get("stat"),
                                     l.get("period") or "ALL", l.get("line"), bool(l.get("over", True))))


def load() -> dict:
    try:
        return json.loads(LOG.read_text())
    except (OSError, ValueError):
        return {}


def save(log: dict) -> None:
    LOG.write_text(json.dumps(log, separators=(",", ":")))


def _snap(l: dict, now: float) -> dict:
    q = l["exchange"]
    return {"t": round(now), "model": _r(l.get("pModel")), "anchored": _r(l.get("pAnchored")),
            "market": _r(q.get("p")), "blend": _r(l.get("pExchange")), "back": q.get("back"),
            "lay": q.get("lay"), "matched": round(q.get("matched") or 0), "tight": bool(q.get("tight")),
            "w": l.get("exchangeWeight"), "value": _r(l.get("value")), "disagree": l.get("disagree")}


def _r(x, n=4):
    return None if x is None else round(x, n)


def log_now(days: int = 3) -> int:
    import weekend
    log = load()
    now = time.time()
    added = updated = 0
    this_run = set()
    for l in upcoming_legs(days):
        q = l.get("exchange")
        if not q:
            continue
        k = key_of(l)
        if k in this_run:
            continue
        this_run.add(k)
        fx = l["fixture"]
        snap = _snap(l, now)
        rec = log.get(k)
        if rec is None:
            log[k] = {"event_id": fx.get("id"), "fixture": f"{fx.get('home')} v {fx.get('away')}",
                      "competition": fx.get("competition"), "kickoff": fx.get("kickoff"),
                      "sport": fx.get("sport"), "team": l.get("team"), "player": l.get("player"),
                      "stat": l.get("stat"), "period": l.get("period") or "ALL", "line": l.get("line"),
                      "over": bool(l.get("over", True)), "family": weekend.exchange_family(l, q),
                      "kind": q.get("kind"), "mtype": q.get("type"), "hits": l.get("hits"),
                      "total": l.get("total"), "first": snap, "last": snap, "seen": 1,
                      "result": None, "value": None}
            added += 1
        elif now < (rec.get("kickoff") or 0) and now - rec["last"]["t"] >= 1800:
            rec["last"] = snap
            rec["seen"] = rec.get("seen", 1) + 1
            updated += 1
    save(log)
    print(f"exchange log: {added} new bet(s), {updated} re-priced, {len(log)} in the log")
    return added


# --------------------------------------------------------------- settle

def settle() -> int:
    import besttrack
    import hitrates
    import sofascore_api as api
    log = load()
    now = time.time()
    events: dict = {}
    done = 0
    for rec in log.values():
        if rec.get("result") is not None or (rec.get("kickoff") or 0) > now - 3 * 3600:
            continue
        eid = rec["event_id"]
        if eid not in events:
            try:
                ev = api.get_json(f"event/{eid}", max_age_hours=1, verbose=False) or {}
                ev = ev.get("event", ev)
                stats = hitrates.extract_match_stats(api.event_statistics(eid)) \
                    if (ev.get("status") or {}).get("type") == "finished" else None
            except Exception:
                ev, stats = {}, None
            events[eid] = (ev, stats)
        ev, stats = events[eid]
        status = (ev.get("status") or {}).get("type")
        if status in ("canceled", "postponed"):
            rec["result"] = "void"
            continue
        if status != "finished":
            continue
        leg = dict(rec, event_id=eid)
        try:
            v = (besttrack._player_value(leg, rec["sport"]) if rec.get("player")
                 else besttrack._team_value(leg, ev, stats or {}))
        except Exception:
            v = None
        if v is None:
            continue
        if v == "dnp":
            rec["result"] = "void"
        else:
            rec["value"] = v
            won = v > rec["line"] if rec["over"] else v < rec["line"]
            rec["result"] = "win" if won else "lose"
        done += 1
    save(log)
    print(f"exchange log: settled {done}, "
          f"{sum(1 for r in log.values() if r.get('result') is None)} still open")
    return done


# -------------------------------------------------------------- scoring

def _ll(p, won):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -math.log(p if won else 1 - p)


def _lg(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sig(z):
    return 1 / (1 + math.exp(-z))


def settled(log=None) -> list[dict]:
    return [r for r in (log or load()).values() if r.get("result") in ("win", "lose")]


def score(rows: list[dict], snap: str = "first") -> dict:
    """Log loss and Brier for each chance, on one set of settled bets."""
    out = {"n": len(rows)}
    if not rows:
        return out
    for name in ("model", "anchored", "market", "blend"):
        ps = [(r[snap].get(name), r["result"] == "win") for r in rows if r[snap].get(name) is not None]
        if not ps:
            continue
        out[name] = {"logloss": sum(_ll(p, w) for p, w in ps) / len(ps),
                     "brier": sum((p - w) ** 2 for p, w in ps) / len(ps),
                     "said": sum(p for p, _ in ps) / len(ps), "n": len(ps)}
    out["landed"] = sum(1 for r in rows if r["result"] == "win") / len(rows)
    return out


def calibration(rows: list[dict], name: str = "blend", snap: str = "first") -> list[dict]:
    bins: dict = {}
    for r in rows:
        p = r[snap].get(name)
        if p is None:
            continue
        b = min(int(p * 10), 9)
        bins.setdefault(b, []).append((p, r["result"] == "win"))
    return [{"band": f"{b * 10}-{b * 10 + 10}%", "n": len(v), "said": sum(p for p, _ in v) / len(v),
             "landed": sum(1 for _, w in v if w) / len(v)} for b, v in sorted(bins.items())]


def roi(rows: list[dict], minimum: float, commission: float | None = None) -> dict:
    """Back every bet whose value cleared `minimum` at its first sighting,
    one unit each, at the back price on offer then."""
    import weekend
    c = weekend.COMMISSION if commission is None else commission
    bets = [r for r in rows if r["first"].get("value") is not None and r["first"]["value"] >= minimum
            and r["first"].get("back")]
    pnl = [((r["first"]["back"] - 1) * (1 - c) if r["result"] == "win" else -1.0) for r in bets]
    n = len(pnl)
    if not n:
        return {"n": 0}
    mean = sum(pnl) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in pnl) / max(1, n - 1))
    return {"n": n, "profit": sum(pnl), "roi": mean, "lo": mean - 1.96 * sd / math.sqrt(n),
            "hi": mean + 1.96 * sd / math.sqrt(n),
            "wins": sum(1 for r in bets if r["result"] == "win")}


def clv(log: dict) -> dict:
    """Closing line value: the market's move between our first sighting and
    the last one before kick-off, on the side the model favoured.

    `beat` is the share of value bets whose back price shortened after we
    flagged them; `edge` the average of first back price over the closing
    fair price, minus one. Needs two sightings, nothing else."""
    rows = [r for r in log.values() if r.get("seen", 1) >= 2 and r["first"].get("back")
            and r["last"].get("market") and r["first"].get("market")]
    def summarise(sel):
        if not sel:
            return {"n": 0}
        edges = [r["first"]["back"] * r["last"]["market"] - 1 for r in sel]
        moved = [_lg(r["last"]["market"]) - _lg(r["first"]["market"]) for r in sel]
        return {"n": len(sel), "edge": sum(edges) / len(edges),
                "beat": sum(1 for m in moved if m > 0.01) / len(sel),
                "drift": sum(1 for m in moved if m < -0.01) / len(sel)}
    value = [r for r in rows if (r["first"].get("value") or -1) > 0]
    model_high = [r for r in rows if (r["first"].get("anchored") or r["first"].get("model") or 0)
                  > (r["first"].get("market") or 1) + 0.03]
    return {"value": summarise(value), "modelHigher": summarise(model_high), "all": summarise(rows)}


def by_family(rows: list[dict]) -> dict:
    fams: dict = {}
    for r in rows:
        fams.setdefault(r["family"], []).append(r)
    return fams


# ------------------------------------------------------------------ fit

def _best_weight(rows: list[dict]) -> float:
    def loss(w):
        t = 0.0
        for r in rows:
            s = r["first"]
            m = s.get("anchored") or s.get("model")
            if m is None or s.get("market") is None:
                continue
            t += _ll(_sig(w * _lg(s["market"]) + (1 - w) * _lg(m)), r["result"] == "win")
        return t
    return min((i / 20 for i in range(21)), key=loss)


def _best_margin(rows: list[dict]) -> float | None:
    rows = [r for r in rows if r["first"].get("back") and r["over"]]
    if not rows:
        return None
    def loss(m):
        return sum(_ll((1 / r["first"]["back"]) / (1 + m), r["result"] == "win") for r in rows)
    return min((i / 100 for i in range(-5, 41)), key=loss)


def fit(write: bool = True) -> dict:
    import market_prices as mp
    import weekend
    rows = settled()
    weights, margins, info = {}, {}, {}
    for fam, rs in by_family(rows).items():
        if len(rs) < FIT_MIN:
            continue
        kind = fam.split("|")[-1]
        default = (weekend.EXCHANGE_W_BACK if kind == "back" else weekend.EXCHANGE_W_DERIVED
                   if kind == "derived" else weekend.EXCHANGE_W_TIGHT)
        w_hat = _best_weight(rs)
        w = (len(rs) * w_hat + FIT_PRIOR * default) / (len(rs) + FIT_PRIOR)
        weights[fam] = round(w, 3)
        info[fam] = {"n": len(rs), "raw": w_hat, "default": default}
    by_type: dict = {}
    for r in rows:
        if r.get("kind") == "back" and r.get("mtype"):
            by_type.setdefault(r["mtype"], []).append(r)
    for t, rs in by_type.items():
        if len(rs) < FIT_MIN:
            continue
        m_hat = _best_margin(rs)
        if m_hat is None:
            continue
        default = mp.BACK_MARGIN.get(t, 0.10)
        margins[t] = round((len(rs) * m_hat + FIT_PRIOR * default) / (len(rs) + FIT_PRIOR), 3)
        info[t] = {"n": len(rs), "raw": m_hat, "default": default}
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "weights": weights, "backMargin": margins, "fit": info, "settled": len(rows)}
    if write:
        WEIGHTS.write_text(json.dumps(out, indent=1))
    return out


# --------------------------------------------------------------- report

def summary() -> dict:
    log = load()
    rows = settled(log)
    fams = {f: score(rs) for f, rs in by_family(rows).items()}
    return {"logged": len(log), "open": sum(1 for r in log.values() if r.get("result") is None),
            "settled": len(rows), "overall": score(rows), "lastSnap": score(rows, "last"),
            "families": fams, "calibration": calibration(rows),
            "roi": {f"{int(b * 100)}%+": roi(rows, b) for b in VALUE_BANDS},
            "clv": clv(log)}


def _fmt(x, pct=False):
    if x is None:
        return "-"
    return f"{x * 100:+.1f}%" if pct else f"{x:.4f}"


def report() -> None:
    s = summary()
    print(f"{s['logged']} bets logged, {s['settled']} settled, {s['open']} open\n")
    o = s["overall"]
    if o.get("n"):
        print(f"{'':12}{'log loss':>10}{'brier':>9}{'said':>7}   landed {o['landed']:.0%}")
        for name in ("model", "anchored", "market", "blend"):
            if name in o:
                x = o[name]
                print(f"{name:12}{x['logloss']:>10.4f}{x['brier']:>9.4f}{x['said']:>7.0%}")
        print("\nby family (log loss: model / market / blend, n)")
        for f, x in sorted(s["families"].items(), key=lambda kv: -kv[1]["n"]):
            print(f"  {f:44} {x.get('model', {}).get('logloss', 0):.3f} / "
                  f"{x.get('market', {}).get('logloss', 0):.3f} / {x.get('blend', {}).get('logloss', 0):.3f}  {x['n']}")
        print("\nvalue bets at the price offered, after commission")
        for k, r in s["roi"].items():
            if r.get("n"):
                print(f"  value {k:5} {r['n']:4} bets  {r['wins']} won  profit {r['profit']:+.1f}u  "
                      f"ROI {r['roi']:+.1%}  (95% {r['lo']:+.1%} to {r['hi']:+.1%})")
    c = s["clv"]
    print("\nclosing line value (no results needed)")
    for k, lab in (("value", "value bets"), ("modelHigher", "model above market"), ("all", "everything")):
        x = c[k]
        if x.get("n"):
            print(f"  {lab:20} {x['n']:5}  edge v close {x['edge']:+.1%}  shortened {x['beat']:.0%}  drifted {x['drift']:.0%}")
        else:
            print(f"  {lab:20} not yet: needs a second publish before kick-off")


# ----------------------------------------------------------------- page

CSS = """:root{--bg:#fbfbfa;--fg:#18181b;--muted:#71717a;--line:#e7e7e4;--card:#fff;--win:#15803d;--lose:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#0f0f10;--fg:#ececec;--muted:#8b8b93;--line:#26262a;--card:#17171a;--win:#4ade80;--lose:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:24px 16px 60px}a{color:inherit}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.05rem;margin:28px 0 8px}.sub{color:var(--muted);font-size:.85rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-top:12px}
table{width:100%;border-collapse:collapse;font-size:.85rem;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600;font-size:.75rem;text-transform:uppercase;letter-spacing:.04em}
.tbl{overflow-x:auto}.pos{color:var(--win);font-weight:650}.neg{color:var(--lose);font-weight:650}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi b{display:block;font-size:1.3rem}.kpi span{color:var(--muted);font-size:.78rem}
p{margin:6px 0}"""


def _cls(x):
    return "pos" if x is not None and x > 0 else "neg" if x is not None and x < 0 else ""


def page() -> Path:
    s = summary()
    e = html.escape
    o = s["overall"]
    c = s["clv"]
    built = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    v = c["value"]
    kpis = [
        ("Bets logged", f"{s['logged']:,}", f"{s['settled']} settled, {s['open']} open"),
        ("Value v close", (f"<span class='{_cls(v.get('edge'))}'>{v['edge']:+.1%}</span>" if v.get("n") else "-"),
         f"{v.get('n', 0)} value bets seen twice"),
    ]
    r0 = s["roi"].get("3%+") or {}
    kpis.append(("Value ROI", (f"<span class='{_cls(r0.get('roi'))}'>{r0['roi']:+.1%}</span>" if r0.get("n") else "-"),
                 f"{r0.get('n', 0)} settled at 3%+ value"))
    if o.get("blend") and o.get("market"):
        d = o["market"]["logloss"] - o["blend"]["logloss"]
        kpis.append(("Blend v market", f"<span class='{_cls(d)}'>{d:+.4f}</span>", "log loss saved per bet"))
    kp = "".join(f"<div class='card kpi'><span>{e(a)}</span><b>{b}</b><span>{e(c_)}</span></div>"
                 for a, b, c_ in kpis)

    def score_rows(x):
        out = []
        for name, lab in (("model", "Model alone"), ("anchored", "Model, bias off"),
                          ("market", "Betfair"), ("blend", "Blend (used)")):
            if name in x:
                y = x[name]
                out.append(f"<tr><td>{lab}</td><td>{y['logloss']:.4f}</td><td>{y['brier']:.4f}</td>"
                           f"<td>{y['said']:.0%}</td></tr>")
        return "".join(out)

    acc = (f"<div class='tbl'><table><tr><th>Chance</th><th>Log loss</th><th>Brier</th><th>Said</th></tr>"
           f"{score_rows(o)}</table></div><p class='sub'>Landed {o['landed']:.0%} of {o['n']}. Lower is better "
           f"on both scores; the row with the lowest log loss is the one to trust.</p>"
           if o.get("n") else "<p class='sub'>Nothing settled yet. Fixtures settle three hours after kick-off.</p>")
    fam_rows = "".join(
        f"<tr><td>{e(f.replace('|', ' &middot; '))}</td><td>{x['n']}</td>"
        f"<td>{x.get('model', {}).get('logloss', float('nan')):.3f}</td>"
        f"<td>{x.get('market', {}).get('logloss', float('nan')):.3f}</td>"
        f"<td>{x.get('blend', {}).get('logloss', float('nan')):.3f}</td></tr>"
        for f, x in sorted(s["families"].items(), key=lambda kv: -kv[1]["n"]))
    fams = (f"<div class='tbl'><table><tr><th>Family</th><th>n</th><th>Model</th><th>Betfair</th><th>Blend</th></tr>"
            f"{fam_rows}</table></div>" if fam_rows else "<p class='sub'>No families settled yet.</p>")
    roi_rows = "".join(
        f"<tr><td>{e(k)}</td><td>{r['n']}</td><td>{r['wins']}</td>"
        f"<td class='{_cls(r['profit'])}'>{r['profit']:+.1f}u</td>"
        f"<td class='{_cls(r['roi'])}'>{r['roi']:+.1%}</td><td>{r['lo']:+.1%} to {r['hi']:+.1%}</td></tr>"
        for k, r in s["roi"].items() if r.get("n"))
    rois = (f"<div class='tbl'><table><tr><th>Value at least</th><th>Bets</th><th>Won</th><th>Profit</th>"
            f"<th>ROI</th><th>95% range</th></tr>{roi_rows}</table></div>"
            if roi_rows else "<p class='sub'>No settled value bets yet.</p>")
    clv_rows = "".join(
        f"<tr><td>{lab}</td><td>{c[k]['n']}</td><td class='{_cls(c[k]['edge'])}'>{c[k]['edge']:+.1%}</td>"
        f"<td>{c[k]['beat']:.0%}</td><td>{c[k]['drift']:.0%}</td></tr>"
        for k, lab in (("value", "Value bets"), ("modelHigher", "Model above Betfair"), ("all", "Everything"))
        if c[k].get("n"))
    clvs = (f"<div class='tbl'><table><tr><th></th><th>Bets</th><th>Edge v close</th><th>Shortened</th>"
            f"<th>Drifted</th></tr>{clv_rows}</table></div>"
            if clv_rows else "<p class='sub'>Needs two publishes before a kick-off.</p>")
    cal_rows = "".join(f"<tr><td>{b['band']}</td><td>{b['n']}</td><td>{b['said']:.0%}</td><td>{b['landed']:.0%}</td></tr>"
                       for b in s["calibration"])
    cal = (f"<div class='tbl'><table><tr><th>Blend said</th><th>Bets</th><th>Average</th><th>Landed</th></tr>"
           f"{cal_rows}</table></div>" if cal_rows else "<p class='sub'>Nothing settled yet.</p>")
    try:
        w = json.loads(WEIGHTS.read_text())
        tuned = ", ".join(f"{e(k.replace('|', ' '))} {v:.2f}" for k, v in (w.get("weights") or {}).items()) or "none yet"
        tuned_line = f"<p class='sub'>Fitted blend weights ({e(w.get('updated', ''))}): {tuned}.</p>"
    except (OSError, ValueError):
        tuned_line = f"<p class='sub'>No fitted weights yet: each family needs {FIT_MIN} settled bets.</p>"

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Market check</title>
<style>{CSS}</style></head><body><div class="wrap">
<p class="sub"><a href="index.html">&larr; Hit Rates</a></p>
<h1>Market check</h1>
<p class="sub">Every bet the site prices that Betfair also prices, scored against Betfair. Built {built}.</p>
<div class="kpis">{kp}</div>
<h2>Closing line value</h2>
<p class="sub">Did Betfair's price move towards us between the first time we saw a bet and kick-off? The
quickest honest test of an edge: if value bets shorten, the market came round to the model.</p>
<div class="card">{clvs}</div>
<h2>Accuracy</h2>
<div class="card">{acc}</div>
<h2>Backing the value bets</h2>
<p class="sub">One unit on every bet whose value cleared the bar when first seen, at the back price on offer
then, after commission.</p>
<div class="card">{rois}</div>
<h2>Calibration of the blend</h2>
<div class="card">{cal}</div>
<h2>By market</h2>
<div class="card">{fams}{tuned_line}</div>
</div></body></html>"""
    PAGE.write_text(doc)
    print(f"wrote {PAGE.name}")
    return PAGE


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("log", "settle", "report", "fit", "page"))
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "log":
        log_now(a.days)
    elif a.cmd == "settle":
        settle()
    elif a.cmd == "report":
        report()
    elif a.cmd == "fit":
        out = fit()
        print(json.dumps(out, indent=1))
    else:
        page()


if __name__ == "__main__":
    main()
