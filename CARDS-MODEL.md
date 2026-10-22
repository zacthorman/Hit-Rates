# The cards model, the per-player cap and the cards backfill

Written 22 October 2026 on the `cards-model` branch. Every number below comes from `cards_model.py test` and `value_cap.py`. Both read only what is on disk and make no requests. The tables are pasted unedited; re-run the two commands to reproduce them.

## Verdict

1. **Team cards: the new model wins and is wired in.** A Poisson model on each side's own and provoked yellow cards over 10 and 38 games, the competition's card rate, both sides' fouls and the Elo gap beat the current team model (LightGBM on teamstyle.py) on all four held-out windows. Over the whole test period it was 0.0043 better in log loss (95% interval 0.0017 to 0.0070). On windows 3 and 4, which played no part in choosing it, it was 0.0041 better (0.0005 to 0.0080). The gain is small but consistent, and it is largest on the 2.5 and 3.5 lines and on match totals. It also beat the page's fouls heuristic, added up over the XI, by 0.0112 (0.0067 to 0.0156), and that was with the heuristic given its best scale. `context.py` now prices team Yellow cards legs with it; anything it cannot reach falls back to the team model.
2. **Player cards: half tested, wired in for the half that was.** The cache never says who was booked: the line-ups carry fouls and minutes but no cards, and SofaScore is not reachable from this machine. So a player's chance cannot be scored against his own card. What can be scored is the side's total, and there the cards model's chances add up better than the heuristic's, by the margin in point 1. The split between team-mates is the heuristic's own (fouls per 90 over expected minutes) and is **not backtested**. The page now shows the cards model's chance where it has one, says the split is untested, and still never counts a card line as value. The player-by-player test is built in and runs as soon as incident files are in `cache/`.
3. **Against the bookmaker: no verdict.** The repo has kept exchange prices for match cards on only 11 test-window matches (20 prices). On those, the new model scored worst (log loss 0.5244), behind the exchange (0.4957), the team model (0.4982) and the heuristic (0.4836). That is far too few matches to rank anything, and there are no settled player card prices at all.
4. **The cap: one value bet per player per game.** Two bets on one player land together, with a residual correlation of +0.62 (standard error 0.11), while team-mates' bets land independently (-0.01). A player's second-ranked single was said to land 69.9% of the time and landed 62.6% (91 legs). His first was said 70.4% and landed 74.5%. The profit table on the 73 settled Paddy Power value bets cannot tell the caps apart, so the profit numbers did not choose the cap. Applied to the per-fixture singles, the recorded fixture singles and the Paddy Power value lists and record.
5. **The cards backfill: not reachable from here.** `cards_backfill.py` needs no account, but SofaScore refuses connections from this container (403 at the egress proxy), so it has to run on the Mac. Nothing was fetched.

## What was tested, and how

`cards_model.py test` replays 6,746 cached matches in date order, using only what was known before each kick-off. The last 40% of dates are cut into four windows. Each model is fitted on everything before a window and scored on that window. The cards variant was chosen on windows 1 and 2 only (N4 by less than 0.0002 over N3 on those two) and confirmed on 3 and 4. Scores are log loss and Brier at the over 0.5, 1.5, 2.5 and 3.5 team lines and at the 2.5 to 6.5 match lines, with calibration pooled over the team lines. Intervals resample whole matches.

The models:

- **N1 to N4, the cards model**, Poisson regressions on logged inputs. Each side's record is pulled towards its league's average as if four league-average games had been added. A league's average is pulled towards the global one as if 60 team-games had been added. N1: own and provoked cards (what the opponent's opponents were shown) over 10 games, and home. N2 adds the competition's card rate. N3 adds the same over 38 games. N4 adds both sides' fouls over 10 games and the Elo gap. The fitted dispersion came out at zero, so team counts are priced as Poisson.
- **Team model (current)**, `teammodel_train.py`'s recipe refitted before every window: LightGBM (Poisson) on every teamstyle.py feature, early stopping on the last fifth of the training dates, negative binomial on top.
- **Team model, 0-0s kept**, the same, trained with the 0-0 matches it currently drops (below). It isolates how much of the gain is that fix: none of it. It got the average right (2.016 cards a side said, 1.999 landed, against 2.079 for the current model) but scored no better.
- **XI heuristic (current)**, the page's `cardCase` for every outfield starter, added up. The opponent factor needs the predicted shape, so it is left at 1 (the page holds it between 0.85 and 1.2). The side's projected fouls come from a fouls model fitted the same way. One scale, fitted on the training data, turns the XI's sum into the side's cards, because the sum also has to cover substitutes.

