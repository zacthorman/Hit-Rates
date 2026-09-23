import csv, math
def logit(p):
    p=min(1-1e-6,max(1e-6,p)); return math.log(p/(1-p))
def sig(z): return 1/(1+math.exp(-z)) if z>-700 else 0.0
def fit(xs,ys,iters=200):
    a,b=0.0,1.0
    for _ in range(iters):
        g=[0.0,0.0]; H=[[1e-4,0],[0,1e-4]]
        for x,y in zip(xs,ys):
            p=sig(a+b*x); r=p-y; w=max(p*(1-p),1e-6)
            g[0]+=r; g[1]+=r*x
            H[0][0]+=w; H[0][1]+=w*x; H[1][0]+=w*x; H[1][1]+=w*x*x
        det=H[0][0]*H[1][1]-H[0][1]*H[1][0]
        if abs(det)<1e-12: break
        da=(H[1][1]*g[0]-H[0][1]*g[1])/det; db=(-H[1][0]*g[0]+H[0][0]*g[1])/det
        a-=max(-1,min(1,da)); b-=max(-1,min(1,db))
    return a,b
def brier(ps,ys): return sum((p-y)**2 for p,y in zip(ps,ys))/len(ys)
def buckets(ps,ys):
    out=[]
    for lo,hi in [(.5,.65),(.65,.75),(.75,.82),(.82,.88),(.88,.93),(.93,.97),(.97,1.01)]:
        s=[(p,y) for p,y in zip(ps,ys) if lo<=p<hi]
        if len(s)<5: continue
        out.append((f"{lo:.0%}-{hi:.0%}",len(s),sum(p for p,_ in s)/len(s),sum(y for _,y in s)/len(s)))
    return out

ALPHA=0.5          # Jeffreys: a 20/20 record becomes 20.5/21, not certainty
for name,path,kind in [("NFL team","calib/nfl_team.csv","team"),
                       ("NFL player","calib/nfl_player.csv","player"),
                       ("PL team (record only)","calib/pl_team.csv","team")]:
    rows=list(csv.DictReader(open(path)))
    if kind=="player": rows=[r for r in rows if r.get("result") not in ("void_absent","void_cameo")]
    rows=[r for r in rows if r["source"]=="record"]
    ys=[1.0 if r["won"]=="True" else 0.0 for r in rows]
    raw=[float(r["p_model"]) for r in rows]
    # apps/total: recover n from the need price where possible, else use apps
    ns=[]
    for r in rows:
        n=r.get("apps")
        ns.append(int(n) if n and n.isdigit() else 10)
    sm=[(p*n+ALPHA)/(n+2*ALPHA) for p,n in zip(raw,ns)]
    a,b=fit([logit(p) for p in sm],ys)
    new=[sig(a+b*logit(p)) for p in sm]
    print(f"=== {name} — {len(rows)} settled ===")
    print(f"  smoothing alpha={ALPHA}, then a={a:+.4f} b={b:.4f}")
    print(f"  Brier  raw {brier(raw,ys):.4f} -> smoothed {brier(sm,ys):.4f} -> calibrated {brier(new,ys):.4f}")
    print(f"  said {sum(raw)/len(raw):.1%} -> {sum(new)/len(new):.1%}   landed {sum(ys)/len(ys):.1%}")
    for lab,n,said,act in buckets(new,ys):
        print(f"     {lab:<10}{n:>6}  said {said:.1%}  landed {act:.1%}  gap {act-said:+.1%}")
    print()
