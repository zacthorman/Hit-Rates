"""Long back-test of the 'best selections' filter on games the models never saw.

    python research/selbt.py prep nba|nfl      # feature table + form, cached in research/selbt/
    python research/selbt.py train nba|nfl [targets]   # train-only models, scored on out-of-sample games
    python research/selbt.py report            # the selections, their record

Models are refitted on games before the validation end (NFL 1 Dec 2025, NBA
1 Apr 2026) with the production settings and tree count; everything after is
out of sample. There are no historical bookmaker lines, so each player-game
gets the line a bookmaker would roughly hang: floor(last-10 median) + 0.5,
both sides, priced at PRICE (Paddy's usual main-line price). October's real
Paddy lines check how close that stand-in is.
"""
import sys, json, gzip, pickle
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "research" / "selbt"
OUT.mkdir(exist_ok=True)
VAL_END = {"nfl": pd.Timestamp("2025-12-01").timestamp(), "nba": pd.Timestamp("2026-04-01").timestamp()}


def prep(sport):
    import usmodel_weekly as W
    F, P = W.table(sport)
    meta = json.loads((ROOT / "usmodel" / f"{sport}_meta.json").read_text())
    pc = meta.get("pos_codes")
    F["pos_c"] = F.pos.map(pc).fillna(-1) if pc else F.pos.astype("category").cat.codes
    tg = [t for t in meta["targets"] if t in P.columns]
    played = P[(P.mins > 0)] if sport == "nba" and "mins" in P else (P[P.has_stats == 1] if "has_stats" in P else P)
    played = played.sort_values("ts")
    # last 10 values of each target before this game, as a list
    hist = {}
    for t in tg:
        hist[t] = {}
    for pid, g in played.groupby("pid"):
        ms = g.match.values
        for t in tg:
            v = g[t].astype(float).values
            for i, m in enumerate(ms):
                hist[t][(m, pid)] = v[max(0, i - 10):i][::-1].tolist()  # newest first
    F = F.merge(P[["match", "pid"] + tg], on=["match", "pid"], how="left", suffixes=("", "_y"))
    for t in tg:
        col = t + "_y" if t + "_y" in F else t
        F["y_" + t] = F[col]
        F["h_" + t] = [hist[t].get((m, p), []) for m, p in zip(F.match, F.pid)]
    pickle.dump(F, open(OUT / f"{sport}_F.pkl", "wb"))
    print(sport, len(F), "rows", tg)


def train(sport, only=None):
    import lightgbm as lgb
    import usmodel_live as L
    import usmodel_weekly as W
    F = pickle.load(open(OUT / f"{sport}_F.pkl", "rb"))
    meta = json.loads((ROOT / "usmodel" / f"{sport}_meta.json").read_text())
    res = []
    for t, m in meta["targets"].items():
        if only and t not in only or "y_" + t not in F:
            continue
        ok = W.eligible(F, t, m) & F["y_" + t].notna()
        S = F[ok]
        X = S.reindex(columns=m["features"]).astype(float).values
        y = np.clip(S["y_" + t].astype(float).values, 0, None)
        base = np.clip(S[m["base"]].astype(float).fillna(0).values, 0.05, None)
        tr = S.ts.values < VAL_END[sport]
        ntrees = len(json.load(gzip.open(ROOT / "usmodel" / f"{sport}_{t}.json.gz", "rt"))["tree_info"])
        prm = dict(objective="poisson", learning_rate=0.03, num_leaves=15, min_data_in_leaf=100,
                   feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=7)
        b = lgb.train(prm, lgb.Dataset(X[tr], y[tr], init_score=np.log(base[tr])), ntrees)
        te = ~tr
        mu = base[te] * np.exp(b.predict(X[te], raw_score=True))
        Te = S[te]
        for i, (r, mu_i) in enumerate(zip(Te.itertuples(index=False), mu)):
            h = getattr(r, "h_" + t)
            if len(h) < 6:
                continue
            med = float(np.median(h))
            line = np.floor(med) + 0.5
            if t == "td":
                line = 0.5
            po = L.calibrate(L.p_over(m["spread"], float(mu_i), line), m["cal"])
            hv = np.array(h)
            y_i = getattr(r, "y_" + t)
            res.append(dict(sport=sport, tgt=t, stat=m["page_stat"], match=r.match, pid=r.pid, name=r.name,
                            ts=r.ts, line=line, mu=float(mu_i), p_over=po,
                            k10o=int((hv > line).sum()), n10=len(hv), k5o=int((hv[:5] > line).sum()), n5=min(5, len(hv)),
                            y=float(y_i)))
        print(f"{sport} {t}: {int(te.sum())} oos rows, {ntrees} trees", flush=True)
    old = []
    f = OUT / f"{sport}_scored.pkl"
    if f.exists() and only:
        old = [r for r in pickle.load(open(f, "rb")) if r["tgt"] not in only]
    pickle.dump(old + res, open(f, "wb"))
    print(len(old + res), "scored rows")


if __name__ == "__main__":
    cmd, *a = sys.argv[1:]
    if cmd == "prep":
        prep(a[0])
    elif cmd == "train":
        train(a[0], set(a[1:]) or None)
