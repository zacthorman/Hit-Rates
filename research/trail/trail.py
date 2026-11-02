"""After the fact: what was different in the games a line landed?

1. Rate ratios (Poisson, his own prior rate as the baseline) for in-game
   context: share of his minutes behind / ahead, team possession, momentum
   share, and what his direct opponent actually did that game.
2. Streak breaks: games where a 1+ line landed after 3+ straight misses,
   against his other misses: how the context differed.
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm

df = pd.read_parquet("pm_pairs.parquet")
df = df[df["gs_level"].notna() & df["poss"].notna()].copy()
on = df["gs_level"] + df["gs_ahead"] + df["gs_behind"]
df["sh_behind"] = df["gs_behind"] / on.clip(lower=1)
df["sh_ahead"] = df["gs_ahead"] / on.clip(lower=1)
df["poss_c"] = (df["poss"] - 50) / 10              # per 10 points of possession
df["mom_c"] = (df["mom_share"].fillna(0.5) - 0.5) * 10   # per 10 points of momentum share

def lg(x):
    return np.log(np.clip(x, 0.05, None))

TARGETS = {"fouled": ("r_fouled", ["sh_behind", "sh_ahead", "poss_c", "mom_c", "m_fouls"]),
           "fouls": ("r_fouls", ["sh_behind", "sh_ahead", "poss_c", "mom_c", "m_fouled", "m_dribbles"]),
           "tackles": ("r_tackles", ["sh_behind", "sh_ahead", "poss_c", "mom_c", "m_dribbles", "m_touches"]),
           "shots": ("r_shots", ["sh_behind", "sh_ahead", "poss_c", "mom_c", "m_tackles", "m_interc"])}
rows = []
for y, (own, xs) in TARGETS.items():
    d = df.dropna(subset=[own] + xs)
    X = sm.add_constant(pd.concat([lg(d[own]).rename("own")] + [d[x] for x in xs], axis=1))
    m = sm.GLM(d[y], X, family=sm.families.Poisson(), offset=np.log(d["min"] / 90)).fit()
    for x in xs:
        unit = {"sh_behind": "behind the whole time vs level", "sh_ahead": "ahead the whole time vs level",
                "poss_c": "+10 pts of possession", "mom_c": "+10 pts of momentum share"}.get(x, f"+1 {x[2:]} by his direct opponent")
        rows.append({"stat": y, "context": unit, "rate x": np.exp(m.params[x]), "p": m.pvalues[x], "n": len(d)})
res = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(res.round(3).to_string())
res.to_csv("trail_effects.csv", index=False)

# Streak breaks
print("\nStreak breaks: 1+ landed after 3+ straight misses, against his other misses (means)")
d = df.sort_values("ts")
out = []
for y in ("fouled", "fouls", "tackles", "shots"):
    for pid, g in d.groupby("pid"):
        miss = 0
        for _, r in g.iterrows():
            hit = r[y] >= 1
            if miss >= 3:
                out.append({"stat": y, "break": hit, "sh_behind": r.sh_behind, "sh_ahead": r.sh_ahead,
                            "poss": r.poss, "mom": r.mom_share, "min": r["min"],
                            "opp_act": r.get({"fouled": "m_fouls", "fouls": "m_fouled",
                                              "tackles": "m_dribbles", "shots": "m_tackles"}[y]),
                            "opp_prior": r.get({"fouled": "m_r_fouls", "fouls": "m_r_fouled",
                                                "tackles": "m_r_dribbles", "shots": "m_r_tackles"}[y])})
            miss = 0 if hit else miss + 1
sb = pd.DataFrame(out)
print(sb.groupby(["stat", "break"]).agg(n=("min", "size"), minutes=("min", "mean"), behind=("sh_behind", "mean"),
                                        ahead=("sh_ahead", "mean"), poss=("poss", "mean"), mom=("mom", "mean"),
                                        opp_did=("opp_act", "mean"), opp_usually=("opp_prior", "mean")).round(2).to_string())
