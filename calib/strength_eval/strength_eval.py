"""Does team strength pick better legs than the raw record? Replay and settle.

Every number is computed as of the fixture's kick-off: form from earlier
matches only (backtest.Backtester), Elo from earlier results only
(strength.rating_at). Writes one row per candidate leg to a CSV.
"""
import csv, math, sys, os
from datetime import datetime, timezone
PROJ = sys.argv[1]
sys.path.insert(0, PROJ)
os.chdir(PROJ)
import backtest, hitrates, markets, model, weekend
import sofascore_api as api
# strength is imported from the project itself (PROJ, above)
import strength, json
SLOPES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "slopes.json")))
HFA = strength.HOME_ADV

api.get_json = backtest.cache_only_get_json
R = strength.Ratings(strength.load_events(strength.Path(PROJ) / "cache"))

def ts_of(date):
    try:
        return datetime.strptime(date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None

class Eval(backtest.Backtester):
    def fixture(self, event, team_ids):
        kickoff = event.get("startTimestamp")
        home, away = event["homeTeam"], event["awayTeam"]
        try:
            outcome = self.actual(event["id"])
            records = [self.form(home["id"], kickoff), self.form(away["id"], kickoff)]
        except backtest.Skipped:
            self.skipped += 1
            return
        if not all(records) or min(len(r) for r in records) < 10:
            return
        fitted = self.ratings_as_of(team_ids, kickoff)
        projection = {}
        if fitted:
            ratings, names_ = fitted
            projection = hitrates.project_fixture(ratings, home["id"], away["id"], names_)
        names = hitrates.stat_names(*records, bettable_only=True, sport="football")
        lines = hitrates.suggest_lines(records, names)
        ids = [home["id"], away["id"]]
        elo_now = [R.rating_at(t, kickoff) for t in ids]
        for side in (0, 1):
            venue = "home" if side == 0 else "away"
            sample, used = weekend._sample(records[side], venue)
            if len(sample) < weekend.MIN_SAMPLE:
                continue
            opp_now = elo_now[1 - side]; me_now = elo_now[side]
            gap_now = None if (opp_now is None or me_now is None) else me_now - opp_now
            per = []
            xs = []
            for r in sample:
                t = ts_of(r.get("date") or "")
                o = R.rating_at(r.get("opponent_id"), t) if t else None
                m = R.rating_at(ids[side], t) if t else None
                per.append((o, m))
                xs.append(None if (o is None or m is None) else (m - o + (HFA if r.get("venue") == "home" else -HFA)) / 100)
            x_now = None if gap_now is None else (gap_now + (HFA if side == 0 else -HFA)) / 100
            known = [x for x in xs if x is not None]
            x_mean = sum(known) / len(known) if known else None
            for period in hitrates.PERIODS:
                if period not in outcome:
                    continue
                for stat in names.get(period, []):
                    if stat not in markets.stats_for("football"):
                        continue
                    line = (lines.get(period) or {}).get(stat)
                    truth = (outcome[period].get(stat) or [None, None])[side]
                    if line is None or truth is None:
                        continue
                    vals, opps = [], []
                    b = SLOPES.get(f"{period}|{stat}", 0.0)
                    for r, (o, m) in zip(sample, per):
                        v = (r.get("stats", {}).get(period) or {}).get(stat)
                        if v is not None:
                            vals.append(float(v)); opps.append((o, m))
                    if len(vals) < weekend.MIN_SAMPLE:
                        continue
                    expected = ((projection.get(period) or {}).get(stat) or [None, None])[side]
                    for over in (True, False):
                        hit_list = [(v > line) == over for v in vals]
                        hits = sum(hit_list); n = len(vals)
                        if hits == 0:
                            continue
                        pr = model.price(line, over, expected, vals, hits, n, sport="football")
                        if pr.get("conflict") or not math.isfinite(pr["fair"]):
                            continue
                        pr_rec = model.price(line, over, None, vals, hits, n, sport="football")
                        row = {"date": datetime.fromtimestamp(kickoff, tz=timezone.utc).strftime("%Y-%m-%d"),
                               "league": self.tournament_id, "event": event["id"], "side": side,
                               "stat": stat, "period": period, "line": line, "over": int(over),
                               "n": n, "hits": hits, "won": int((truth > line) == over),
                               "fair": pr["fair"], "p_model": pr["p"], "src": pr["source"],
                               "p_rec_model": pr_rec["p"], "fair_rec": pr_rec["fair"],
                               "opp_now": opp_now, "gap_now": gap_now}
                        mean_v = sum(vals) / len(vals)
                        ev_reg = (mean_v * math.exp(b * (x_now - x_mean))) if (x_now is not None and x_mean is not None) else None
                        row["ev_reg"] = ev_reg
                        p_r = model.price(line, over, ev_reg, vals, hits, n, sport="football") if ev_reg else None
                        row["p_ev_reg"] = p_r["p"] if p_r and math.isfinite(p_r.get("fair", float("nan"))) and not p_r.get("conflict") else None
                        for sigma in (125,):
                            for mode in ("gap",):
                                ws = []
                                for (o, m) in opps:
                                    if mode == "opp":
                                        d = None if (o is None or opp_now is None) else o - opp_now
                                    else:
                                        d = None if (o is None or m is None or gap_now is None) else (m - o) - gap_now
                                    ws.append(1e-3 if d is None else math.exp(-0.5 * (d / sigma) ** 2))
                                sw = sum(ws); sw2 = sum(w * w for w in ws)
                                wh = sum(w for w, h in zip(ws, hit_list) if h)
                                neff = sw * sw / sw2 if sw2 else 0
                                ev = sum(w * v for w, v in zip(ws, vals)) / sw if sw else None
                                key = f"{mode}{sigma}"
                                row[f"sw_{key}"] = round(sw, 3)
                                row[f"neff_{key}"] = round(neff, 2)
                                row[f"wrate_{key}"] = wh / sw if sw else None
                                row[f"ev_{key}"] = ev
                                p_e = model.price(line, over, ev, vals, hits, n, sport="football") if ev else None
                                row[f"p_ev_{key}"] = p_e["p"] if p_e and math.isfinite(p_e.get("fair", float("nan"))) else None
                        self.rows.append(row)

out_path = sys.argv[2]; since = backtest.parse_date(sys.argv[3]); leagues = sys.argv[4].split(",")
allrows = []
for name in leagues:
    tid = api.TOURNAMENTS.get(name)
    roster = api.tournament_team_ids(tid)
    seen, fixtures = set(), []
    for team_id in roster:
        try:
            evs = hitrates.collect_events(team_id, tid, team_name=str(team_id), verbose=False)
        except backtest.Skipped:
            continue
        for e in evs:
            if e["id"] in seen or (e.get("startTimestamp") or 0) < since:
                continue
            if (e.get("tournament", {}).get("uniqueTournament", {}).get("id")) != tid:
                continue
            seen.add(e["id"]); fixtures.append(e)
    fixtures.sort(key=lambda e: e["startTimestamp"])
    team_ids = sorted({e[s]["id"] for e in fixtures for s in ("homeTeam", "awayTeam")})
    t = Eval(tid, 38, verbose=False)
    for i, e in enumerate(fixtures):
        t.fixture(e, team_ids)
    print(name, len(fixtures), "fixtures", len(t.rows), "rows", "skipped", t.skipped, flush=True)
    allrows.extend(t.rows)
keys = sorted({k for r in allrows for k in r})
with open(out_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(allrows)
print("done", len(allrows))
