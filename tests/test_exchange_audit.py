import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import exchange_audit as ea
import weekend


def _rec(eid=1, team="A", player=None, stat="Goals", line=0.5, over=True, result=None, value=None,
         market=0.6, model=0.6, back=None, lay=None, v=None):
    snap = {"t": 0, "model": model, "anchored": model, "market": market, "blend": market, "back": back,
            "lay": lay, "matched": 0, "tight": True, "w": 0.5, "value": v, "disagree": None}
    return {"event_id": eid, "fixture": "A v B", "competition": "X", "kickoff": 0, "sport": "football",
            "team": team, "player": player, "stat": stat, "period": "ALL", "line": line, "over": over,
            "family": f"{'player' if player else 'team'}|{stat}|exchange", "kind": "exchange",
            "mtype": "T", "first": snap, "last": snap, "seen": 2, "result": result, "value": value}


def test_commission_maths_matches_the_site():
    for p, b in ((0.5, 2.1), (0.3, 3.4), (0.8, 1.3)):
        assert abs(ea.ev(p, b) - weekend.ev_at(p, b, 0.05)) < 1e-12
    # Break-even sits above 1/back once commission is taken.
    assert ea.break_even(2.0) > 0.5
    assert abs(ea.ev(ea.break_even(2.0), 2.0)) < 1e-12
    assert ea.back_return(3.0, True) == 2 * 0.95
    assert ea.back_return(3.0, False) == -1.0


def test_blend_is_the_sites_log_odds_blend():
    m, s, w = 0.62, 0.48, 0.7
    z = w * math.log(m / (1 - m)) + (1 - w) * math.log(s / (1 - s))
    assert abs(ea.blend(m, s, w) - 1 / (1 + math.exp(-z))) < 1e-12
    assert abs(ea.blend(m, s, 1.0) - m) < 1e-9


def test_post_match_source_beats_the_log():
    log = {"k": _rec(player="P", stat="Shots on target", result="lose", value=0.0)}
    key = ea.stat_key(log["k"])
    res = ea.resolve(log, {"cache": {key: 2.0}, "best_bets": {}, "pplog": {}})["k"]
    assert res["result"] == "win" and res["ok"] and res["conflict"]


def test_player_lines_only_the_log_saw_are_set_aside_both_ways():
    log = {"zero": _rec(player="P", result="lose", value=0.0),
           "win": _rec(player="Q", result="win", value=1.0)}
    res = ea.resolve(log, {"cache": {}, "best_bets": {}, "pplog": {}})
    assert not res["zero"]["ok"] and not res["win"]["ok"]


def test_team_results_from_the_log_are_kept():
    log = {"k": _rec(result="lose", value=0.0)}
    res = ea.resolve(log, {"cache": {}, "best_bets": {}, "pplog": {}})["k"]
    assert res["ok"] and res["result"] == "lose" and res["why"] == "log only"


def test_a_value_settles_every_line_on_that_stat():
    log = {"o": _rec(line=1.5, over=True), "u": _rec(line=1.5, over=False)}
    key = ea.stat_key(log["o"])
    res = ea.resolve(log, {"cache": {}, "best_bets": {key: 2.0}, "pplog": {}})
    assert res["o"]["result"] == "win" and res["u"]["result"] == "lose"


def test_dnp_is_a_void_not_a_zero():
    log = {"k": _rec(player="P", result="lose", value=0.0)}
    res = ea.resolve(log, {"cache": {ea.stat_key(log["k"]): "dnp"}, "best_bets": {}, "pplog": {}})["k"]
    assert res["result"] == "void" and not res["ok"]


def test_one_side_per_line():
    log = {"o": _rec(over=True, result="win", value=1.0, market=0.6),
           "u": _rec(over=False, result="lose", value=1.0, market=0.4)}
    res = ea.resolve(log, {"cache": {}, "best_bets": {}, "pplog": {}})
    rows = ea.rows_for(log, res)
    assert len(rows) == 1 and rows[0]["over"]
    assert len(ea.rows_for(log, res, one_side=False)) == 2


def test_lineups_before_kick_off_are_not_post_match():
    pre = {"home": {"players": [{"player": {"name": "P"}, "statistics": {}}]}}
    post = {"home": {"players": [{"player": {"name": "P"}, "statistics": {"minutesPlayed": 90}}]}}
    assert not ea.lineups_post_match(pre)
    assert ea.lineups_post_match(post)


def test_goals_count_own_goals_for_the_other_side():
    lu = {"home": {"players": [{"statistics": {"goals": 2, "minutesPlayed": 90}},
                               {"statistics": {"ownGoals": 1, "minutesPlayed": 90}}]},
          "away": {"players": [{"statistics": {"goals": 1, "minutesPlayed": 90}}]}}
    assert ea.goals_from_lineups(lu) == (2, 2)


def test_spread_band_runs_from_lay_to_back():
    log = {"k": dict(_rec(back=2.0, lay=2.04, market=0.495), kind="exchange")}
    s = ea.spread_check(log)
    assert s["n"] == 1 and s["inside"] == 1 and s["median_width"] > 0


def test_fitted_back_margin_recovers_a_known_margin():
    rng = random.Random(1)
    rows = []
    for i in range(20000):
        back = rng.choice((1.5, 2.0, 3.0, 5.0))
        p = (1 / back) / 1.2
        rows.append({"back": back, "kind": "back", "over": True, "won": rng.random() < p, "event_id": i})
    assert abs(ea.fitted_back_margin(rows) - 0.2) <= 0.03


def test_market_only_rule_scores_zero_against_itself():
    rng = random.Random(2)
    rows = []
    for i in range(200):
        m = rng.uniform(0.2, 0.8)
        rows.append({"event_id": i // 3, "market": m, "model": m, "anchored": m, "blend": m,
                     "family": "f", "won": rng.random() < m})
    cv = ea.cv_rules(rows)
    assert cv["Betfair only"]["vs_betfair"] == 0
    assert abs(cv["Fixed 50/50"]["vs_betfair"]) < 1e-9


def test_cluster_bootstrap_is_repeatable():
    rows = [{"event_id": i % 7, "x": i} for i in range(50)]
    f = lambda rs: sum(r["x"] for r in rs) / len(rs)
    assert ea.cluster_boot(rows, f, n=200) == ea.cluster_boot(rows, f, n=200)
