"""Fit the pre-match trail adjustments and check them out of sample.
Writes trail_fit.json: per stat, coefficients on centred logs, applied as a
multiplier on top of the player's own expected count."""
import json, numpy as np, pandas as pd, statsmodels.api as sm
df = pd.read_parquet("pm_pairs.parquet")
def lg(x): return np.log(np.clip(x, 0.05, None))
SPECS = {
  "tackles": ("r_tackles", ["m_r_dribbles", "m_r_lost", "t_Ball possession", "ot_Ball possession"]),
  "fouled":  ("r_fouled",  ["m_r_tackles", "t_Ball possession", "ot_Fouls"]),
  "fouls":   ("r_fouls",   ["m_r_fouled", "t_Ball possession", "ota_Fouls"]),
  "shots":   ("r_shots",   ["m_r_interc", "t_Ball possession", "ota_Total shots"]),
}
fit = {}
for y, (own, xs) in SPECS.items():
    d = df.dropna(subset=[own] + xs + ["m_name"]).sort_values("ts")
    cut = d.ts.quantile(0.7); tr, te = d[d.ts <= cut], d[d.ts > cut]
    cen = {x: float(lg(tr[x]).mean()) for x in xs}
    def X(f, cols):
        return sm.add_constant(pd.DataFrame({"own": lg(f[own]), "home": f["home"], **{x: lg(f[x]) - cen[x] for x in cols}}), has_constant="add")
    off = lambda f: np.log(f["min"] / 90)
    b = sm.GLM(tr[y], X(tr, []), family=sm.families.Poisson(), offset=off(tr)).fit()
    m = sm.GLM(tr[y], X(tr, xs), family=sm.families.Poisson(), offset=off(tr)).fit()
    mb, mm = b.predict(X(te, []), offset=off(te)), m.predict(X(te, xs), offset=off(te))
    llb = float(np.sum(te[y] * np.log(mb) - mb)); llm = float(np.sum(te[y] * np.log(mm) - mm))
    # calibration of P(k+) by decile of the multiplier
    mult = mm / mb
    te = te.assign(mult=mult, pb=1 - np.exp(-mb), pm=1 - np.exp(-mm), hit=(te[y] >= 1).astype(int))
    te["q"] = pd.qcut(te.mult, 5, labels=False, duplicates="drop")
    cal = te.groupby("q").agg(n=("hit", "size"), mult=("mult", "mean"), base=("pb", "mean"), trail=("pm", "mean"), hit=("hit", "mean")).round(3)
    print(f"\n== {y}: out-of-sample gain {(llm - llb) / len(te) * 1000:+.1f} per 1,000 (n test {len(te)})")
    print({x: round(m.params[x], 4) for x in xs})
    print("1+ line by fifth of the trail multiplier (base model v with trail v landed):")
    print(cal.to_string())
    # refit on everything for live use
    a = d; cen_all = {x: float(lg(a[x]).mean()) for x in xs}
    mall = sm.GLM(a[y], sm.add_constant(pd.DataFrame({"own": lg(a[own]), "home": a["home"], **{x: lg(a[x]) - cen_all[x] for x in xs}}), has_constant="add"),
                  family=sm.families.Poisson(), offset=np.log(a["min"] / 90)).fit()
    fit[y] = {"coef": {x: float(mall.params[x]) for x in xs}, "centre": cen_all,
              "gain_per_1000": round((llm - llb) / len(te) * 1000, 2), "n": int(len(a))}
json.dump(fit, open("trail_fit.json", "w"), indent=1)
