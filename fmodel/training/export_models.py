"""Refit each line's model on train+validation with the validation-chosen
groups and tree count, then dump to plain JSON for a numpy-only scorer."""
import json, numpy as np, pandas as pd, lightgbm as lgb, sys
sys.argv = ["x", "none"]
import evaluate as E
F, G, PARAMS = E.F, E.G, E.PARAMS
OUT = "/home/claude/bt/export"
cats = list(F["comp_c"].cat.categories)
meta = {"comp_categories": [int(c) for c in cats], "lines": {}}
for s, ks in E.LINES.items():
    gs = E.AUTO[s]
    feats = sum((G[g] for g in gs), [])
    cov = F["c_" + s].astype(bool)
    for k in ks:
        y = (F["y_" + s] >= k).astype(int).values
        ok = F[f"b_{s}_{k}"].notna() & cov
        tr, va = ok & (F.split == "train"), ok & (F.split == "val")
        m, _, _ = E.fit_predict(F, feats, y, tr, va, va)
        nt = m.best_iteration or m.current_iteration()
        full = ok & F.split.isin(["train", "val"])
        dtr = lgb.Dataset(F.loc[full, feats], y[full], categorical_feature=[f for f in feats if f == "comp_c"] or "auto")
        m2 = lgb.train(PARAMS, dtr, nt)
        name = f"{s}_{k}"
        json.dump(m2.dump_model(), open(f"{OUT}/{name}.json", "w"))
        te = ok & (F.split == "oos")
        np.save(f"{OUT}/{name}_check.npy", m2.predict(F.loc[te, feats].head(3000)))
        meta["lines"][name] = {"stat": s, "k": k, "groups": gs, "features": feats, "trees": nt,
                               "train_rows": int(full.sum())}
        print(name, nt, len(feats), flush=True)
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)
