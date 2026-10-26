import json, collections, random, datetime
R = json.load(open("research/_sel_rows.json"))
def roi(b):
    if not b: return (0, 0, 0)
    p = sum((x["price"] - 1) if x["win"] else -1 for x in b)
    return (len(b), len({x["ev"] for x in b}), p / len(b))
def show(name, b):
    n, g, r = roi(b)
    w = sum(x["win"] for x in b)
    print(f"{name:55s} {n:5d} bets {g:4d} games  won {w/max(n,1):.0%}  ROI {r:+.1%}")
def form(x, a=0.7, b=0.6):
    return x["n10"] and x["n10"] >= 6 and x["k10"] / x["n10"] >= a and x["n5"] and x["k5"] / x["n5"] >= b
def dedupe(b):
    best = {}
    for x in b:
        k = (x["ev"], x["pl"])
        if k not in best or x["edge"] > best[k]["edge"]: best[k] = x
    return list(best.values())
for sp in ("american-football", "basketball", "football"):
    for ov in (True, False):
        S = [x for x in R if x["sport"] == sp and x["over"] == ov]
        print(f"\n== {sp} {'over' if ov else 'under'}")
        show("all lines", S)
        V = [x for x in S if x["edge"] >= 0.03]
        show("model value 3%+", V)
        P = [x for x in V if 1.6 <= x["price"] <= 2.3]
        show(" + price 1.60-2.30", P)
        F = [x for x in P if form(x)]
        show(" + form L10>=70%, L5>=60%", F)
        show(" + one per player", dedupe(F))
        F2 = [x for x in V if form(x)]
        show("value + form (any price)", F2)
        F3 = [x for x in S if form(x) and 1.6 <= x["price"] <= 2.3]
        show("form + price only (no model)", F3)
print("\n\n==== filtered (value3+, 1.6-2.3, form), by edge band and time half")
US = [x for x in R if x["sport"] != "football"]
F = [x for x in US if x["edge"] >= 0.03 and 1.6 <= x["price"] <= 2.3 and form(x)]
for lo, hi in ((0.03, .08), (.08, .15), (.15, .25), (.25, 9)):
    show(f"edge {lo:.0%}-{hi:.0%}", [x for x in F if lo <= x["edge"] < hi])
kos = sorted(x["ko"] for x in F); mid = kos[len(kos)//2]
show("older half", [x for x in F if x["ko"] < mid]); show("newer half", [x for x in F if x["ko"] >= mid])
for a, b in ((0.6, 0.6), (0.7, 0.6), (0.8, 0.6), (0.7, 0.8), (0.8, 0.8)):
    show(f"form L10>={a:.0%} L5>={b:.0%}", [x for x in US if x["edge"] >= 0.03 and 1.6 <= x["price"] <= 2.3 and form(x, a, b)])
# daily shortlist: one per player, max 2 per game, top 8 per day by edge
def daily(b, cap=8, pergame=2, key="edge"):
    b = dedupe(b); out = []
    byday = collections.defaultdict(list)
    for x in b: byday[datetime.datetime.utcfromtimestamp(x["ko"] - 6*3600).date()].append(x)
    for d, xs in byday.items():
        xs.sort(key=lambda x: -x[key]); g = collections.Counter(); n = 0
        for x in xs:
            if n >= cap or g[x["ev"]] >= pergame: continue
            out.append(x); g[x["ev"]] += 1; n += 1
    return out
D = daily(F); show("DAILY SHORTLIST (top 8/day, 2/game)", D)
show("  older half", [x for x in D if x["ko"] < mid]); show("  newer half", [x for x in D if x["ko"] >= mid])
for sp in ("american-football", "basketball"):
    for ov in (True, False):
        show(f"  {sp} {'over' if ov else 'under'}", [x for x in D if x["sport"] == sp and x["over"] == ov])
D2 = daily([x for x in F if x["edge"] < 0.25]); show("DAILY, edge capped at 25%", D2)
# resample range
random.seed(1); days = collections.defaultdict(list)
for x in D: days[datetime.datetime.utcfromtimestamp(x["ko"]-6*3600).date()].append(x)
ks = list(days); res = []
for _ in range(2000):
    s = [x for k in random.choices(ks, k=len(ks)) for x in days[k]]
    res.append(roi(s)[2])
res.sort(); print(f"daily shortlist: {len(ks)} days, 90% range {res[100]:+.0%} to {res[1900]:+.0%}, P(ROI>0) {sum(r>0 for r in res)/len(res):.0%}")