**A finding in the data.** SofaScore leaves the "Yellow cards" row out of a match's statistics when neither side was booked. In the cache, 208 matches with fouls recorded have no cards row, against 6 that carry an explicit 0-0, while one side on 0 is common (1,360). teamstyle.py reads the missing row as missing, so the team model has never trained on a 0-0, and its cards history skips those games. The cards model counts them as 0-0s. This affects only the cards stat, which now has its own model, so teamstyle.py is unchanged.

## Results: team and match cards

6746 matches, 8600 side rows, 3698 in the four test windows, 3613 priced by every model (the heuristic needs nine starters and seven with three real appearances).

| Window | From | To |
|---|---|---|
| 1 | 09 Apr 2026 | 09 May 2026 |
| 2 | 09 May 2026 | 15 Aug 2026 |
| 3 | 15 Aug 2026 | 13 Sep 2026 |
| 4 | 13 Sep 2026 | 19 Oct 2026 |

#### Team cards, log loss by window (mean of the 0.5, 1.5, 2.5 and 3.5 lines; lower is better)

| Model | W1 | W2 | W3 | W4 | Brier W1-W4 |
|---|---|---|---|---|---|
| N1 own+opp | 0.5209 | 0.5222 | 0.5008 | 0.5175 | 0.1724 / 0.1732 / 0.1638 / 0.1708 |
| N2 +league | 0.5204 | 0.5220 | 0.5000 | 0.5172 | 0.1722 / 0.1731 / 0.1635 / 0.1707 |
| N3 +long | 0.5152 | 0.5175 | 0.4979 | 0.5137 | 0.1704 / 0.1713 / 0.1628 / 0.1692 |
| N4 +fouls+elo | 0.5158 | 0.5166 | 0.4969 | 0.5112 | 0.1706 / 0.1709 / 0.1625 / 0.1683 |
| Team model (current) | 0.5182 | 0.5235 | 0.5003 | 0.5161 | 0.1711 / 0.1735 / 0.1638 / 0.1700 |
| Team model, 0-0s kept | 0.5174 | 0.5234 | 0.5000 | 0.5176 | 0.1708 / 0.1736 / 0.1636 / 0.1706 |
| XI heuristic (current) | 0.5249 | 0.5293 | 0.5033 | 0.5277 | 0.1743 / 0.1762 / 0.1652 / 0.1742 |

Chosen on windows 1 and 2: **N4 +fouls+elo**.

#### Team cards by line, all four windows (log loss / Brier)

| Model | over 0.5 | over 1.5 | over 2.5 | over 3.5 |
|---|---|---|---|---|
| N1 own+opp | 0.3854 / 0.1136 | 0.6625 / 0.2350 | 0.6143 / 0.2122 | 0.3978 / 0.1187 |
| N2 +league | 0.3849 / 0.1135 | 0.6622 / 0.2349 | 0.6137 / 0.2119 | 0.3972 / 0.1185 |
| N3 +long | 0.3827 / 0.1130 | 0.6577 / 0.2327 | 0.6092 / 0.2099 | 0.3934 / 0.1175 |
| N4 +fouls+elo | 0.3823 / 0.1129 | 0.6569 / 0.2323 | 0.6075 / 0.2092 | 0.3925 / 0.1172 |
| Team model (current) | 0.3837 / 0.1131 | 0.6583 / 0.2330 | 0.6138 / 0.2120 | 0.4006 / 0.1195 |
| Team model, 0-0s kept | 0.3834 / 0.1130 | 0.6591 / 0.2334 | 0.6137 / 0.2120 | 0.4006 / 0.1194 |
| XI heuristic (current) | 0.3880 / 0.1149 | 0.6698 / 0.2380 | 0.6231 / 0.2160 | 0.4030 / 0.1203 |

