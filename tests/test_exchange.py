import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import market_prices as mp
import weekend


def _r(name, h, back, lay):
    return {"name": name, "handicap": h, "back": back, "lay": lay,
            "price": (back + lay) / 2 if back and lay and lay / back < 1.3 else None}


def test_handicap_pairs_by_opposite_line():
    rs = [_r("A", -0.5, 4.6, 4.9), _r("B", 0.5, 1.25, 1.28),
          _r("A", 0.5, 4.5, 4.9), _r("B", -0.5, 1.26, 1.29)]
    mp._devig(rs, "HANDICAP")
    assert abs(rs[0]["p"] + rs[1]["p"] - 1) < 1e-3
    assert rs[1]["p"] > 0.75


def test_totals_pair_over_under():
    rs = [_r("Under", 41.5, 1.9, 1.96), _r("Over", 41.5, 2.04, 2.12)]
    mp._devig(rs, "COMBINED_TOTAL")
    assert abs(rs[0]["p"] + rs[1]["p"] - 1) < 1e-3


def test_back_only_list_never_normalised():
    rs = [_r("X", 0, 2.3, None), _r("Y", 0, 2.5, None)]
    mp._devig(rs, "TO_SCORE")
    assert rs[0]["p"] is None
    q = mp._back_only(rs[0], {"type": "TO_SCORE", "name": "To score", "matched": 0}, True)
    assert q["kind"] == "back" and q["back"] == 2.3
    assert q["p"] < 1 / 2.3


def test_band_edges():
    m = {"type": "CORNER_ODDS", "name": "Corners", "matched": 0,
         "runners": [_r("9 or less", 0, 1.92, 2.1), _r("10 - 12", 0, 2.88, 3.85), _r("13 or more", 0, 4.2, 6.0)]}
    mp._devig(m["runners"], "CORNER_ODDS")
    under = mp._band(m, 9.5, False)
    over = mp._band(m, 9.5, True)
    assert abs(under["p"] + over["p"] - 1) < 1e-3
    assert under["back"] == 1.92 and over["back"] is None


def test_goal_model_reproduces_inputs():
    ev = {"sport": "football", "betfair": "Home v Away", "swapped": False, "markets": [
        {"type": "MATCH_ODDS", "name": "Match Odds", "matched": 9000, "runners": [
            {"name": "Home", "p": 0.50, "back": 1.98, "lay": 2.0},
            {"name": "Away", "p": 0.25, "back": 3.95, "lay": 4.0},
            {"name": "The Draw", "p": 0.25, "back": 3.95, "lay": 4.0}]},
        {"type": "OVER_UNDER_25", "name": "O/U 2.5", "matched": 9000, "runners": [
            {"name": "Under 2.5 Goals", "p": 0.48, "back": 2.06, "lay": 2.08},
            {"name": "Over 2.5 Goals", "p": 0.52, "back": 1.92, "lay": 1.94}]}]}
    data = {"events": {"1": ev}}
    mp._GOALS.clear()
    g = mp.goal_model(data, 1)
    h, d, a, tot = mp._probs(g["home"], g["away"])
    assert abs(h - 0.5) < 0.04 and abs(a - 0.25) < 0.04
    assert abs(sum(tot[3:]) - 0.52) < 0.04
    assert g["home"] > g["away"]


def test_ev_after_commission():
    assert abs(weekend.ev_at(0.5, 2.0, 0.0)) < 1e-9
    assert weekend.ev_at(0.5, 2.0, 0.05) < 0
    assert weekend.ev_at(0.6, 2.0, 0.05) > 0
