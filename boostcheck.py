"""
Two things on the tonight page that answer the questions that kept being
asked by hand (22 Oct 2026):

1. value_box(window, now): bookmaker player bets where our model is ahead of
   the Paddy Power price, with the record of that kind of bet so far from
   pplog, and a budget split. The rule picks itself from the settled log:
   a market is shown only while its record at sensible prices is close to
   break-even or better and not carried by one or two long shots. Chances
   are shrunk by how far that market's hits have fallen short of the model.

2. boost_tab(entry, meta): a calculator for price boosts and bet builders
   on one game. Result, most shots on target, most corners, goals line and
   both teams to score, against the boosted price. Result from the site's
   score model, goals from its Poisson projection (rescaled to the result),
   shots-on-target and corners winners from boost_table.json: how often each
   side won those, given the result and which side was the pre-game
   favourite, across 5,000 matches (boost_table.py). Ties lose.
"""
from __future__ import annotations

import html
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / "boost_table.json"

MAX_PRICE = 8.0        # longer prices: a handful of winners decide the record
MIN_SETTLED = 20
BREAK_EVEN_TOL = -0.05  # ROI per bet at or above this counts as "about break-even"
MAX_BETS = 6


# ------------------------------------------------------------------ value box

def _segments(rows):
    """Record per stat for fmodel-priced bets with an edge, at <= MAX_PRICE."""
    import pplog
    seg = {}
    for r in rows:
        s = r.get("last") or {}
        if (r.get("sport") != "football" or r.get("result") not in ("win", "lose")
                or s.get("source") != "fmodel" or s.get("edge", -1) <= 0 or s.get("price", 99) > MAX_PRICE):
            continue
        g = seg.setdefault(r["stat"], {"n": 0, "w": 0, "pred": 0.0, "profit": 0.0, "wins": []})
        g["n"] += 1
        g["pred"] += s["chance"]
        p = pplog._profit(r, "last")
        g["profit"] += p
        if r["result"] == "win":
            g["w"] += 1
            g["wins"].append(p)
    for g in seg.values():
        top2 = sum(sorted(g["wins"], reverse=True)[:2])
        g["roi"] = g["profit"] / g["n"]
        g["robust_roi"] = (g["profit"] - top2) / g["n"]
        g["shrink"] = min(1.0, (g["w"] + 1) / (g["pred"] + 1))
        g["ok"] = g["n"] >= MIN_SETTLED and g["roi"] >= BREAK_EVEN_TOL
        g["proven"] = g["ok"] and g["robust_roi"] > 0
    return seg


def value_bets(now: float, until: float) -> tuple[list[dict], dict]:
    import pplog
    rows = pplog.all_rows()
    seg = _segments(rows)
    fm = pplog._fmodel()  # live player model: confirmed XI once out, predicted XI before
    out = []
    for r in rows:
        s = r.get("last") or {}
        g = seg.get(r.get("stat"))
        if (not g or not g["ok"] or r.get("sport") != "football" or not (now < (r.get("kickoff") or 0) < until)
                or s.get("source") != "fmodel" or s.get("price", 99) > MAX_PRICE or s.get("edge", -1) <= 0):
            continue
        ev = fm.get(str(r.get("event_id"))) or {}
        starting = pplog._norm(r["player"]) in (ev.get("players") or {})
        if not starting:
            continue  # not in the XI the model is using (benched once line-ups land)
        p = s["chance"] * g["shrink"]
        site = s.get("site_chance")
        if p * s["price"] <= 1.0 or (site is not None and site * s["price"] <= 1.0):
            continue  # gone once shrunk, or the site's own record disagrees
        kelly = (p * s["price"] - 1) / (s["price"] - 1)
        out.append({"fixture": r["fixture"], "kickoff": r["kickoff"], "player": r["player"], "stat": r["stat"],
                    "label": r["label"], "market": r.get("market"), "price": s["price"], "p": p, "site": site,
                    "kelly": kelly, "fetched": s.get("t"), "proven": g["proven"],
                    "first_price": (r.get("first") or {}).get("price"),
                    "xi": "confirmed" if ev.get("confirmed") else "predicted"})
    # one bet per game (legs in one game move together), best first
    out.sort(key=lambda b: -b["kelly"])
    seen, pick = set(), []
    for b in out:
        if b["fixture"] in seen:
            continue
        seen.add(b["fixture"])
        pick.append(b)
        if len(pick) == MAX_BETS:
            break
    return pick, seg