#### Chosen model minus the others, log loss, 95% interval resampling matches (negative favours the chosen model)

| Against | Windows | Difference | 95% interval |
|---|---|---|---|
| Team model (current) | all | -0.0043 | -0.0070 to -0.0017 |
| Team model (current) | windows 3-4 | -0.0041 | -0.0080 to -0.0005 |
| Team model, 0-0s kept | all | -0.0044 | -0.0072 to -0.0015 |
| Team model, 0-0s kept | windows 3-4 | -0.0047 | -0.0088 to -0.0011 |
| XI heuristic (current) | all | -0.0112 | -0.0156 to -0.0067 |
| XI heuristic (current) | windows 3-4 | -0.0115 | -0.0185 to -0.0051 |

#### Average cards a side, said against landed (common rows)

| Model | Said | Landed |
|---|---|---|
| N1 own+opp | 2.014 | 1.999 |
| N2 +league | 2.023 | 1.999 |
| N3 +long | 2.040 | 1.999 |
| N4 +fouls+elo | 2.039 | 1.999 |
| Team model (current) | 2.079 | 1.999 |
| Team model, 0-0s kept | 2.016 | 1.999 |
| XI heuristic (current) | 2.017 | 1.999 |

The heuristic's XI adds up to 0.91 of the side's cards on the training data (scale 1.10, 1.11, 1.11, 1.10 by window); it is scored above with that scale applied, which is its best case.

#### Calibration, the four team lines pooled

**N4 +fouls+elo**

| Said | n | Average said | Landed |
|---|---|---|---|
| 0% to 10% | 632 | 8.0% | 7.4% |
| 10% to 20% | 2385 | 14.8% | 13.0% |
| 20% to 30% | 1869 | 25.0% | 23.5% |
| 30% to 40% | 1586 | 34.6% | 32.2% |
| 40% to 50% | 1071 | 44.9% | 44.4% |
| 50% to 60% | 1539 | 55.4% | 57.6% |
| 60% to 70% | 1357 | 64.6% | 65.2% |
| 70% to 80% | 657 | 75.0% | 74.1% |
| 80% to 90% | 2634 | 85.7% | 86.1% |
| 90% to 100% | 722 | 91.7% | 93.2% |

**Team model (current)**

| Said | n | Average said | Landed |
|---|---|---|---|
| 0% to 10% | 339 | 8.2% | 8.3% |
| 10% to 20% | 2641 | 15.0% | 12.6% |
| 20% to 30% | 1606 | 25.3% | 22.5% |
| 30% to 40% | 1899 | 34.8% | 32.5% |
| 40% to 50% | 886 | 44.4% | 43.7% |
| 50% to 60% | 1423 | 55.9% | 54.8% |
| 60% to 70% | 1702 | 64.4% | 64.1% |
| 70% to 80% | 465 | 74.1% | 73.1% |
| 80% to 90% | 2798 | 86.4% | 86.2% |
| 90% to 100% | 693 | 91.5% | 91.6% |

**XI heuristic (current)**

| Said | n | Average said | Landed |
|---|---|---|---|
| 0% to 10% | 1054 | 6.7% | 9.5% |
| 10% to 20% | 2141 | 14.9% | 15.3% |
| 20% to 30% | 1777 | 24.8% | 25.1% |
| 30% to 40% | 1516 | 34.7% | 34.6% |
| 40% to 50% | 1260 | 44.9% | 43.6% |
| 50% to 60% | 1362 | 55.2% | 56.7% |
| 60% to 70% | 1217 | 64.7% | 64.9% |
| 70% to 80% | 1077 | 75.4% | 74.6% |
| 80% to 90% | 2150 | 85.5% | 86.3% |
| 90% to 100% | 898 | 92.4% | 90.8% |

#### Match cards (both sides' yellows), log loss / Brier

