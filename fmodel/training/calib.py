import pandas as pd, numpy as np, json
D="/home/claude/bt/data"
P=pd.read_parquet(f"{D}/oos_preds.parquet")
LINES={"shots":(1,2,3),"sot":(1,2),"fouls":(1,2),"fouled":(1,2,3),"tackles":(1,2,3),"goals":(1,),"assists":(1,)}
out=[]
for s,ks in LINES.items():
    for k in ks:
        c=f"p_{s}_{k}"
        if c not in P: continue
        d=P[P[c].notna()]
        y=(d["y_"+s]>=k).astype(int)
        for name,col in [("new",c),("site",f"b_{s}_{k}"),("site_fair",f"sf_{s}_{k}")]:
            bins=pd.cut(d[col],[0,.1,.2,.3,.4,.5,.6,.7,.8,.9,1])
            g=pd.DataFrame({"p":d[col],"y":y,"b":bins}).groupby("b",observed=True).agg(n=("y","size"),pred=("p","mean"),hit=("y","mean"))
            g=g[g.n>=100]
            ece=float((g.n*(g.pred-g.hit).abs()).sum()/g.n.sum())
            out.append({"market":f"{s} {k}+","model":name,"ece":round(ece,4),
                        "bins":[(round(r.pred,2),round(r.hit,2),int(r.n)) for r in g.itertuples()]})
for o in out:
    if o["model"]!="site_fair": print(o["market"],o["model"],"avg gap",o["ece"],o["bins"] if o["model"]=="new" else "")
json.dump(out,open(f"{D}/calibration.json","w"))
