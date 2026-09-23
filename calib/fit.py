"""Fit Platt scaling p' = sigmoid(a + b*logit(p)) by Newton's method."""
import csv, math, sys

def logit(p):
    p = min(1-1e-9, max(1e-9, p)); return math.log(p/(1-p))
def sig(z): return 1/(1+math.exp(-z)) if z > -700 else 0.0

def fit(xs, ys, iters=60):
    a, b = 0.0, 1.0
    for _ in range(iters):
        g=[0.0,0.0]; H=[[1e-6,0],[0,1e-6]]
        for x,y in zip(xs,ys):
            p=sig(a+b*x); r=p-y; w=max(p*(1-p),1e-9)
            g[0]+=r; g[1]+=r*x
            H[0][0]+=w; H[0][1]+=w*x; H[1][0]+=w*x; H[1][1]+=w*x*x
        det=H[0][0]*H[1][1]-H[0][1]*H[1][0]
        if abs(det)<1e-12: break
        da=( H[1][1]*g[0]-H[0][1]*g[1])/det
        db=(-H[1][0]*g[0]+H[0][0]*g[1])/det
        a-=da; b-=db
        if abs(da)<1e-10 and abs(db)<1e-10: break
    return a,b

def brier(ps, ys): return sum((p-y)**2 for p,y in zip(ps,ys))/len(ys)

def buckets(ps, ys):
    edges=[(.5,.65),(.65,.75),(.75,.82),(.82,.88),(.88,.93),(.93,.97),(.97,1.01)]
    out=[]
    for lo,hi in edges:
        sel=[(p,y) for p,y in zip(ps,ys) if lo<=p<hi]
        if len(sel)<5: continue
        said=sum(p for p,_ in sel)/len(sel); act=sum(y for _,y in sel)/len(sel)
        out.append((f"{lo:.0%}-{hi:.0%}", len(sel), said, act, act-said))
    return out

def load(path, kind):
    rows=list(csv.DictReader(open(path)))
    if kind=="player":
        rows=[r for r in rows if r.get("result") not in ("void_absent","void_cameo")]
    return rows

for name, path, kind, src in [
    ("NFL team   (record)",   "calib/nfl_team.csv",   "team",   "record"),
    ("NFL player (record)",   "calib/nfl_player.csv", "player", "record"),
    ("PL  team   (record)",   "calib/pl_team.csv",    "team",   "record"),
    ("PL  player (model)",    "calib/pl_player.csv",  "player", "model"),
    ("PL  player (blend)",    "calib/pl_player.csv",  "player", "blend"),
]:
    rows=[r for r in load(path,kind) if r["source"]==src]
    if len(rows)<50:
        print(f"{name}: only {len(rows)} settled rows -- too few to fit\n"); continue
    ps=[float(r["p_model"]) for r in rows]; ys=[1.0 if r["won"]=="True" else 0.0 for r in rows]
    a,b=fit([logit(p) for p in ps], ys)
    new=[sig(a+b*logit(p)) for p in ps]
    print(f"=== {name} — {len(rows)} settled ===")
    print(f"  fitted a={a:+.4f}  b={b:.4f}")
    print(f"  Brier {brier(ps,ys):.4f} -> {brier(new,ys):.4f}"
          f"   |  said {sum(ps)/len(ps):.1%} -> {sum(new)/len(new):.1%}, landed {sum(ys)/len(ys):.1%}")
    print("   after correction:")
    for lab,n,said,act,gap in buckets(new,ys):
        print(f"     {lab:<10}{n:>6}  said {said:.1%}  landed {act:.1%}  gap {gap:+.1%}")
    print()