| Model | over 2.5 | over 3.5 | over 4.5 | over 5.5 | over 6.5 |
|---|---|---|---|---|---|
| N1 own+opp | 0.5705 / 0.1917 | 0.6761 / 0.2416 | 0.6484 / 0.2282 | 0.5272 / 0.1727 | 0.3689 / 0.1081 |
| N2 +league | 0.5707 / 0.1918 | 0.6754 / 0.2413 | 0.6472 / 0.2276 | 0.5252 / 0.1719 | 0.3670 / 0.1076 |
| N3 +long | 0.5666 / 0.1905 | 0.6696 / 0.2386 | 0.6412 / 0.2246 | 0.5207 / 0.1700 | 0.3653 / 0.1069 |
| N4 +fouls+elo | 0.5669 / 0.1906 | 0.6697 / 0.2387 | 0.6397 / 0.2239 | 0.5194 / 0.1695 | 0.3641 / 0.1065 |
| Team model (current) | 0.5723 / 0.1925 | 0.6773 / 0.2422 | 0.6488 / 0.2283 | 0.5278 / 0.1728 | 0.3690 / 0.1079 |
| Team model, 0-0s kept | 0.5708 / 0.1919 | 0.6755 / 0.2413 | 0.6476 / 0.2277 | 0.5275 / 0.1727 | 0.3695 / 0.1081 |
| XI heuristic (current) | 0.5742 / 0.1931 | 0.6774 / 0.2417 | 0.6542 / 0.2298 | 0.5287 / 0.1726 | 0.3743 / 0.1090 |

#### To be booked, player by player

0 test-window starters have their match's incidents cached, under the 200 this test needs. The cache holds no per-player cards until cards_backfill.py has run on the Mac; re-run `cards_model.py test` then.


#### Against the exchange: 20 match cards prices on 11 matches in the test windows

Landed 80.0%; the exchange said 64.0% on average.

| Source | Log loss | Brier |
|---|---|---|
| Exchange | 0.4957 | 0.1574 |
| N1 own+opp | 0.5313 | 0.1735 |
| N2 +league | 0.5328 | 0.1742 |
| N3 +long | 0.5100 | 0.1650 |
| N4 +fouls+elo | 0.5244 | 0.1716 |
| Team model (current) | 0.4982 | 0.1584 |
| Team model, 0-0s kept | 0.5025 | 0.1601 |
| XI heuristic (current) | 0.4836 | 0.1536 |

Reading the tables. The cards model's average is about 2% high (2.039 said, 1.999 landed). Its calibration table shows that as a point or two of over-statement between 10% and 40%, which the team model shares. The heuristic, given its best scale, is well calibrated on average. It loses on ranking: it cannot tell which sides will be booked more, because it knows nothing about the league or the opponent.

## Results: to be booked, per player

What the backtest can say about the player chances:

- **The level.** Unscaled, the page's heuristic for the XI adds up to 0.91 of the side's cards (scale 1.10 by window, every window within 0.01 of that). Outfield starters take an estimated 86% of a side's cards (`starter_share`: each half's cards per player-minute, about two thirds in the second half, starters from minute 0, substitutes from 90 minus their minutes, keepers left out). So the heuristic's chances run about 6% high on average (0.91 against 0.86). That estimate assumes every outfield player on the pitch is equally likely to be booked in a given minute of a half, and that the cards row counts only players. It is an estimate, not a measurement.
- **The side's total.** The cards model's chances add up to 86% of the cards model's expected cards for the side. Scored as side totals, that is the N4 row above, and it beat the heuristic's sum by 0.0112 in log loss (0.0067 to 0.0156).
- **The split.** Untested. The cards model shares the XI's cards out in proportion to the heuristic's own weights, his fouls per 90 over expected minutes, half last ten and half everything. Because cards per foul and the projected-fouls factor are the same for the whole side, they cancel. Whether a holding midfielder deserves more than his fouls say, or a forward less, cannot be checked without per-player cards.