def _move(b) -> str:
    """The price when first logged, if it has moved: lines the model liked
    shortened 3.6% on average before kick-off (papertrade/CLV check, 22 Oct)."""
    f = b.get("first_price")
    if not f or abs(f - b["price"]) < 0.01:
        return ""
    arrow = "&darr;" if b["price"] < f else "&uarr;"
    return f"<div class='sub'>{arrow} from {f:.2f}</div>"


def value_box(now: float, until: float) -> str:
    esc = html.escape
    try:
        bets, seg = value_bets(now, until)
    except Exception as exc:  # never cost the page
        return f"<p class='sub'>Bookie value bets unavailable ({esc(str(exc))})</p>"
    recs = []
    for stat, g in sorted(seg.items(), key=lambda kv: -kv[1]["roi"]):
        if g["n"] >= 10:
            recs.append(f"{esc(stat)}: {g['n']} bets, {g['w']} won, {g['profit']:+.1f} pts "
                        f"({g['roi'] * 100:+.0f}%)")
    record = "; ".join(recs) or "nothing settled yet"
    if not bets:
        return ("<div class='vbox'><p class='none'>Nothing tonight where our model beats the Paddy Power "
                "price by enough, once its record is allowed for.</p>"
                f"<p class='sub'>Record of model-ahead bets at {MAX_PRICE:.0f}.0 or shorter: {record}.</p></div>")
    proven = all(b["proven"] for b in bets)
    banner = ("<p class='call ok'><b>Proven:</b> this kind of bet has made money at these prices, "
              "beyond one or two lucky long shots.</p>" if proven else
              "<p class='call meh'><b>Not proven yet:</b> at these prices this kind of bet has been about "
              "break-even so far, which beats the 30&ndash;60% that every other Paddy Power player market "
              "has lost. Small stakes.</p>")
    rows = []
    for i, b in enumerate(bets):
        ko = time.strftime("%H:%M", time.localtime(b["kickoff"]))
        sel = f"{b['player']} {b['label']}" + ("" if b["stat"] == "Goals" else f" {b['stat'].lower()}")
        tag = ("<span class='tag ok'>starting</span>" if b["xi"] == "confirmed"
               else "<span class='tag'>predicted XI</span>")
        rows.append(f"<tr data-k='{b['kelly']:.5f}'><td>{esc(sel)} {tag}<div class='sub'>{ko} &middot; "
                    f"{esc(b['fixture'])}</div></td><td class='n'>{b['price']:.2f}{_move(b)}</td>"
                    f"<td class='n'>{b['p'] * 100:.0f}%</td><td class='n'>{100 / b['price']:.0f}%</td>"
                    f"<td class='n stake'>&ndash;</td></tr>")
    fetched = max((b["fetched"] or 0) for b in bets)
    return (
        "<div class='vbox'>" + banner +
        "<p class='budget'>Budget &pound;<input type='number' id='vbudget' value='10' min='1' step='1' "
        "inputmode='decimal'> <span class='sub'>split by how far ahead each bet is, one per game</span></p>"
        "<table><thead><tr><th>Bet</th><th class='n'>Price</th><th class='n'>Ours</th>"
        "<th class='n'>Price says</th><th class='n'>Stake</th></tr></thead><tbody id='vrows'>"
        + "".join(rows) + "</tbody></table>"
        f"<p class='sub'>Updates when line-ups land: a player benched in the confirmed XI drops off. "
        f"Paddy Power prices as of {time.strftime('%H:%M', time.localtime(fetched))}: check "
        f"each is still close before betting, and skip any that has shortened. Our chance is the player "
        f"model's, cut by how far its hits have fallen short in this market. Record so far, model-ahead bets "
        f"at {MAX_PRICE:.0f}.0 or shorter: {record}. Singles only: a multiple stacks the margin.</p></div>")


