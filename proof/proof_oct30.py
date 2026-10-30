#!/usr/bin/env python3
"""
Score the 21 October models on everything settled since, from the Mac's cache. No requests.

    python3 -B proof/proof_oct30.py            # items 1 and 2 of PROOF-2026-10-30.md

1. Every written scoreline call ("Call:" in every committed tonight.html since
   21 Oct), the last version written before kick-off, scored against the final
   90-minute score in cache/ (strength.load_events), against the bookmaker
   (Betfair de-vigged match odds from market_prices.json at the same commit)
   and against base rates (every cached finished match before 21 Oct).
2. lead_log.json settled the way tonight.results_block settles it (best_bets.json,
   then exchange_log.json), with a calibration table, a flat baseline and the
   sample needed.
"""
from __future__ import annotations
import html, json, math, re, subprocess, sys, unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "proof"))
import settle_oct21 as S          # settled_legs, key, n_needed, binom_tail_le
import strength

SINCE = datetime(2026, 10, 21, tzinfo=timezone.utc).timestamp()
Z = 1.96 + 0.8416


SRC = {"style model ": "style", "team attack ": "ratings", "Elo for the ": "Elo (untested)"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def when(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d %b %H:%M")


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout


def calls():
    out = []
    for line in filter(None, git("log", "--format=%H %ct", "--since=2026-10-20", "--", "tonight.html").split("\n")):
        rev, ct = line.split(); ct = int(ct)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", git("show", f"{rev}:tonight.html"))))
        for m in re.finditer(r"Call: (.+?) (\d+)-(\d+) (.+?) · home (\d+)% · draw (\d+)% · away (\d+)%(?: · ([\d.]+) goals expected · ([^·]+?)(?= Lead| Bet| Why| Tonight|  |$))?", text):
            h, hg, ag, a, ph, pd, pa, xg, src = m.groups()
            p = [int(ph), int(pd), int(pa)]; t = sum(p)
            out.append(dict(home=h.strip(), away=a.strip(), hg=int(hg), ag=int(ag), p=[x / t for x in p],
                            rev=rev, ct=ct, xg=xg, src=(src or "").strip()))
    return out


def market(rev, eid):
    raw = git("show", f"{rev}:market_prices.json")
    if not raw:
        return None
    ev = (json.loads(raw).get("events") or {}).get(str(eid)) or {}
    for m in ev.get("markets") or []:
        if m.get("type") == "MATCH_ODDS":
            names = [r["name"] for r in m["runners"]]; ps = [r.get("p") for r in m["runners"]]
            if None in ps or len(ps) != 3:
                return None
            d = names.index("The Draw") if "The Draw" in names else names.index("Draw") if "Draw" in names else None
            if d is None:
                return None
            hh, aa = [k for k in range(3) if k != d]
            t = ps[hh] + ps[d] + ps[aa]
            return [ps[hh] / t, ps[d] / t, ps[aa] / t]
    return None


def oc(i, j):
    return 0 if i > j else 1 if i == j else 2


def scores(p, y):
    """Brier (3-way sum), log loss, RPS for probs p and outcome index y."""
    br = sum((p[k] - (k == y)) ** 2 for k in range(3))
    ll = -math.log(max(p[y], 1e-6))
    c = [p[0], p[0] + p[1]]; o = [1 if y <= 0 else 0, 1 if y <= 1 else 0]
    rps = sum((c[k] - o[k]) ** 2 for k in range(2)) / 2
    return br, ll, rps


def paired(d):
    n = len(d)
    if n < 2:
        return float("nan"), float("nan")
    m = sum(d) / n; sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return m, sd / math.sqrt(n)


def summary(rows, label, bp, sc):
    n = len(rows)
    if not n:
        return
    M, R, B, Ms = [], [], [], []
    ex = outc = outr = outb = 0
    for c in rows:
        e = c["e"]; y = oc(e["hg"], e["ag"]); mk = market(c["rev"], e["id"])
        ex += (c["hg"], c["ag"]) == (e["hg"], e["ag"]); outc += oc(c["hg"], c["ag"]) == y
        M.append(scores(c["p"], y)); R.append(scores(bp, y)); outr += max(range(3), key=lambda k: bp[k]) == y
        if mk:
            B.append(scores(mk, y)); Ms.append(M[-1]); outb += max(range(3), key=lambda k: mk[k]) == y
    avg = lambda L, i: sum(x[i] for x in L) / len(L) if L else float("nan")
    print(f"\n**{label}** ({n} fixtures)\n")
    print("| Forecast | Fixtures | Exact score | Outcome right | Brier | Log loss | RPS |")
    print("|---|---|---|---|---|---|---|")
    print(f"| The case | {n} | {ex} ({ex / n:.0%}) | {outc} ({outc / n:.0%}) | {avg(M,0):.4f} | {avg(M,1):.4f} | {avg(M,2):.4f} |")
    print(f"| Base rates | {n} | {sum((c['e']['hg'], c['e']['ag']) == sc for c in rows)} (always {sc[0]}-{sc[1]}) | {outr} ({outr / n:.0%}) | {avg(R,0):.4f} | {avg(R,1):.4f} | {avg(R,2):.4f} |")
    if B:
        print(f"| The case, the {len(B)} with odds | {len(B)} | | | {avg(Ms,0):.4f} | {avg(Ms,1):.4f} | {avg(Ms,2):.4f} |")
        print(f"| Betfair | {len(B)} | | {outb} ({outb / len(B):.0%}) | {avg(B,0):.4f} | {avg(B,1):.4f} | {avg(B,2):.4f} |")
        d = [m[1] - b[1] for m, b in zip(Ms, B)]; m, se = paired(d)
        print(f"\nLog loss, the case minus Betfair: {m:+.4f} (SE {se:.4f}, z {m / se:+.2f}).")
    d = [m[1] - r[1] for m, r in zip(M, R)]; m, se = paired(d)
    print(f"Log loss, the case minus base rates: {m:+.4f} (SE {se:.4f}, z {m / se:+.2f}).")


def item1():
    ev = strength.load_events(ROOT / "cache")
    before = [e for e in ev if e["ts"] < SINCE]
    base = Counter(oc(e["hg"], e["ag"]) for e in before)
    bp = [base[k] / len(before) for k in range(3)]
    sc = Counter((e["hg"], e["ag"]) for e in before).most_common(1)[0][0]
    after = [e for e in ev if e["ts"] >= SINCE - 86400]
    idx = defaultdict(list)
    for e in after:
        idx[(norm(e["home_name"]), norm(e["away_name"]))].append(e)
    best = {}
    unmatched = set()
    for c in calls():
        cands = [e for e in idx.get((norm(c["home"]), norm(c["away"])), []) if c["ct"] - 2 * 86400 <= e["ts"] <= c["ct"] + 3 * 86400]
        if not cands:
            unmatched.add((c["home"], c["away"]))
            continue
        e = min(cands, key=lambda e: abs(e["ts"] - c["ct"]))
        c["e"] = e; c["pre"] = c["ct"] < e["ts"]
        k = e["id"]
        old = best.get(k)
        # keep the last version committed before kick-off; else the earliest after it
        if old is None or (c["pre"] and (not old["pre"] or c["ct"] > old["ct"])) or (not c["pre"] and not old["pre"] and c["ct"] < old["ct"]):
            best[k] = c
    rows = sorted(best.values(), key=lambda c: c["e"]["ts"])
    print("## 1. Written score calls since 21 Oct\n")
    print(f"Base rates from {len(before):,} cached finished matches before 21 Oct: home {bp[0]:.1%}, draw {bp[1]:.1%}, away {bp[2]:.1%}; commonest score {sc[0]}-{sc[1]}.\n")
    print("| Kick-off (UTC) | Fixture | Call | H / D / A said | Betfair H / D / A | Final | Exact | Outcome | Written | Method |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    M, B, R, ex, outc, exb, outb, outr = [], [], [], 0, 0, 0, 0, 0
    pairs_b, pairs_r = defaultdict(list), defaultdict(list)
    for c in rows:
        e = c["e"]; y = oc(e["hg"], e["ag"]); mk = market(c["rev"], e["id"])
        hit = (c["hg"], c["ag"]) == (e["hg"], e["ag"]); ok = oc(c["hg"], c["ag"]) == y
        ex += hit; outc += ok
        sm = scores(c["p"], y); M.append(sm); sr = scores(bp, y); R.append(sr)
        outr += (max(range(3), key=lambda k: bp[k]) == y)
        for i in range(3):
            pairs_r[i].append(sm[i] - sr[i])
        if mk:
            sb = scores(mk, y); B.append(sb); outb += (max(range(3), key=lambda k: mk[k]) == y)
            for i in range(3):
                pairs_b[i].append(sm[i] - sb[i])
        print(f"| {when(e['ts'])} | {c['home']} v {c['away']} | {c['hg']}-{c['ag']} | "
              f"{' / '.join(f'{p:.0%}' for p in c['p'])} | {' / '.join(f'{p:.0%}' for p in mk) if mk else 'n/a'} | "
              f"{e['hg']}-{e['ag']} | {'yes' if hit else 'no'} | {'yes' if ok else 'no'} | "
              f"{'before kick-off' if c['pre'] else ('after full time' if c['ct'] > e['ts'] + 7200 else 'after kick-off')} | {SRC.get(c['src'][:12], c['src'] or '?')} |")
    n = len(rows); nb = len(B)
    if unmatched:
        print(f"\nCalls with no finished match in the cache: {len(unmatched)}: " + "; ".join(f"{h} v {a}" for h, a in sorted(unmatched)))
    print(f"\n{n} calls scored ({sum(c['pre'] for c in rows)} written before kick-off). Bookmaker odds on file for {nb}.\n")
    avg = lambda L, i: sum(x[i] for x in L) / len(L) if L else float('nan')
    print("| Forecast | Fixtures | Exact score | Outcome right | Brier | Log loss | RPS |")
    print("|---|---|---|---|---|---|---|")
    print(f"| The case (model) | {n} | {ex} ({ex / n:.0%}) | {outc} ({outc / n:.0%}) | {avg(M,0):.4f} | {avg(M,1):.4f} | {avg(M,2):.4f} |")
    print(f"| Base rates | {n} | {sc[0]}-{sc[1]} always: {sum((e['hg'], e['ag']) == sc for e in (c['e'] for c in rows))} | {outr} ({outr / n:.0%}) | {avg(R,0):.4f} | {avg(R,1):.4f} | {avg(R,2):.4f} |")
    if nb:
        Msub = [scores(c['p'], oc(c['e']['hg'], c['e']['ag'])) for c in rows if market(c['rev'], c['e']['id'])]
        print(f"| The case, same {nb} with odds | {nb} | | | {avg(Msub,0):.4f} | {avg(Msub,1):.4f} | {avg(Msub,2):.4f} |")
        print(f"| Betfair (de-vigged) | {nb} | | {outb} ({outb / nb:.0%}) | {avg(B,0):.4f} | {avg(B,1):.4f} | {avg(B,2):.4f} |")
    print("\nPaired difference, model minus baseline (negative means the model is better), mean and standard error:\n")
    print("| Against | n | Brier | Log loss | RPS |")
    print("|---|---|---|---|---|")
    for name, P in (("Base rates", pairs_r), ("Betfair", pairs_b)):
        if P[0]:
            cells = []
            for i in range(3):
                m, se = paired(P[i]); cells.append(f"{m:+.4f} (SE {se:.4f}, z {m / se:+.2f})" if se == se and se > 0 else f"{m:+.4f}")
            print(f"| {name} | {len(P[0])} | " + " | ".join(cells) + " |")
    for name, P, gap in (("base rates", pairs_r, 0.06), ("Betfair", pairs_b, 0.01)):
        if len(P[1]) > 2:
            m, se = paired(P[1]); sd = se * math.sqrt(len(P[1]))
            print(f"\nFixtures needed to detect a log loss gap of {gap} against {name} at the measured paired sd {sd:.3f}: {math.ceil((Z * sd / gap) ** 2)}"
                  + (f"; at the gap measured now ({m:+.4f}): {math.ceil((Z * sd / abs(m)) ** 2)}" if m else ""))
    summary([c for c in rows if c["pre"]], "Written before kick-off only (the fair test)", bp, sc)
    summary([c for c in rows if c["pre"] or c["ct"] <= c["e"]["ts"] + 7200], "Excluding calls first committed after full time", bp, sc)
    for k, v in SRC.items():
        summary([c for c in rows if c["src"].startswith(k)], f"Method: {v}", bp, sc)
    return rows


def sport_of(r):
    if r.get("sport"):
        return r["sport"]
    c = (r.get("competition") or "").lower()
    if c in ("nba",) or "basketball" in c:
        return "basketball"
    if c in ("nfl",) or "football league" in c:
        return "american-football"
    if c in ("mlb",) or "baseball" in c or "postseason" in c:
        return "baseball"
    if "darts" in c or "premier league darts" in c:
        return "darts"
    return "football"


def item2():
    settled = S.settled_legs()
    log = json.loads((ROOT / "lead_log.json").read_text())
    rows = sorted((r for r in log.values() if r["kickoff"] >= SINCE), key=lambda r: r["kickoff"])
    now = datetime.now(timezone.utc).timestamp()
    done, status = [], Counter()
    for r in rows:
        l = settled.get(S.key(r))
        res = l["result"] if l else ("not played" if r["kickoff"] > now else "not settled")
        status[res] += 1
        if l and l["result"] in ("win", "lose") and r.get("chance"):
            done.append((r["chance"], 1 if l["result"] == "win" else 0, r))
    print("\n## 2. lead_log.json since 21 Oct\n")
    print(f"{len(rows)} leads: " + ", ".join(f"{v} {k}" for k, v in status.most_common()) + ".\n")
    zero = [r for r in rows if not r.get("chance")]
    print(f"Leads written with chance 0: {len(zero)} ({', '.join(sorted({r.get('sport') or r['competition'] for r in zero})) or 'none'}).\n")
    pool = [l for l in settled.values() if (l.get("kickoff") or 0) >= SINCE and l["result"] in ("win", "lose")]
    flat = sum(l["result"] == "win" for l in pool) / len(pool)
    print("| Group | Settled | Said (mean) | Landed | P(this few or fewer) | P(this many or more) | Brier | Log loss | Flat Brier | Flat log loss |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    def line(name, d):
        if not d:
            print(f"| {name} | 0 | | | | | | | | |"); return
        n = len(d); w = sum(y for _, y, _ in d); s = sum(p for p, _, _ in d) / n
        br = sum((p - y) ** 2 for p, y, _ in d) / n; ll = -sum(math.log(p if y else 1 - p) for p, y, _ in d) / n
        fb = sum((flat - y) ** 2 for _, y, _ in d) / n; fl = -sum(math.log(flat if y else 1 - flat) for _, y, _ in d) / n
        # Poisson-binomial tail by DP
        dp = [1.0]
        for p, _, _ in d:
            dp = [(dp[k] if k < len(dp) else 0) * (1 - p) + (dp[k - 1] * p if k else 0) for k in range(len(dp) + 1)]
        tail = sum(dp[: w + 1]); up = sum(dp[w:])
        print(f"| {name} | {n} | {s:.1%} | {w} ({w / n:.1%}) | {tail:.3f} | {up:.3f} | {br:.4f} | {ll:.4f} | {fb:.4f} | {fl:.4f} |")
    line("All", done)
    by = defaultdict(list)
    for t in done:
        by[sport_of(t[2])].append(t)
    for k in sorted(by):
        line(k, by[k])
    print(f"\nFlat baseline: every lead at {flat:.1%}, the hit rate of all {len(pool):,} legs settled since 21 Oct.\n")
    print("Calibration:\n")
    print("| Stated chance | Leads | Said (mean) | Landed | Hit rate | Gap |")
    print("|---|---|---|---|---|---|")
    for lo, hi in ((0, .65), (.65, .70), (.70, .75), (.75, .80), (.80, .85), (.85, 1.01)):
        b = [(p, y) for p, y, _ in done if lo <= p < hi]
        if b:
            s = sum(p for p, _ in b) / len(b); h = sum(y for _, y in b) / len(b)
            se = math.sqrt(s * (1 - s) / len(b))
            print(f"| {lo:.0%} to {min(hi, 1):.0%} | {len(b)} | {s:.1%} | {sum(y for _, y in b)} | {h:.1%} | {(h - s) * 100:+.1f} pts (SE {se * 100:.1f}) |")
    if done:
        base = sum(p for p, _, _ in done) / len(done)
        print(f"\nSample needed at the mean stated chance {base:.0%}: {S.n_needed(base, base - 0.10)} settled leads for a 10 point "
              f"overstatement, {S.n_needed(base, base - 0.05)} for 5 points (two-sided 5%, 80% power).")
    unsettled = [r for r in rows if not settled.get(S.key(r)) and r["kickoff"] <= now]
    if unsettled:
        print("\nPast kick-off and not settled, by sport and stat:\n")
        c = Counter((r.get("sport") or "?", r["stat"]) for r in unsettled)
        for (sp, st), v in c.most_common(15):
            print(f"- {sp}, {st}: {v}")


if __name__ == "__main__":
    item1()
    item2()
