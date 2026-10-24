"""NFL game-script test. Current features vs current + script features, same
split, same model, same spread. Per-row out-of-sample log loss at the three
lines; bootstrap by game (players in one game move together); Holm across
the 12 markets. Adopt only if validation improves and the Holm-adjusted
out-of-sample gain is significant at 5%."""
import json, sys
import numpy as np, pandas as pd
sys.argv = ["evaluate_us.py", "nfl", "ablate"]
sys.path.insert(0, "/home/claude/us/usmodel/training")
import evaluate_us as E

D = "/home/claude/usbt/data"
S = pd.read_parquet(f"{D}/nfl_features_s.parquet")
SC = ["s_exp_margin", "s_exp_plays", "s_script_push", "s_short_week", "s_bye"]
F = E.F.merge(S[["match", "team"] + SC].drop_duplicates(["match", "team"]), on=["match", "team"], how="left")
assert len(F) == len(E.F)
E.F = F
print("script coverage", F[SC[0]].notna().mean().round(3))
META = json.load(open("/home/claude/us/usmodel/nfl_meta.json"))["targets"]
rng = np.random.default_rng(11)
B = 2000
out = []
for s in E.TARGETS:
    E.CUR["s"] = s
    ok = E.eligible(s).values
    y = np.clip(F[f"y_{s}"].astype(float).values, 0, None)
    tr, va, te = ok & (F.split == "train").values, ok & (F.split == "val").values, ok & (F.split == "oos").values
    base = [c for c in META[s]["features"] if c in F.columns]
    lines = E.lines_for(s)
    res = {}
    for name, feats in (("cur", base), ("script", base + SC)):
        m = E.fit(feats, y, tr, va)
        mv, mt = E.predict(m, va, feats), E.predict(m, te, feats)
        sp = E.Spread(y[va], mv, s in E.YARDS)
        rows_v, rows_t = [], []
        for L in lines:
            Lv, Lt = np.asarray(L)[va], np.asarray(L)[te]
            pv, pt = sp.p_over(mv, Lv), sp.p_over(mt, Lt)
            ov, ot = (y[va] > Lv).astype(float), (y[te] > Lt).astype(float)
            pv, pt = np.clip(pv, 1e-4, 1 - 1e-4), np.clip(pt, 1e-4, 1 - 1e-4)
            rows_v.append(-(ov * np.log(pv) + (1 - ov) * np.log(1 - pv)))
            rows_t.append(-(ot * np.log(pt) + (1 - ot) * np.log(1 - pt)))
        res[name] = dict(v=np.mean(rows_v, 0), t=np.mean(rows_t, 0),
                         dev_v=E.poisson_dev(y[va], mv), dev_t=E.poisson_dev(y[te], mt), it=m.best_iteration)
    gain_v = res["cur"]["v"].mean() - res["script"]["v"].mean()
    d = res["cur"]["t"] - res["script"]["t"]
    g = F.match.values[te]
    dfm = pd.DataFrame({"g": g, "d": d}).groupby("g").d.agg(["sum", "count"])
    sums, cnts = dfm["sum"].values, dfm["count"].values
    idx = rng.integers(0, len(sums), (B, len(sums)))
    boot = sums[idx].sum(1) / cnts[idx].sum(1)
    p = float((boot <= 0).mean())
    out.append(dict(target=s, n_val=int(va.sum()), n_oos=int(te.sum()), games_oos=len(sums),
                    ll_cur_oos=res["cur"]["t"].mean(), ll_script_oos=res["script"]["t"].mean(),
                    gain_val=gain_v, gain_oos=d.mean(), gain_oos_pct=100 * d.mean() / res["cur"]["t"].mean(),
                    ci_lo=np.quantile(boot, .025), ci_hi=np.quantile(boot, .975), p=p,
                    dev_cur=res["cur"]["dev_t"], dev_script=res["script"]["dev_t"],
                    trees_cur=res["cur"]["it"], trees_script=res["script"]["it"]))
    print({k: (round(v, 5) if isinstance(v, float) else v) for k, v in out[-1].items()}, flush=True)
R = pd.DataFrame(out).sort_values("p")
m = len(R)
R["p_holm"] = np.minimum(1, np.maximum.accumulate([(m - i) * pv for i, pv in enumerate(R.p)]))
R["adopt"] = (R.gain_val > 0) & (R.p_holm < 0.05)
R["adopt_unadjusted"] = (R.gain_val > 0) & (R.ci_lo > 0)
R.to_csv(f"{D}/nfl_gs_eval_compact.csv", index=False)
print(R[["target", "n_oos", "games_oos", "gain_val", "gain_oos_pct", "ci_lo", "ci_hi", "p", "p_holm", "adopt", "adopt_unadjusted"]].round(5).to_string())