# ------------------------------------------------------------------ boost tab

def _table() -> dict:
    try:
        return json.loads(TABLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def boost_data(entry: dict, meta: dict) -> dict | None:
    import context
    b = context.brief(entry, meta)
    sc = b.get("score") or {}
    if not all(isinstance(sc.get(k), (int, float)) for k in ("ph", "pd", "pa", "lh", "la")):
        return None
    xh, xa = (b.get("home") or {}).get("xg") or {}, (b.get("away") or {}).get("xg") or {}
    cut = _table().get("cut", 0.5)
    try:
        d = (xh["for_pg"] - xh["against_pg"]) - (xa["for_pg"] - xa["against_pg"])
        bucket = "home_fav" if d > cut else "away_fav" if d < -cut else "even"
    except (KeyError, TypeError):
        bucket = "even"
    return {"home": meta["home"], "away": meta["away"], "ph": sc["ph"], "pd": sc["pd"], "pa": sc["pa"],
            "lh": sc["lh"], "la": sc["la"], "bucket": bucket, "src": sc.get("source", "")}


def boost_tab(entry: dict, meta: dict, n: int) -> str:
    esc = html.escape
    try:
        d = boost_data(entry, meta)
    except Exception as exc:
        return f"<p class='sub'>Boost check unavailable ({esc(str(exc))})</p>"
    if not d:
        return "<p class='none'>No score model for this game, so no boost check.</p>"
    h, a = esc(d["home"]), esc(d["away"])
    fav = {"home_fav": f"{h} favourites on recent xG", "away_fav": f"{a} favourites on recent xG",
           "even": "evenly matched on recent xG"}[d["bucket"]]

    def sel(name, opts):
        return (f"<label class='bl'><span>{name}</span><select data-leg='{name}'>"
                + "".join(f"<option value='{v}'>{t}</option>" for v, t in opts) + "</select></label>")
    return (
        f"<div class='boost' data-g='{esc(json.dumps(d))}'>"
        f"<p class='sub'>Tick the legs of a boost or bet builder and type its price. "
        f"Our model: {h} {d['ph'] * 100:.0f}%, draw {d['pd'] * 100:.0f}%, {a} {d['pa'] * 100:.0f}%; "
        f"goals {d['lh']:.1f}&ndash;{d['la']:.1f}; {fav}.</p>"
        + sel("Result", [("", "any"), ("H", f"{h} win"), ("D", "draw"), ("A", f"{a} win"),
                         ("HD", f"{h} or draw"), ("AD", f"{a} or draw")])
        + sel("Most shots on target", [("", "any"), ("H", h), ("A", a)])
        + sel("Most corners", [("", "any"), ("H", h), ("A", a)])
        + sel("Goals", [("", "any"), ("o1.5", "over 1.5"), ("o2.5", "over 2.5"), ("o3.5", "over 3.5"),
                        ("u2.5", "under 2.5"), ("u3.5", "under 3.5")])
        + sel("Both teams to score", [("", "any"), ("y", "yes"), ("n", "no")])
        + "<label class='bl'><span>Price</span><input type='number' step='0.01' min='1.01' "
          "inputmode='decimal' placeholder='e.g. 2.25'></label>"
        "<div class='bout'></div>"
        "<p class='sub'>Shots-on-target and corners winners come from 5,000 matches: how often each side "
        "won them given the result and who was favourite. Ties lose, as they do on most boosts. A guide, "
        "not a price: player legs are not in here.</p></div>")


SCRIPT = r"""
<script>
(function(){
var T=__TABLE__;
function pois(l,k){var p=Math.exp(-l);for(var i=1;i<=k;i++)p*=l/i;return p;}
function calc(box){
  var g=JSON.parse(box.dataset.g), legs={};
  box.querySelectorAll('select').forEach(function(s){legs[s.dataset.leg]=s.value;});
  var price=parseFloat(box.querySelector('input').value), out=box.querySelector('.bout');
  var any=Object.keys(legs).some(function(k){return legs[k];});
  if(!any){out.innerHTML='';return;}
  // goals grid, rescaled so each result carries the site's own chance
  var grid=[],mass={H:0,D:0,A:0};
  for(var i=0;i<=10;i++)for(var j=0;j<=10;j++){var r=i>j?'H':i<j?'A':'D',p=pois(g.lh,i)*pois(g.la,j);grid.push([i,j,r,p]);mass[r]+=p;}
  var want={H:g.ph,D:g.pd,A:g.pa},tot=0;
  grid.forEach(function(c){
    var i=c[0],j=c[1],r=c[2],w=c[3]*want[r]/mass[r];
    if(legs['Result']&&legs['Result'].indexOf(r)<0)return;
    var gl=legs['Goals'];
    if(gl){var L=parseFloat(gl.slice(1)),n=i+j;if(gl[0]=='o'&&!(n>L))return;if(gl[0]=='u'&&!(n<L))return;}
    var bt=legs['Both teams to score'];
    if(bt=='y'&&!(i>0&&j>0))return; if(bt=='n'&&(i>0&&j>0))return;
    var cell=(T.table[g.bucket+'|'+r]||{}).p||{},ps=0;
    for(var k in cell){var s=k[0],c=k[1];
      if(legs['Most shots on target']&&s!=legs['Most shots on target'])continue;
      if(legs['Most corners']&&c!=legs['Most corners'])continue;
      ps+=cell[k];}
    tot+=w*ps;
  });
  var fair=1/tot, h='<p class="call"><b>Our chance '+(tot*100).toFixed(0)+'%</b> &middot; fair price <b>'+fair.toFixed(2)+'</b></p>';
  if(price>1){
    var need=1/price, edge=tot*price-1, cls=edge>0.05?'ok':edge>-0.1?'meh':'bad',
        word=edge>0.05?'Value':edge>-0.1?'About fair, the margin is in it':'Poor value';
    h+='<p class="call '+cls+'"><b>'+word+'</b>: '+price.toFixed(2)+' needs '+(need*100).toFixed(0)+'%, we make it '+(tot*100).toFixed(0)+'% ('+(edge>0?'+':'')+(edge*100).toFixed(0)+'% per &pound;1)</p>';
  }
  out.innerHTML=h;
}
document.querySelectorAll('.boost').forEach(function(b){
  b.addEventListener('input',function(){calc(b);});b.addEventListener('change',function(){calc(b);});});
function stakes(){
  var inp=document.getElementById('vbudget'); if(!inp)return;
  var B=parseFloat(inp.value)||0, rows=[].slice.call(document.querySelectorAll('#vrows tr')),
      K=rows.reduce(function(s,r){return s+parseFloat(r.dataset.k);},0);
  var st=rows.map(function(r){return Math.max(0.5,Math.round(2*B*parseFloat(r.dataset.k)/K)/2);});
  var over=st.reduce(function(a,b){return a+b;},0)-B;
  for(var i=st.length-1;over>0&&i>=0;i--){var c=Math.min(over,st[i]-0.5);st[i]-=c;over-=c;}
  rows.forEach(function(r,i){r.querySelector('.stake').innerHTML='&pound;'+st[i].toFixed(2);});
}
var vb=document.getElementById('vbudget'); if(vb){vb.addEventListener('input',stakes);stakes();}
})();
</script>
"""

CSS = """
.vbox { margin:8px 0 4px; }
.budget input, .boost input, .boost select { font:inherit; font-size:15px; padding:4px 6px;
  border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--fg); }
.budget input { width:80px; }
.boost .bl { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:6px 0; font-size:14px; }
.boost .bl select, .boost .bl input { max-width:58%; }
.ok { border-left:3px solid #2e8b57; padding-left:8px; }
.meh { border-left:3px solid #c9a227; padding-left:8px; }
.bad { border-left:3px solid #c0392b; padding-left:8px; }
"""


def script() -> str:
    t = _table() or {"table": {}}
    return SCRIPT.replace("__TABLE__", json.dumps({"table": t.get("table", {})}))
