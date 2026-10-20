import sys, json, warnings
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
warnings.filterwarnings("ignore")
D = "/home/claude/bt/data"
LINES = {"shots": (1, 2, 3), "sot": (1, 2), "fouls": (1, 2), "fouled": (1, 2, 3),
         "tackles": (1, 2, 3), "goals": (1,), "assists": (1,)}
TRAIN_END = pd.Timestamp("2026-04-01").timestamp()
VAL_END = pd.Timestamp("2026-07-01").timestamp()

F = pd.read_parquet(f"{D}/features.parquet")
B = pd.read_parquet(f"{D}/baseline.parquet")
F = F.merge(B, on=["match", "pid"], how="left")
F["pos_c"] = F.pos.map({"G": 0, "D": 1, "M": 2, "F": 3})
F["comp_c"] = F.comp.fillna(-1).astype(int).astype("category")
F["split"] = np.where(F.ts < TRAIN_END, "train", np.where(F.ts < VAL_END, "val", "oos"))

ID = {"match", "ts", "pid", "name", "team", "opp", "pos", "comp", "split", "month"}
cols = [c for c in F.columns if c not in ID and not c.startswith(("y_", "c_", "b_", "h_"))]
G = {
 "form": [c for c in cols if any(c.startswith(s + "_") for s in
          ["shots","sot","fouls","fouled","tackles","goals","assists","xg","xa","keypass","dribbles","touches",
           "intercepts","duelwon","recoveries","crosses","passes","dispossessed","aerialwon","challengelost","clearances"])]
         + ["n", "start_rate", "mins_avg5", "days_rest", "pos_c", "depth", "lat", "linesize", "att_idx", "def_idx", "home"],
 "team_style": [c for c in cols if c.startswith(("tf_", "ta_")) or c == "t_n"],
 "opp_style": [c for c in cols if c.startswith(("otf_", "ota_")) or c == "ot_n"],
 "strength_league": ["elo_diff", "lg_fouls", "comp_c"],
 "pos_concession": [c for c in cols if c.startswith("oc_")],
 "partners": ["mate_att", "mate_def", "mate_fouls90", "def_share_line", "att_minus_mates"],
 "matchup": [c for c in cols if c.startswith("vs_")],
 "h2h": [c for c in cols if c.startswith("h2h_")],
}
ORDER = list(G)
PARAMS = dict(objective="binary", learning_rate=0.03, num_leaves=31, min_data_in_leaf=200,
              feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=7)


def fit_predict(df, feats, y, tr, va, te):
    dtr = lgb.Dataset(df.loc[tr, feats], y[tr], categorical_feature=[f for f in feats if f == "comp_c"] or "auto")
    dva = lgb.Dataset(df.loc[va, feats], y[va], reference=dtr)
    m = lgb.train(PARAMS, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    return m, m.predict(df.loc[va, feats]), m.predict(df.loc[te, feats])


def ll(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return log_loss(y, p, labels=[0, 1])


def auto_groups():
    """Pick feature groups per stat on the VALIDATION period only: keep a group
    if, averaged over that stat's lines, adding it lowered validation log loss."""
    rows = [json.loads(l) for l in open(f"{D}/ablate.log") if l.startswith("{")]
    out = {}
    for s in LINES:
        rs = [r for r in rows if r["market"].split()[0] == s]
        keep = ["form"]
        for i, g in enumerate(ORDER[1:], 1):
            gain = np.mean([r["val+" + ORDER[i - 1]] - r["val+" + g] for r in rs])
            if gain > 0:
                keep.append(g)
        out[s] = keep
    return out


AUTO = auto_groups()


def main(mode):
    res = []
    imps = {}
    for s, ks in LINES.items():
        cov = F["c_" + s].astype(bool)
        for k in ks:
            y = (F["y_" + s] >= k).astype(int).values
            base_ok = F[f"b_{s}_{k}"].notna()
            tr = (F.split == "train") & cov & base_ok
            va = (F.split == "val") & cov & base_ok
            te = (F.split == "oos") & cov & base_ok
            row = {"market": f"{s} {k}+", "n_oos": int(te.sum()), "rate_oos": y[te].mean()}
            # baseline: site model and raw hit rate (smoothed)
            row["site"] = ll(y[te], F.loc[te, f"b_{s}_{k}"])
            # Fair baseline: the site's own chance, recalibrated (Platt) on the
            # training split only, so calibration alone is not counted as gain.
            from sklearn.linear_model import LogisticRegression
            lo = lambda q: np.log(np.clip(q, 1e-4, 1 - 1e-4) / (1 - np.clip(q, 1e-4, 1 - 1e-4)))
            pl = LogisticRegression(C=1e6).fit(lo(F.loc[tr, f"b_{s}_{k}"].values).reshape(-1, 1), y[tr])
            site_fair = pl.predict_proba(lo(F.loc[te, f"b_{s}_{k}"].values).reshape(-1, 1))[:, 1]
            row["site_fair"] = ll(y[te], site_fair)
            if mode != "ablate":
                F.loc[te, f"sf_{s}_{k}"] = site_fair
            h = F.loc[te, f"h_{s}_{k}"].fillna(y[tr].mean())
            row["hitrate"] = ll(y[te], 0.8 * h + 0.2 * y[tr].mean())
            row["base_rate"] = ll(y[te], np.full(te.sum(), y[tr].mean()))
            if mode == "ablate":
                feats = []
                for g in ORDER:
                    feats = feats + G[g]
                    _, pv, pt = fit_predict(F, feats, y, tr, va, te)
                    row["val+" + g] = ll(y[va], pv)
                    row["oos+" + g] = ll(y[te], pt)
            else:
                if mode == "auto":
                    gs = AUTO[s]
                else:
                    gs = mode.split(",")
                row["groups"] = "+".join(gs)
                feats = sum((G[g] for g in gs), [])
                m, pv, pt = fit_predict(F, feats, y, tr, va, te)
                row["new"] = ll(y[te], pt)
                row["new_val"] = ll(y[va], pv)
                row["brier_site"] = brier_score_loss(y[te], F.loc[te, f"b_{s}_{k}"])
                row["brier_new"] = brier_score_loss(y[te], pt)
                row["auc_site"] = roc_auc_score(y[te], F.loc[te, f"b_{s}_{k}"])
                row["auc_new"] = roc_auc_score(y[te], pt)
                F.loc[te, f"p_{s}_{k}"] = pt
                imp = pd.Series(m.feature_importance("gain"), index=feats)
                imps[f"{s} {k}+"] = (imp / imp.sum()).sort_values(ascending=False).head(15).round(3).to_dict()
            res.append(row)
            print(json.dumps({k2: (round(v, 4) if isinstance(v, float) else v) for k2, v in row.items()}), flush=True)
    R = pd.DataFrame(res)
    R.to_csv(f"{D}/results_{mode.replace(',', '+')}.csv", index=False)
    if imps:
        json.dump(imps, open(f"{D}/importance.json", "w"), indent=1)
        F[[c for c in F.columns if c.startswith(("p_", "y_", "b_", "c_", "sf_"))] + ["match", "pid", "name", "split", "ts", "pos"]].loc[F.split == "oos"].to_parquet(f"{D}/oos_preds.parquet")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ablate")
