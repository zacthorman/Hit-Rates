import sys, time, collections
sys.path.insert(0, ".")
exec(open("calib/exchange/diag.py").read().split("c=collections")[0])
import market_prices as mp
data=mp.load()
done=0
for e,m in up:
    ev=data["events"].get(str(m["id"]))
    if not ev: continue
    ms=[x for x in ev["markets"] if x["type"] in("SHOTS_ON_TARGET_P1","TO_SCORE","TO_SCORE_A_TOUCHDOWN")]
    if not ms: continue
    sp=weekend.sport_of(e); m=dict(m,sport=sp)
    legs=[l for l in parlay.single_legs_for(e,m)+parlay.alt_legs_for(e,m) if l["stat"] in("Shots on target","Goals","Anytime touchdown")]
    print(m["home"],m["away"],[x["type"] for x in ms])
    for x in ms: print("  ",x["type"],[ (r["name"],r["back"],r.get("p")) for r in x["runners"][:6]])
    print("  ours",[(l["player"],l["stat"],l["line"],l["over"],l.get("period"),l.get("alt"),l.get("teamIndex")) for l in legs[:6]])
    done+=1
    if done>3: break
