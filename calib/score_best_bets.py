"""Score the Football stats best-bets record: does the site's stated chance match what happened?"""
import json, sys, numpy as np, pandas as pd
d = json.load(open(sys.argv[1]))
rows = []
for b in d:
    if b["result"] not in ("win", "lose") or not b.get("fair"):
        continue
    l0 = b["legs"][0]
    raw = np.prod([l["hits"] / l["total"] for l in b["legs"] if l.get("total")]) if all(l.get("total") for l in b["legs"]) else np.nan
    rows.append({"cat": b["category"], "sport": b["sport"], "legs": len(b["legs"]), "said": 1 / b["fair"], "raw": raw,
                 "won": b["result"] == "win", "fixture": l0["event_id"], "stat": l0["stat"], "who": "player" if l0.get("player") else "team",
                 "day": pd.Timestamp(b["snapshot_at"], unit="s").date()})
t = pd.DataFrame(rows)
rng = np.random.default_rng(20261013)
fx = t["fixture"].unique()
groups = {f: g.index.to_numpy() for f, g in t.groupby("fixture")}

def boot(sub_idx_fn, B=2000):
    out = []
    for _ in range(B):
        pick = rng.choice(fx, len(fx))
        idx = np.concatenate([groups[f] for f in pick])
        s = t.loc[idx]
        s = sub_idx_fn(s)
        if len(s): out.append(s["won"].mean() - s["said"].mean())
    return np.percentile(out, [2.5, 97.5])

def line(name, s, fn):
    lo, hi = boot(fn)
    return {"group": name, "bets": len(s), "fixtures": s["fixture"].nunique(), "said": round(s["said"].mean(), 3),
            "hit": round(s["won"].mean(), 3), "gap": round(s["won"].mean() - s["said"].mean(), 3),
            "gap_95ci": f"{lo:+.3f} to {hi:+.3f}", "break_even_odds": round(1 / s["won"].mean(), 2) if s["won"].mean() > 0 else None,
            "site_fair_odds": round(1 / s["said"].mean(), 2)}

out = [line("ALL", t, lambda s: s)]
for c in sorted(t["cat"].unique()):
    out.append(line(f"type: {c}", t[t.cat == c], lambda s, c=c: s[s.cat == c]))
for c in sorted(t["sport"].unique()):
    out.append(line(f"sport: {c}", t[t.sport == c], lambda s, c=c: s[s.sport == c]))
for w in ("team", "player"):
    out.append(line(f"leg is: {w}", t[(t.who == w) & (t.legs == 1)], lambda s, w=w: s[(s.who == w) & (s.legs == 1)]))
bands = [(0, .55), (.55, .65), (.65, .75), (.75, .85), (.85, 1.01)]
for a, b in bands:
    m = (t.said >= a) & (t.said < b)
    if m.sum():
        out.append(line(f"said {a:.0%}-{min(b,1):.0%}", t[m], lambda s, a=a, b=b: s[(s.said >= a) & (s.said < b)]))
res = pd.DataFrame(out)
pd.set_option("display.width", 250)
print(res.to_string(index=False))
single = t[t.legs == 1].dropna(subset=["raw"])
brier = lambda p: float(((p - single["won"]) ** 2).mean())
print("\nSingles, Brier score (lower is better): site's stated chance", round(brier(single["said"]), 4),
      "| raw hit record", round(brier(single["raw"]), 4), "| flat base rate", round(brier(np.full(len(single), single["won"].mean())), 4))
print("raw record mean", round(single["raw"].mean(), 3), "site said", round(single["said"].mean(), 3), "hit", round(single["won"].mean(), 3))
print("days", t["day"].min(), "to", t["day"].max(), "settled bets", len(t))
by_stat = t[t.legs == 1].groupby("stat").agg(n=("won", "size"), said=("said", "mean"), hit=("won", "mean"))
by_stat["gap"] = by_stat.hit - by_stat.said
print(by_stat[by_stat.n >= 15].sort_values("gap").round(3).to_string())
res.to_csv("calibration.csv", index=False)
