"""Which extra data improves the best-selections pool? Each signal is tested on
(1) Paddy's real prices since 13 Oct and (2) the long back-test on unseen games
(stand-in lines: compare the two halves of a split, not the level).

Pool: model edge 3%+ and price 1.60 to 2.30 (before the form filter), so form is
tested like everything else. A signal is 'for' when it points the same way as
the bet (over or under). Continuous signals split at their median in the pool.
"""
import sys, json, pickle, collections, datetime, random
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pplog, ruletrack
OUT = ROOT / "research" / "selbt"
SP = {"basketball": "nba", "american-football": "nfl"}
META = {s: json.loads((ROOT / "usmodel" / f"{s}_meta.json").read_text()) for s in ("nba", "nfl")}
VOL = {"nba": "usage", "nfl": "targets"}

def f(x, k):
    try:
        v = float(x.get(k)); return None if np.isnan(v) else v
    except (TypeError, ValueError):
        return None

def signals(x, sport, tgt, line, over, form10, form5):
    """name -> (value, kind). kind 'dir': a higher value favours the OVER
    (split at the median within sport, stat and side). kind 'side': a higher
    value favours this bet whichever side it is. kind 'flag': +1 / -1."""
    o = {}
    o["form 7/10 + 3/5"] = (1 if (form10 >= .7 and form5 >= .6) else -1, "flag")
    o["form last 10 rate"] = (form10, "side")
    o["form last 5 rate"] = (form5, "side")
    ew = f(x, f"{tgt}_ew")
    if ew is not None: o["weighted average v line"] = ((ew - line) / max(line, 1), "dir")
    m3, m10 = f(x, f"{tgt}_m3"), f(x, f"{tgt}_m10")
    if m3 is not None and m10 is not None: o["last 3 v last 10 (stat)"] = ((m3 - m10) / max(m10, 1), "dir")
    a, b = f(x, "mins_m3"), f(x, "mins_m10")
    if a is not None and b is not None and sport == "nba": o["minutes trend"] = (a - b, "dir")
    v = VOL[sport]; a, b = f(x, f"{v}_m3"), f(x, f"{v}_m10")
    if a is not None and b is not None: o[f"{v} trend"] = (a - b, "dir")
    mk = f(x, "miss_key")
    if mk is not None: o["team-mates missing"] = (mk, "dir")
    oc = f(x, f"oc_{tgt}")
    if oc is not None: o["opponent concedes to his position"] = (oc, "dir")
    b2b = f(x, "b2b")
    if b2b is not None and sport == "nba": o["back-to-back"] = (-1 if b2b else 1, "dir")
    dr = f(x, "days_rest")
    if dr is not None: o["days rest"] = (dr, "dir")
    e = f(x, "elo_diff")
    if e is not None: o["mismatch |elo| (blowout risk)"] = (-abs(e), "dir")
    if e is not None: o["his team stronger (elo)"] = (e, "dir")
    h = f(x, "home")
    if h is not None: o["home"] = (1 if h else -1, "dir")
    sr = f(x, "start_rate")
    if sr is not None: o["starter"] = (sr, "dir")
    h2 = f(x, f"h2h_{tgt}"); hn = f(x, "h2h_n")
    if h2 is not None and hn: o["head to head v line"] = ((h2 - line) / max(line, 1), "dir")
    return o

def roi(b):
    return sum(x["price"] - 1 if x["win"] else -1 for x in b) / len(b) if b else float("nan")

def favour(pool):
    """Per bet and signal: True if the signal points the bet's way."""
    groups = collections.defaultdict(list)
    for p in pool:
        for k, (v, kind) in p["sig"].items():
            if kind == "dir":
                groups[(k, p["sport"], p["tgt"], p["over"])].append(v)
            elif kind == "side":
                groups[(k, p["sport"])].append(v)
    med = {g: float(np.median(v)) for g, v in groups.items()}
    for p in pool:
        p["fav"] = {}
        for k, (v, kind) in p["sig"].items():
            if kind == "flag":
                p["fav"][k] = v > 0
            elif kind == "side":
                p["fav"][k] = v > med[(k, p["sport"])]
            else:
                m = med[(k, p["sport"], p["tgt"], p["over"])]
                if v == m: continue
                p["fav"][k] = (v > m) if p["over"] else (v < m)

