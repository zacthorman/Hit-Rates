"""Score the models on Paddy Power's real, settled lines (pplog), out of sample.

    python3 ppcheck_us.py nba|nfl

Uses the train-only models (never saw these games), the validation-fitted
spread, calibration and blend from meta, and the site's own price_player
chance, at exactly the line Paddy offered. Reports log loss and what betting
the flagged value would have returned at Paddy's first-seen price.
"""
import json
import math
import sys
import unicodedata
import warnings
from collections import defaultdict

import lightgbm as lgb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/usbt/src")
import model  # noqa: E402

sys.argv = [sys.argv[0], sys.argv[1], "auto"]
import evaluate_us as E  # noqa: E402

SPORT = E.SPORT
SITE = {"nba": "basketball", "nfl": "american-football"}[SPORT]
meta = json.load(open(f"/home/claude/usbt/export/{SPORT}_meta.json"))
by_stat = {m["page_stat"]: (t, m) for t, m in meta["targets"].items()}
lg = lambda q: math.log(min(1 - 1e-4, max(1e-4, q)) / (1 - min(1 - 1e-4, max(1e-4, q))))
sg = lambda z: 1 / (1 + math.exp(-z))


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if c.isascii() and (c.isalpha() or c == " ")).lower().split())


def p_over(spread, mu, line):
    if spread["type"] == "ratio":
        b = min(3, max(0, int(np.searchsorted(spread["edges"], mu)) - 1))
        return float(np.mean(mu * np.asarray(spread["q"][b]) > line))
    from scipy import stats as sst
    size = spread["size"]
    return float(1 - sst.nbinom.cdf(math.floor(line), size, size / (size + mu)))


rows = [json.loads(l) for l in open("/mnt/user-data/uploads/Cowork Base/03 Code Projects/Football stats/pplog/2026-10.jsonl")]
rows = [r for r in rows if r["sport"] == SITE and r.get("result") in ("win", "lose") and r["stat"] in by_stat]
F = E.F
F["key"] = F.name.map(norm)
idx = {(m, k): i for i, (m, k) in enumerate(zip(F.match, F.key))}
P = E.P
models = {}
hist = defaultdict(list)
Pp = P[(P.mins > 0) if SPORT == "nba" else (P.has_stats == 1)].sort_values("ts")
if SPORT == "nfl":
    Pp = Pp.assign(mins=60.0, td=Pp.rush_td + Pp.rec_td)
by_pid = defaultdict(list)
for r in Pp.itertuples(index=False):
    by_pid[r.pid].append(r)
out = []
for r in rows:
    i = idx.get((r["event_id"], norm(r["player"])))
    if i is None:
        continue
    t, m = by_stat[r["stat"]]
    if t not in models:
        models[t] = lgb.Booster(model_file=f"/home/claude/usbt/export/oos_{SPORT}_{t}.txt")
    x = F.loc[[i], m["features"]].astype(float).values
    base = max(0.05, float(np.nan_to_num(F.loc[i, m["base"]])))
    mu = base * float(np.exp(models[t].predict(x, raw_score=True)[0]))
    line = r["line"] if r["line"] is not None else 0.5
    p_new = sg(m["cal"][0] + m["cal"][1] * lg(p_over(m["spread"], mu, line)))
    prev = [q for q in by_pid[F.pid[i]] if q.ts < F.ts[i]][-20:]
    if len(prev) < 3:
        continue
    apps = [{"value": float(getattr(q, t)), "minutes": float(q.mins)} for q in prev]
    p_site = model.price_player(apps, float(line), True, 1.0, None, SITE)["p"]
    sf = sg(m["site_cal"][0] + m["site_cal"][1] * lg(p_site))
    p_bl = sg(m["blend"][0] + m["blend"][1] * lg(p_new) + m["blend"][2] * lg(sf))
    over = r["over"]
    y = 1 if r["result"] == "win" else 0
    price = r["first"]["price"]
    f = (lambda q: q) if over else (lambda q: 1 - q)
    out.append(dict(stat=r["stat"], player=r["player"], line=line, over=over, price=price, y=y,
                    p_site=f(p_site), p_new=f(p_new), p_blend=f(p_bl), paddy=1 / price, mu=mu))
D = pd.DataFrame(out)


def ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


print(f"{SPORT}: {len(D)} settled Paddy lines matched (of {len(rows)})")
for k in ("paddy", "p_site", "p_new", "p_blend"):
    print(f"  {k:8} log loss {ll(D.y.values, D[k].values):.4f}  said {D[k].mean():.0%}  landed {D.y.mean():.0%}")
for k in ("p_site", "p_blend"):
    v = D[(D[k] >= 0.5) & (D[k] * D.price - 1 >= 0.05)]
    pl = float(((v.price - 1) * v.y - (1 - v.y)).sum())
    print(f"  value by {k:7}: {len(v):3} bets, won {v.y.mean() if len(v) else 0:.0%}, P/L {pl:+.1f}u, ROI {pl / max(1, len(v)):+.0%}")
D.to_csv(f"/home/claude/usbt/data/{SPORT}_ppcheck.csv", index=False)
print(D.groupby("stat").apply(lambda g: pd.Series({"n": len(g), "paddy": ll(g.y.values, g.paddy.values),
                                                   "site": ll(g.y.values, g.p_site.values),
                                                   "blend": ll(g.y.values, g.p_blend.values)})).round(3).to_string())
