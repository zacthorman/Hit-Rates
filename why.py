"""
Why a pick should land, in plain sentences, from the numbers behind it.

    import why
    why.reasons(leg)   # -> {"for": [...], "against": [...], "steps": [...]}

Nothing here decides anything. The chance a pick is ranked on is built in
weekend.py, strength.py and the exchange blend; this reads the pieces each of
those left on the leg and says what each one contributed, in the order they
were applied:

  for / against   the evidence pulling each way: the season record, the
                  last five, the average against the line, the record
                  against similar opposition, what team strength and the
                  projection expect, what the market thinks.
  steps           how the chance was built, number by number: record ->
                  strength blend or shrink -> self-correction -> exchange
                  blend -> value at the price on offer.

The page shows `for` and `against` up front and `steps` behind a fold.
"""

from __future__ import annotations


def _pct(p) -> str:
    return f"{round(p * 100)}%"


def _num(x) -> str:
    if x is None:
        return "-"
    return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"


def _bet(leg) -> str:
    stat = (leg.get("stat") or "").lower()
    if leg.get("alt"):
        return f"{leg.get('threshold')}+ {stat}"
    return f"{'over' if leg.get('over', True) else 'under'} {leg.get('line')} {stat}"


def _landed(v, line, over) -> bool:
    return v > line if over else v < line


def _who(leg) -> str:
    return leg.get("player") or leg.get("team") or "they"


def _opp(leg) -> str:
    fx = leg.get("fixture") or {}
    t = leg.get("team")
    if t and fx.get("home") and fx.get("away"):
        return fx["away"] if t == fx["home"] else fx["home"]
    return "the opposition"


def _implied(leg):
    try:
        import weekend
        data, mp = weekend._prices()
        if data and mp:
            return mp.implied(data, (leg.get("fixture") or {}).get("id"))
    except Exception:
        return None
    return None


