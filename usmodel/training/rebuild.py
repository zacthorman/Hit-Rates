import sys, pandas as pd
sys.path.insert(0, "/home/claude/usbt/src")
import usfeatures as U
for sport in sys.argv[1:]:
    M, T, P = U.build("/home/claude/usbt/raw", sport)
    if sport == "nba":
        P["pra"] = P.points + P.rebounds + P.assists; P["pr"] = P.points + P.rebounds
        P["pa"] = P.points + P.assists; P["ra"] = P.rebounds + P.assists
    else:
        P["rush_rec_yds"] = P.rush_yds + P.rec_yds; P["pass_rush_yds"] = P.pass_yds + P.rush_yds
    for n, d in (("matches", M), ("teams", T), ("players", P)):
        d.to_parquet(f"/home/claude/usbt/data/{sport}_{n}.parquet")
    F = U.features(M, T, P, sport)
    F.to_parquet(f"/home/claude/usbt/data/{sport}_features.parquet")
    print(sport, len(M), "games", F.shape)
