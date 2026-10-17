import sys, time, json
sys.path.insert(0, ".")
exec(open("calib/exchange/diag.py").read().split("c=collections")[0])
t=time.time()
out=weekend.picks(ents,days=7)
print("secs",round(time.time()-t,1))
for s in out["sports"]:
    v=s["value"]
    print(s["sport"],"quoted",v["quoted"],"positive",v["positive"])
    for l in v["legs"]:
        print("  ",l["fixture"]["home"],"v",l["fixture"]["away"],"|",l.get("player") or l["team"],l["stat"],l["line"],l["over"],"chance",l["chance"],"model",l["chanceModel"],"ex",l["exchange"]["p"],l["exchange"]["back"],l["exchange"]["kind"],"value",l["value"])
    for k in ("single","banker"):
        if s.get(k): print(" ",k,json.dumps(s[k].get("why"),indent=1)[:1500])
    if s["sport"]=="football" and v["legs"]: print(json.dumps(v["legs"][0]["why"],indent=1))