The player-by-player test is in `cards_model.py` (`score_players`). It reads `cache/event_<id>_incidents.json` (what `cards_backfill.py` writes) and, once 200 test-window starters have one, prints log loss, Brier and calibration for the heuristic as it is against the cards model's split. Today it prints:

> 0 test-window starters have their match's incidents cached, under the 200 this test needs.

**Is it wired in?** Yes, for the part that was measured. The page's player chance moves from the heuristic's level to the cards model's level for the side, and keeps the heuristic's split. The profile says so ("The split between players is not backtested"). Card lines are still never value, on the page or in `pplog.py`, which already excludes `Card` even when the model priced it. The Paddy Power log will now record the cards model's chance (`source: fmodel`) with the heuristic's beside it (`site_chance`), so the two are compared on real prices and real bookings once the backfill or `pplog.py settle` has the incidents.

## Results: against the bookmaker

The repo's committed `exchange_log.json` and `market_prices.json` snapshots hold Betfair match cards over/under prices (the latest before kick-off, per match and line). Only 11 of those matches fall in the test windows with results in the cache. There are no settled player card prices: `best_bets.json` carries `exchange_p` on card legs only as null, and the Paddy Power card log is in `pplog/` on the Mac. The table is at the end of the cards section above. It says nothing either way: 20 prices on 11 matches, and 80% of the overs landed against the exchange's 64%.

## What changed

- `cards_model.py`: the backtest (`test`), the refit (`fit`, writes `cards_fit.json`), and `Live`, which replays the cache through the same `State` the backtest uses so live and backtest features cannot drift. A test replays a finished match as upcoming and checks the features and the expected cards are identical.
- `cards_fit.json`: N4 refitted on all 8,600 side rows, starter share 0.861, team dispersion 0 (Poisson).
- `context.py`: `team_model_mu("Yellow cards", ...)` asks the cards model first and passes the fixture's competition id; the team model is the fallback.
- `fmodel_live.py`: `add_cards` writes `lines["Card"]["1"]` for every starter the player model already covers, and each side's expected cards under `cards`, into `reports/fmodel.json`. Any failure is printed and the rest of the file is written as before. It adds about 25 seconds (one replay of the cache).
- `report.py`: `cardModelP` reads that chance. The profile's To be booked, its explanation and the Paddy Power Card line use it where it exists and the heuristic everywhere else.

To switch the cards model off: delete `cards_fit.json`. `context.py` falls back to the team model and `fmodel_live.py` writes no Card lines, so the page falls back to its heuristic. To refit after the cache grows: `python -B cards_model.py fit` (it re-runs the test first and stores the result in the file). The refit needs `lightgbm` and `pandas`, but only for the comparison with the team model; the live model needs only numpy.

## The per-player cap on value bets and singles

The problem, from the 21 October Paddy Power record: Cason Wallace had eight value bets in one game (steals 1.5 and 2.5, threes, points, rebounds, three combinations) and lost all eight. Devin Vassell lost five of five, Jayden Daniels four of four. They were one bet on one bad night, counted eight times.

`value_cap.py` is the backtest. It reads every settled single in `best_bets.json` (fixture singles and player lines). For the Paddy Power value bets it reads `pplog/` on the Mac, or failing that the "Recent value bets" rows of each committed `pp-results.html`, which is all this machine has.

#### Singles in best_bets.json: 1966 settled, 586 on players

How alike two legs land, as a residual correlation (0 independent, 1 the same bet):

| Pair | Pairs | Correlation | Standard error |
|---|---|---|---|
| same player | 117 | +0.62 | 0.11 |
| team-mates | 634 | -0.01 | 0.04 |
| opponents | 666 | -0.02 | 0.04 |

A player's legs in one game, ranked by the site's chance:

| Leg | n | Said | Landed |
|---|---|---|---|
| 1st | 482 | 70.4% | 74.5% |
| 2nd | 91 | 69.9% | 62.6% |
| 3rd or lower | 13 | 70.0% | 69.2% |

#### Paddy Power value bets: 73 settled, from pp-results.html history (recent value bets only)

