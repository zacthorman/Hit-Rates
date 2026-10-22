import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/usbt/src")
import usfeatures as U
sport = sys.argv[1]
M = pd.read_parquet(f"../data/{sport}_matches.parquet"); T = pd.read_parquet(f"../data/{sport}_teams.parquet")
P = pd.read_parquet(f"../data/{sport}_players.parquet"); F = pd.read_parquet(f"../data/{sport}_features.parquet")
last = T.sort_values("ts").groupby("team").tail(1)
games = [g for g in M.to_dict("records") if (last.match == g["match"]).sum() == 2][-15:]
ids = {g["match"] for g in games}
out_ids = set()  # nobody ruled out: compare like with like, except absences
M0, T0, P0 = M[~M.match.isin(ids)], T[~T.match.isin(ids)], P[~P.match.isin(ids)]
M1, T1, P1 = U.add_upcoming(M0, T0, P0, [{k: g[k] for k in ("match", "ts", "home", "away", "season")} for g in games], sport)
if sport == "nba":
    for c in ("pra", "pr", "pa", "ra"): P1[c] = P1[c] if c in P1 else np.nan
F1 = U.features(M1, T1, P1, sport)
F1 = F1[F1.match.isin(ids)]
ref = F[F.match.isin(ids)]
j = ref.merge(F1, on=["match", "pid"], suffixes=("", "_live"))
skip = ("starter", "miss_", "y_", "mins")
cols = [c for c in ref.columns if ref[c].dtype.kind in "fi" and not c.startswith(skip) and c + "_live" in j and c not in ("match", "pid", "ts", "season")]
diff = {c: float((j[c].fillna(-9) - j[c + "_live"].fillna(-9)).abs().max()) for c in cols}
bad = {c: v for c, v in diff.items() if v > 1e-9}
print(sport, "games", len(games), "players in both", len(j), "of", len(ref), "played /", len(F1), "expected")
print("features compared", len(cols), "mismatches", len(bad), dict(list(bad.items())[:8]))
print("played but not expected:", sorted(set(ref.name) - set(F1.name))[:12])
if sport == "nfl":
    c = "oc_rec_yds"
    bad = j[(j[c].fillna(-9) - j[c + "_live"].fillna(-9)).abs() > 1e-6]
    print(bad[["name", "pos", "pos_live", "team", "opp", c, c + "_live"]].head(8).to_string())
