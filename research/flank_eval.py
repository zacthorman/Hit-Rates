"""Do flank and involvement features improve the backtested player model?
fmodel's own split (train < Apr 2026, val Apr-Jun, oos Jul+). Per line: current features vs
+flank, +usage, +both. Per-row oos log loss; bootstrap by match (2000); Holm across lines per
variant. Adopt only if val improves and Holm p < 0.05."""
import json, sys, warnings
import numpy as np, pandas as pd, lightgbm as lgb
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/bt/code/flank")
import flank
D = "/home/claude/bt/data"
META = json.load(open("/home/claude/bt/code/fmodel/meta.json"))
TRAIN_END, VAL_END = pd.Timestamp("2026-04-01").timestamp(), pd.Timestamp("2026-07-01").timestamp()
PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=31, min_data_in_leaf=200, feature_fraction=0.7,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=7)
P = pd.read_parquet(f"{D}/players.parquet"); M = pd.read_parquet(f"{D}/matches.parquet")
TR, PR = flank.build(P, M)
TR.to_parquet(f"{D}/flank_team.parquet"); PR.to_parquet(f"{D}/flank_player.parquet")
F = pd.read_parquet(f"{D}/features.parquet")
F = flank.player_features(F, TR, PR)
F["pos_c"] = F.pos.map({"G": 0, "D": 1, "M": 2, "F": 3})
F["comp_c"] = F.comp.fillna(-1).astype(int).astype("category")
F["split"] = np.where(F.ts < TRAIN_END, "train", np.where(F.ts < VAL_END, "val", "oos"))
FL = [c for c in F.columns if c.startswith("f_")]
US = ["u_touch", "u_shots", "u_keypass", "u_fouled"]
print("coverage", F[FL + US].notna().mean().round(2).to_dict(), flush=True)
rng = np.random.default_rng(5)
def rowll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4); return -(y * np.log(p) + (1 - y) * np.log(1 - p))
res = []
for key, ln in META["lines"].items():
    s, k = ln["stat"], ln["k"]
    if f"y_{s}" not in F: continue
    cov = F["c_" + s].astype(bool) if "c_" + s in F else pd.Series(True, index=F.index)
    y = (F["y_" + s] >= k).astype(int).values
    base = [f for f in ln["features"] if f in F.columns]
    tr, va, te = [((F.split == x) & cov).values for x in ("train", "val", "oos")]
    out = {}
    for name, feats in (("cur", base), ("flank", base + FL), ("usage", base + US), ("both", base + FL + US)):
        dtr = lgb.Dataset(F.loc[tr, feats], y[tr]); dva = lgb.Dataset(F.loc[va, feats], y[va], reference=dtr)
        m = lgb.train(PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
        out[name] = (rowll(y[va], m.predict(F.loc[va, feats])).mean(), rowll(y[te], m.predict(F.loc[te, feats])))
    g = F.match.values[te]
    for v in ("flank", "usage", "both"):
        d = out["cur"][1] - out[v][1]
        dfm = pd.DataFrame({"g": g, "d": d}).groupby("g").d.agg(["sum", "count"])
        S, C = dfm["sum"].values, dfm["count"].values
        idx = rng.integers(0, len(S), (2000, len(S)))
        boot = S[idx].sum(1) / C[idx].sum(1)
        res.append(dict(line=f"{s} {k}+", variant=v, n_oos=int(te.sum()), gain_val=out["cur"][0] - out[v][0],
                        gain_oos_pct=100 * d.mean() / out["cur"][1].mean(), ci_lo=np.quantile(boot, .025),
                        p=float((boot <= 0).mean())))
        print({k2: (round(x, 5) if isinstance(x, float) else x) for k2, x in res[-1].items()}, flush=True)
R = pd.DataFrame(res)
for v, g in R.groupby("variant"):
    g = g.sort_values("p"); m = len(g)
    R.loc[g.index, "p_holm"] = np.minimum(1, np.maximum.accumulate([(m - i) * p for i, p in enumerate(g.p)]))
R["adopt"] = (R.gain_val > 0) & (R.p_holm < 0.05)
R.to_csv(f"{D}/flank_results.csv", index=False)
print(R.sort_values(["variant", "p"]).round(4).to_string())