| Cap per player | Bets | Won | Said | Landed | Profit | ROI | ROI 95% interval |
|---|---|---|---|---|---|---|---|
| 1 | 38 | 12 | 60.4% | 31.6% | -12.5u | -32.8% | -64.9% to +0.7% |
| 2 | 52 | 16 | 62.3% | 30.8% | -20.0u | -38.4% | -65.2% to -10.7% |
| 3 | 61 | 22 | 62.5% | 36.1% | -17.8u | -29.2% | -57.8% to +0.8% |
| none | 73 | 25 | 63.2% | 34.2% | -25.0u | -34.2% | -62.6% to -1.5% |

A value bet's rank among that player's value bets in the game, by edge:

| Leg | n | Said | Landed |
|---|---|---|---|
| 1st | 38 | 60.4% | 31.6% |
| 2nd | 14 | 67.7% | 28.6% |
| 3rd or lower | 21 | 65.4% | 42.9% |


How the cap was chosen. The profit table cannot choose it: 73 bets, and the intervals for every cap overlap almost entirely (-33% at a cap of 1, -34% with none). Two other results carry the decision:

- Legs on one player are close to one bet: a residual correlation of +0.62 on 117 pairs, against -0.01 for team-mates and -0.02 for opponents. A second leg on the same player roughly doubles the stake on one outcome without adding a second view of the game.
- A player's second leg was the weaker one. Ranked by the site's chance, his first legs landed 4 points above what was said and his second legs 7 points below (91 legs, so about plus or minus 10 points). On the value bets the second-ranked bets were also the worst (29% landed, 68% said), though on 14 bets.

Allowing two would keep half the correlated exposure and every one of the weaker second legs, so the cap is 1. It is the shakiest result in this file, because it rests on 91 and 73 settled bets. Re-run `python -B value_cap.py` on the Mac, where it reads the full `pplog/` record (177 settled value bets on 21 October, and growing), and raise `MAX_PER_PLAYER` if a cap of 2 starts to show more profit than 1 by more than the noise.

Where it applies (one constant, `value_cap.MAX_PER_PLAYER = 1`, mirrored as `VALUE_PER_PLAYER` in the page):

- `tonight.py`: "Best singles here", one leg per player, the best ranked kept. Team legs are not capped.
- `besttrack.py`: the three fixture singles recorded per fixture, the same way.
- `pplog.py`: the value bets in the record and on `pp-results.html` (settled and open), each player's biggest edge in a game. The record's headline figures will change on the next publish, because they will count one bet per player per game. The page says so.
- `report.py`: "Best value at Paddy Power" and "Bet365" on the Players tab, and the Value tab's Take and Acceptable lists, counted across both. The Value tab's "Left off" note counts the lines the cap drops, and every line is still on the player's profile.

## The cards backfill

`cards_backfill.py` fetches each recent match's incidents (`event/{id}/incidents`) from SofaScore: no account, no key, one request every 20 seconds or slower, stopping and locking itself out for 24 hours at the first refusal. It cannot run here: this container's egress proxy refuses `api.sofascore.com` and `www.sofascore.com` (HTTP 403 on CONNECT), and the cache in `cache_backtest.tar.zst` holds no incidents. Nothing was fetched, and no other source of per-player cards is reachable without a new account. On the Mac:

    caffeinate -i python cards_backfill.py --dry     # how many, how long
    caffeinate -i python cards_backfill.py           # the slow run

then `python -B cards_model.py test` prints the player-by-player section automatically.

## Tests

`tests/test_cards_model.py` (18 tests) and `tests/test_value_cap.py` (8). They cover reading a missing cards row as a 0-0, the page's heuristic reproduced to the digit, the Poisson and negative binomial tails against direct sums, the regression recovering known coefficients, XI chances adding up to the side, the live features matching the backtest row for a replayed match, the incident parsing and the player scorer, the `context.py` and `fmodel_live.py` wiring, the cap, and `pplog.cap_value`. The full suite is 82 tests, all passing (3 skipped, as before), and `verify.py` still reports that model.py and report.py agree. One thing to know: the existing suite rewrites `learned.json` when it runs (it did before this branch too), so that file was restored after every run and is not part of this change.
