import betfair_sb_prices as bf


def _ev():
    return {"lines": [{"player": "A", "market": "Shots", "price": 2.0, "mid": "924.1", "sid": 11},
                      {"player": "B", "market": "Shots", "price": 3.0, "mid": "924.1", "sid": 12},
                      {"player": "C", "market": "Old", "price": 4.0}],
            "team": [{"stat": "Corner kicks", "price": 1.9, "mid": "924.2", "sid": 21}],
            "goals": []}


def test_market_ids():
    assert bf.market_ids(_ev()) == ["924.1", "924.2"]


def test_apply_moves_drops_and_keeps():
    ev = _ev()
    prices = {"924.1": {"open": True, "runners": {11: 2.2, 12: None}},
              "924.2": {"open": False, "runners": {21: 1.8}}}
    assert bf.apply(ev, prices) == (1, 2, 1)
    assert [r["player"] for r in ev["lines"]] == ["A", "C"]
    assert ev["lines"][0]["price"] == 2.2 and ev["team"] == []
