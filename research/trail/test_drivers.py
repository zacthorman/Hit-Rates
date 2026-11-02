"""Which pre-match causes predict a player's count beyond his own rate?

Poisson GLMs with an offset for minutes, fitted on the first 70% of games by
date and scored on the last 30%. Base: his own prior rate and the opposing
team's prior. Then add one candidate driver at a time and report the change
in out-of-sample log-likelihood per 1,000 player-games and the coefficient.
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import linear_sum_assignment

df = pd.read_parquet("pm.parquet")
df = df[(~df["sub"]) & (df["pos"] != "G") & (df["min"] >= 45) & (df["apps"] >= 5)].copy()

# One-to-one direct opponents from prior positions (Hungarian on mirrored distance)
pairs = {}
for eid, g in df[df["px"].notna()].groupby("eid"):
    h, a = g[g.side == "h"], g[g.side == "a"]
    if len(h) < 6 or len(a) < 6:
        continue
    hx, hy = h["px"].to_numpy(), h["py"].to_numpy()
    ax, ay = 100 - a["px"].to_numpy(), 100 - a["py"].to_numpy()
    cost = (hx[:, None] - ax[None, :]) ** 2 + (hy[:, None] - ay[None, :]) ** 2
    ri, ci = linear_sum_assignment(cost)
    for i, j in zip(ri, ci):
        pairs[h.index[i]] = a.index[j]
        pairs[a.index[j]] = h.index[i]
STATS = ["fouls", "fouled", "tackles", "shots", "sot", "dribbles", "touches", "lost", "interc", "duels"]
for k in STATS:
    df["m_r_" + k] = np.nan
    df["m_" + k] = np.nan
idx = list(pairs)
opp = [pairs[i] for i in idx]
for k in STATS:
    df.loc[idx, "m_r_" + k] = df.loc[opp, "r_" + k].to_numpy()
    df.loc[idx, "m_" + k] = df.loc[opp, k].to_numpy()
df.loc[idx, "m_name"] = df.loc[opp, "name"].to_numpy()
df.loc[idx, "m_pos"] = df.loc[opp, "pos"].to_numpy()
df["home"] = (df.side == "h").astype(float)
df.to_parquet("pm_pairs.parquet")
print("starter rows", len(df), "with a one-to-one direct opponent", df["m_name"].notna().sum())


def lg(x):
    return np.log(np.clip(x, 0.05, None))


# target stat -> (his own prior, opposing team prior, candidate drivers)
TESTS = {
    "fouled": ("r_fouled", "ot_Fouls", ["m_r_fouls", "m_r_tackles", "m_r_duels", "ot_Ball possession", "t_Ball possession"]),
    "fouls": ("r_fouls", "ota_Fouls", ["m_r_fouled", "m_r_dribbles", "m_r_touches", "ot_Ball possession", "t_Ball possession"]),
    "tackles": ("r_tackles", "ot_Ball possession", ["m_r_dribbles", "m_r_touches", "m_r_lost", "t_Ball possession"]),
    "shots": ("r_shots", "ota_Total shots", ["m_r_tackles", "m_r_interc", "m_r_duels", "t_Ball possession", "ot_Fouls"]),
}

out = []
for y, (own, oppt, cands) in TESTS.items():
    base_cols = [own, oppt, "home"]
    d = df.dropna(subset=[own, oppt]).copy()
    d = d[d["m_name"].notna()]
    d = d.sort_values("ts")
    cut = d["ts"].quantile(0.7)
    for c in [None] + cands:
        cols = base_cols + ([c] if c else [])
        dd = d.dropna(subset=cols)
        tr, te = dd[dd.ts <= cut], dd[dd.ts > cut]
        X = lambda f: sm.add_constant(pd.DataFrame({
            **{k: (lg(f[k]) if k != "home" else f[k]) for k in cols}}), has_constant="add")
        off = lambda f: np.log(f["min"] / 90.0)
        m = sm.GLM(tr[y], X(tr), family=sm.families.Poisson(), offset=off(tr)).fit()
        mu = m.predict(X(te), offset=off(te))
        ll = float(np.sum(te[y] * np.log(mu) - mu))
        if c is None:
            base_ll, n_te = ll, len(te)
            b = None
        out.append({"stat": y, "driver": c or "(base)", "n_train": len(tr), "n_test": len(te),
                    "coef": m.params.get(c) if c else np.nan,
                    "p": m.pvalues.get(c) if c else np.nan,
                    "gain_per_1000": (ll - base_ll) / len(te) * 1000 if c else 0.0,
                    "own_coef": m.params.get(own)})
res = pd.DataFrame(out)
pd.set_option("display.width", 200)
print(res.round(4).to_string())
res.to_csv("drivers.csv", index=False)
