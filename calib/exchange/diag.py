import sys, time, collections
sys.path.insert(0, ".")
from pathlib import Path
import make_index as mi, weekend, parlay
files=[f for f in sorted(mi.REPORTS.glob("*.html")) if not f.name.startswith(("pick-","_"))]
fr=sorted(files,key=lambda p:("-v-" in p.stem or p.stem.startswith("mixed-"),p.stat().st_mtime),reverse=True)
ents=[];seen=set()
for p in fr:
    for e,m in mi.read_entries(p):
        k=(m["home"],m["away"],m["kickoff"])
        if k in seen: continue
        seen.add(k); ents.append((e,m))
now=time.time()
up=[(e,m) for e,m in ents if now<m["kickoff"]<=now+7*86400]
c=collections.Counter(); q=collections.Counter()
for e,m in up:
    sp=weekend.sport_of(e); m=dict(m,sport=sp)
    legs=weekend.legs_for(e,m)+parlay.single_legs_for(e,m)+parlay.alt_legs_for(e,m)
    weekend.calibrate(legs)
    for l in legs:
        k=(sp,l.get("period"),bool(l.get("player")),l["stat"],l["line"])
        c[k]+=1
        if l.get("exchange"): q[k]+=1
for k,n in sorted(c.items(),key=lambda x:-x[1])[:120]:
    print(k,n,q[k])
