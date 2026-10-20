import sys, time, numpy as np, pandas as pd
sys.path.insert(0, "/tmp/claude-0/sim/root")
import fmodel_live as L
t=time.time(); M,T,P=L.history(); print("history", M.shape, T.shape, P.shape, f"{time.time()-t:.0f}s")
F0=pd.read_parquet("/home/claude/bt/data/features.parquet")
# simulate: the 40 latest matches with no team repeated, all after every other match of those teams
M=M.sort_values("ts"); chosen=[]; seen=set()
for r in M[::-1].itertuples():
    if r.home in seen or r.away in seen: 
        seen|={r.home,r.away}; continue
    seen|={r.home,r.away}; chosen.append(r.match)
    if len(chosen)==40: break
sim={m: int(M.set_index("match").ts[m]) for m in chosen}
HM,HT,HP=M[~M.match.isin(sim)],T[~T.match.isin(sim)],P[~P.match.isin(sim)]
UM,UT,UP,meta=L.upcoming(7,set(HM.match),simulate=sim)
print("upcoming", UM.shape, UP.shape)
t=time.time()
F=L.features(pd.concat([HM,UM]),pd.concat([HT,UT]),pd.concat([HP,UP]),set(UM.match)); print("features", F.shape, f"{time.time()-t:.0f}s")
B=F0[F0.match.isin(sim)]
j=F.merge(B,on=["match","pid"],suffixes=("","_bt"))
print("rows live", len(F), "backtest", len(B), "joined", len(j))
bad=[]
for c in F.columns:
    if c+"_bt" in j and pd.api.types.is_numeric_dtype(j[c]) and pd.api.types.is_numeric_dtype(j[c+"_bt"]):
        a,b=j[c].astype(float),j[c+"_bt"].astype(float)
        d=((a-b).abs()>1e-6)&~(a.isna()&b.isna())
        if d.any(): bad.append((c,int(d.sum())))
print("mismatched features", bad[:30])
pl=L.score(j[F.columns]); 
Bj=j[[c for c in F.columns]].copy()
for c in F.columns:
    if c+"_bt" in j: Bj[c]=j[c+"_bt"]
pb=L.score(Bj)
print("max prob diff", {k: round(float(np.abs(pl[k]-pb[k]).max()),5) for k in pl})
x=F[~F.set_index(["match","pid"]).index.isin(B.set_index(["match","pid"]).index)]
pp=P.set_index(["match","pid"])
mins=[pp.mins.get((a,b)) for a,b in zip(x.match,x.pid)]
print("extra rows by actual minutes:", pd.Series(mins).describe().to_dict())
