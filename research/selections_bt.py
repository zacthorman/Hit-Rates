"""Back-test of the 'best selections' filter on settled pplog rows (first prices)."""
import json, sys, collections, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pplog, ruletrack
rows = [r for r in pplog.all_rows() if r.get("result") in ("win", "lose")]
hist = ruletrack._hist_model()
sides = collections.defaultdict(set)
for r in rows:
    sides[(r["event_id"], r["player"], r["stat"], r["line"])].add(bool(r["over"]))
out = []
for r in rows:
    f = r.get("first") or {}
    pr = f.get("price")
    if not pr or r["sport"] not in ("basketball", "american-football", "football"):
        continue
    m = ruletrack._model(r, hist)
    if m is None and r["sport"] == "football" and f.get("source") == "fmodel":
        m = f.get("chance")
    if m is None:
        continue
    out.append(dict(sport=r["sport"], stat=r["stat"], over=bool(r["over"]), price=pr, m=m,
                    edge=m * pr - 1, k10=r.get("k10"), n10=r.get("n10"), k5=r.get("k5"), n5=r.get("n5"),
                    main=len(sides[(r["event_id"], r["player"], r["stat"], r["line"])]) == 2,
                    ev=r["event_id"], pl=r["player"], ko=r["kickoff"], win=r["result"] == "win"))
json.dump(out, open("research/_sel_rows.json", "w"))
print(len(out), collections.Counter(o["sport"] for o in out))
