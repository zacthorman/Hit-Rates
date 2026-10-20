"""The site's current player model, replayed: model.price_player on the
player's last 38 appearances (45+ minutes), adjustment 1, calibrated as the
site calibrates. Plus the plain last-10 hit rate, the number the page shows."""
import sys
from collections import defaultdict
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/bt/src")
import model

D = "/home/claude/bt/data"
LINES = {"shots": (1, 2, 3), "sot": (1, 2), "fouls": (1, 2), "fouled": (1, 2, 3),
         "tackles": (1, 2, 3), "goals": (1,), "assists": (1,)}
COV = {"shots", "sot", "fouls", "fouled", "tackles"}

P = pd.read_parquet(f"{D}/players.parquet")
F = pd.read_parquet(f"{D}/features.parquet")[["match", "pid"]]
want = set(zip(F.match, F.pid))
cov = pd.read_parquet(f"{D}/features.parquet", columns=["match", "pid"] + [f"c_{s}" for s in COV])
# per (match, team) coverage from features is only for starters; recompute simply:
P = P[P.mins > 0].sort_values(["ts", "match"])
# coverage: cov_* from build.py, the same rule features.py uses
hist = defaultdict(list)
out = []
for mid, pm in P.groupby("match", sort=False):
    for r in pm.itertuples(index=False):
        if (mid, r.pid) in want:
            h = hist[r.pid]
            row = {"match": mid, "pid": r.pid}
            for s, ks in LINES.items():
                apps = [{"value": x[s], "minutes": x["mins"]} for x in h[-38:]
                        if x["mins"] >= 45 and (s not in COV or x["cov_" + s])]
                vals10 = [a["value"] for a in apps[-10:]]
                for k in ks:
                    row[f"b_{s}_{k}"] = model.price_player(apps, k - 0.5, True, 1.0, None, "football")["p"] if apps else np.nan
                    row[f"h_{s}_{k}"] = np.mean([v >= k for v in vals10]) if vals10 else np.nan
            out.append(row)
    for r in pm.itertuples(index=False):
        d = {s: getattr(r, s) for s in LINES}
        d["mins"] = r.mins
        for s in COV:
            d["cov_" + s] = getattr(r, "cov_" + s)
        hist[r.pid].append(d)
B = pd.DataFrame(out)
B.to_parquet(f"{D}/baseline.parquet")
print(B.shape)