def table(pool, title):
    favour(pool)
    print(f"\n### {title}: {len(pool)} bets, {len({p['game'] for p in pool})} games, ROI {roi(pool):+.1%}\n")
    print("| signal | bets it favours | ROI when it agrees | ROI when it disagrees | difference |")
    print("|---|---|---|---|---|")
    keys = sorted({k for p in pool for k in p["fav"]})
    res = []
    for k in keys:
        yes = [p for p in pool if p["fav"].get(k) is True]; no = [p for p in pool if p["fav"].get(k) is False]
        if len(yes) < 15 or len(no) < 15: continue
        res.append((roi(yes) - roi(no), k, len(yes), len(yes) + len(no), roi(yes), roi(no)))
    for d, k, ny, nh, ry, rn in sorted(res, reverse=True):
        print(f"| {k} | {ny}/{nh} | {ry:+.1%} | {rn:+.1%} | {d:+.1%} |")
    return {k: d for d, k, *_ in res}

def real_pool():
    hist = ruletrack._hist_model()
    Fs = {s: pickle.load(open(OUT / f"{s}_F.pkl", "rb")) for s in ("nba", "nfl")}
    idx = {}
    for s, F in Fs.items():
        for rec in F.to_dict("records"):
            idx[(s, rec["match"], pplog._norm(rec["name"]))] = rec
    pool = []
    for r in pplog.all_rows():
        if r.get("result") not in ("win", "lose") or r["sport"] not in SP: continue
        sp = SP[r["sport"]]
        fs = r.get("first") or {}; pr = fs.get("price")
        if not pr or not (1.6 <= pr <= 2.3) or not r.get("n10") or r["n10"] < 6: continue
        m = ruletrack._model(r, hist)
        if m is None or m * pr - 1 < .03: continue
        tgt = next((t for t, mm in META[sp]["targets"].items() if mm["page_stat"] == r["stat"]), None)
        x = idx.get((sp, r["event_id"], pplog._norm(r["player"])))
        if tgt is None or x is None: continue
        sig = signals(x, sp, tgt, r["line"], bool(r["over"]), r["k10"] / r["n10"], r["k5"] / max(r["n5"], 1))
        last = (r.get("last") or {}).get("price")
        if last: sig["price shortened after logging"] = (1 if last < pr else -1, "flag")
        sig["he is listed questionable"] = (1 if (r.get("injury") or "Active").lower() != "active" else -1, "flag")
        sig["model edge size"] = (m * pr - 1, "side")
        pool.append(dict(tgt=tgt, price=pr, win=r["result"] == "win", game=r["event_id"], sig=sig, sport=sp, over=bool(r["over"])))
    return pool

def long_pool():
    Fs = {s: pickle.load(open(OUT / f"{s}_F.pkl", "rb")).set_index(["match", "pid"]) for s in ("nba", "nfl")}
    FIT = {"points","rebounds","assists","threes","steals","pra","pr","pa","ra","rush_yds","rec_yds","rec"}
    pool = []
    for sp in ("nba", "nfl"):
        for r in pickle.load(open(OUT / f"{sp}_v2.pkl", "rb")):
            if r["tgt"] not in FIT: continue
            try: x = Fs[sp].loc[(r["match"], r["pid"])]
            except KeyError: continue
            x = (x.iloc[0] if x.ndim > 1 else x).to_dict()
            for over in (True, False):
                pr = 1.91 if over else 1.84
                p = r["p_over"] if over else 1 - r["p_over"]
                if p * pr - 1 < .03: continue
                k10 = r["k10o"] if over else r["n10"] - r["k10o"]; k5 = r["k5o"] if over else r["n5"] - r["k5o"]
                sig = signals(x, sp, r["tgt"], r["line"], over, k10 / r["n10"], k5 / r["n5"])
                sig["model edge size"] = (p * pr - 1, "side")
                pool.append(dict(tgt=r["tgt"], price=pr, win=(r["y"] > r["line"]) == over, game=r["match"], sig=sig, sport=sp, over=over))
    return pool

if __name__ == "__main__":
    real = real_pool()
    a = table(real, "Paddy's real prices, 13-25 Oct, NBA + NFL")
    for sp in ("nba", "nfl"):
        table([p for p in real if p["sport"] == sp], f"real prices, {sp.upper()} only")
    lp = long_pool()
    b = table(lp, "Long back-test, unseen games, stand-in lines (compare columns, not the level)")
    print("\n### Agreement: difference on real prices v long back-test\n")
    for k in sorted(set(a) & set(b), key=lambda k: -(a[k] + b[k])):
        tag = "both help" if a[k] > 0 and b[k] > 0 else ("both hurt" if a[k] < 0 and b[k] < 0 else "disagree")
        print(f"- {k}: real {a[k]:+.1%}, long {b[k]:+.1%} ({tag})")