def reasons(leg: dict) -> dict:
    pro: list[str] = []
    con: list[str] = []
    steps: list[str] = []
    over = bool(leg.get("over", True))
    line = leg.get("line")
    who = _who(leg)
    hits, n = leg.get("hits"), leg.get("total")
    where = {"home": " at home", "away": " away"}.get(leg.get("venue") or "", "")
    unit = "appearances" if leg.get("player") else "games"

    # -- the record
    if hits is not None and n:
        rate = hits / n
        s = f"Landed in {hits} of {who}'s last {n} {unit}{where} ({_pct(rate)})."
        (pro if rate >= 0.5 else con).append(s)

    # -- the last five, oldest first
    last = leg.get("last") or []
    if last and isinstance(line, (int, float)):
        k = sum(1 for v in last if _landed(v, line, over))
        seq = ", ".join(_num(v) for v in last)
        s = f"Last {len(last)}: {seq} ({k} of {len(last)} {'cleared' if over else 'stayed under'} {line})."
        (pro if k / len(last) >= 0.6 else con if k / len(last) <= 0.4 else pro).append(s)

    # -- the average against the line
    avg = leg.get("avg")
    if avg is not None and isinstance(line, (int, float)):
        margin = avg - line if over else line - avg
        if abs(margin) >= 0.1 * max(1.0, abs(line)):
            s = f"Averages {_num(avg)} against a line of {line}."
            (pro if margin > 0 else con).append(s)

    # -- team strength
    st = leg.get("strength") or {}
    if st.get("team") is not None:
        gap = int(st.get("gap") or 0)
        if st.get("marketGap") is not None and st.get("eloGap") is not None:
            mw = st.get("marketWin")
            s = (f"Betfair has {leg.get('team')} {_pct(mw)} to win where the ratings said "
                 f"{_pct(st.get('win') or 0)}, so the strength gap used ({gap:+d}) leans "
                 f"{round((st.get('marketWeight') or 0) * 100)}% on the market's.")
            steps.append(s)
        else:
            steps.append(f"{leg.get('team')} rated {st.get('team')} ({st.get('teamLabel')}) v "
                         f"{_opp(leg)} {st.get('opp')} ({st.get('oppLabel')}), a gap of {gap:+d}.")
        sh, sn = st.get("similarHits"), st.get("similarN")
        if sn and sn >= 3:
            r = sh / sn
            s = f"Against opposition of a similar standing: {_num(sh)} of {_num(sn)} weighted games ({_pct(r)})."
            (pro if r >= 0.5 else con).append(s)
        exp = st.get("eloExpected")
        if exp is not None and isinstance(line, (int, float)):
            good = exp > line if over else exp < line
            s = f"For a gap like tonight's, strength expects {_num(exp)} {(leg.get('stat') or '').lower()}."
            (pro if good else con).append(s)
        proj = st.get("projection")
        if proj is not None and isinstance(line, (int, float)):
            good = proj > line if over else proj < line
            (pro if good else con).append(f"The league projection says {_num(proj)}.")

    # -- what the market expects of the match
    imp = _implied(leg)
    if imp:
        fx = leg.get("fixture") or {}
        if imp.get("sport") == "football" and imp.get("home") is not None and imp.get("away") is not None \
                and isinstance(imp.get("home"), (int, float)) and imp.get("fitError") is not None:
            steps.append(f"Betfair's prices imply {fx.get('home')} {imp['home']:.1f} goals and "
                         f"{fx.get('away')} {imp['away']:.1f}.")
        elif imp.get("homePoints") is not None:
            steps.append(f"Betfair's total and handicap imply {fx.get('home')} {imp['homePoints']:.1f} "
                         f"and {fx.get('away')} {imp['awayPoints']:.1f} points.")

    # -- how the chance was built
    if leg.get("pStrength"):
        rec = 1 / leg["fairRecord"] if leg.get("fairRecord") else None
        steps.append(f"Record alone {_pct(rec) if rec else '-'}; blended with the similar-opposition record, "
                     f"the strength expectation and the projection: {_pct(leg['pStrength'])}.")
    elif leg.get("pShrunk"):
        steps.append(f"Player records overstate (the site's settled player picks land below what they said), "
                     f"so {hits}/{n} is pulled towards evens: {_pct(leg['pShrunk'])}.")
    if leg.get("pLearned") and leg.get("pBase"):
        steps.append(f"Self-correction from settled picks moved it from {_pct(leg['pBase'])} to {_pct(leg['pLearned'])}.")

    q = leg.get("exchange")
    if q:
        pm, px = leg.get("pModel"), q.get("p")
        pm = leg.get("pAnchored", pm)
        raw_pm = leg.get("pModel")
        kind = q.get("kind")
        src = {"back": f"Betfair back price {q.get('back')}, margin estimated off",
               "derived": f"Betfair's goal model (expected {q.get('lambda')})",
               }.get(kind, f"Betfair {q.get('market') or 'exchange'}")
        money = f", £{round(q.get('matched') or 0):,} matched" if q.get("matched") else ""
        an = leg.get("anchor") or {}
        pa = leg.get("pAnchored")
        if pa is not None and abs(pa - (raw_pm or 0)) >= 0.005:
            steps.append(f"Across {an.get('legs')} bets like this on the exchange this round the model runs "
                         f"{'high' if (an.get('bias') or 0) > 0 else 'low'} on the over side, so its "
                         f"{_pct(raw_pm)} is taken back to {_pct(pa)} before comparing.")
        steps.append(f"{src}{money}: {_pct(px)}. Model {_pct(pm)}. Blended at "
                     f"{round((leg.get('exchangeWeight') or 0) * 100)}% market: {_pct(leg.get('pExchange') or pm)}.")
        if leg.get("disagree") is not None:
            con.append(f"Model and market are {round(abs(leg['disagree']) * 100)} points apart. A gap that size "
                       f"is more often the model missing something (team news, a rotation) than a real edge.")
        elif abs((pm or 0) - (px or 0)) <= 0.05:
            pro.append(f"The market agrees: {_pct(px)} on Betfair against the model's {_pct(pm)}.")
        elif (pm or 0) > (px or 0):
            pro.append(f"Model higher than the market ({_pct(pm)} v {_pct(px)}), which is where any edge comes from.")
        else:
            con.append(f"Market higher than the model ({_pct(px)} v {_pct(pm)}): the price is short for what the record says.")
        if leg.get("player") and (pm or 0) > (px or 0) + 0.03 and (leg.get("fixture") or {}).get("sport", "football") == "football":
            con.append("The market prices in the chance he is benched or taken off early; his record only "
                       "counts games he played 45 minutes or more.")
        v = leg.get("value")
        if v is not None:
            steps.append(f"At {q.get('back')}, after commission, every £10 staked is worth "
                         f"{'+' if v >= 0 else '-'}£{abs(v) * 10:.2f} on average.")

    return {"for": pro[:5], "against": con[:4], "steps": steps}
