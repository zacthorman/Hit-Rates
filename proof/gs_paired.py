"""Is the game state's gain over M1 bigger than noise? Paired per row, clustered by day.

    python3 -B gs_backtest.py build && python3 -B proof/gs_paired.py .

Replays gs_backtest.py's walk-forward exactly (same windows, same fits, same
line at each side's own average) but keeps each row's log loss, so M2 - M1 can
be given a standard error. Rows on one day share matches, so the
error is clustered by day. z below -2 is a gain that would rarely be luck.
"""
import json, math, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, sys.argv[1])
import gs_backtest as G

def per_row(rows, stat, team):
    recs = [{**r["stats"][stat], "ts": r["ts"], **({"home": r["home"]} if team else {})} for r in rows if stat in r["stats"]]
    recs.sort(key=lambda r: r["ts"])
    ts = np.array([r["ts"] for r in recs]); cut0 = np.quantile(ts, 0.6)
    edges = np.quantile(ts[ts >= cut0], [0, .25, .5, .75, 1])
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        tr = [r for r in recs if r["ts"] < a]; te = [r for r in recs if a <= r["ts"] <= b]
        ytr = np.array([r["y"] for r in tr], float)
        loss = {}
        for k in ("M1", "M2"):
            bt = G.fit_poisson(G.design(tr, k), ytr)
            al = G.nb_alpha(ytr, np.exp(G.design(tr, k) @ bt))
            mu = np.exp(G.design(te, k) @ bt)
            l = []
            for r, m in zip(te, mu):
                kk = int(math.floor(r["own"])) + 1
                p = min(.999, max(.001, G.p_at_least(kk, m, al)))
                l.append(-math.log(p if r["y"] >= kk else 1 - p))
            loss[k] = np.array(l)
        for r, d in zip(te, loss["M2"] - loss["M1"]):
            out.append((int(r["ts"] // 86400), d))
    return out

m = json.loads(G.DATA.read_text()); m.sort(key=lambda x: (x["ts"], x["id"]))
T, P = G.team_rows(m), G.player_rows(m)
print("| Scope | Stat | n | M2 - M1 | SE (by day) | z | rows for 80% power |")
print("|---|---|---|---|---|---|---|")
for scope, rows, stats, team in (("team", T, G.TEAM_STATS, True), ("player", P, G.PLAYER_STATS, False)):
    for s in stats:
        o = per_row(rows, s, team)
        d = np.array([x[1] for x in o]); days = defaultdict(float)
        for k, v in o: days[k] += v
        g = np.array(list(days.values()))
        se = math.sqrt(len(g) * np.var(g, ddof=1)) / len(d)
        z = d.mean() / se
        need = f"{math.ceil(len(d) * (2.8 / abs(z)) ** 2):,}" if d.mean() < 0 else "n/a (no gain)"
        print(f"| {scope} | {s} | {len(d)} | {d.mean():+.4f} | {se:.4f} | {z:+.2f} | {need} |")
