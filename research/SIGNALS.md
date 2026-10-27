# Which extra data improves the best selections? (26 Oct 2026, research/signals.py)

Every signal we hold, tested two ways: on Paddy Power's real prices (13-25 Oct, NBA + NFL,
1,652 bets in the pool: model edge 3%+, price 1.60-2.30), and on the long back-test of games
the models never saw (26,099 bets; stand-in lines, so only the difference between the two
columns means anything). A signal is only adopted if it helps in BOTH.

**Adopted:** team-mates missing. Unders on a player whose side is missing regulars lost 12%
on real prices (106 bets); skipping them, and overs when fewer than usual are missing, lifted
the form-filtered pool from +6.7% to +9.0% on real prices and +25.7% to +30.6% on the long
test. In selections.py from 26 Oct (thresholds in selections_thresholds.json). On the daily
top-8 list itself the change is inside the noise (47 bets +14.1% v 45 bets +10.8%).

**Watching, not adopted:** starter (helps on the long test, barely on real prices; adopting it
would drop most starters' unders); fading the recent trend (last 3 v last 10 and minutes trend
pointing against the bet did much better on real prices, +18% v +7%, but the long test says the
opposite: bookmakers may over-react to streaks, needs more real data).

**Rejected:** back-to-back favouring unders, rest, home, blowout risk, opponent conceding to his
position: each hurt or did nothing in both tests (the model already uses most of them).

Already in the filter and confirmed in both: model edge size, form 7/10 + 3/5.

### Paddy's real prices, 13-25 Oct, NBA + NFL: 1652 bets, 52 games, ROI +2.5%

| signal | bets it favours | ROI when it agrees | ROI when it disagrees | difference |
|---|---|---|---|---|
| he is listed questionable | 45/1652 | +28.3% | +1.8% | +26.5% |
| team-mates missing | 182/476 | -7.3% | -21.0% | +13.6% |
| form 7/10 + 3/5 | 719/1652 | +6.7% | -0.8% | +7.4% |
| weighted average v line | 820/1640 | +6.3% | -0.3% | +6.6% |
| model edge size | 825/1652 | +4.9% | +0.1% | +4.9% |
| form last 10 rate | 780/1652 | +4.5% | +0.6% | +3.9% |
| price shortened after logging | 113/1652 | +5.3% | +2.3% | +3.1% |
| form last 5 rate | 726/1652 | +3.4% | +1.7% | +1.7% |
| head to head v line | 354/710 | +3.7% | +2.4% | +1.3% |
| his team stronger (elo) | 806/1606 | +3.2% | +1.9% | +1.2% |
| starter | 278/455 | +3.1% | +2.8% | +0.4% |
| usage trend | 692/1384 | +2.8% | +4.4% | -1.6% |
| opponent concedes to his position | 797/1600 | +1.1% | +4.7% | -3.5% |
| home | 587/815 | -0.1% | +3.8% | -4.0% |
| targets trend | 100/210 | -5.8% | -1.5% | -4.3% |
| mismatch |elo| (blowout risk) | 798/1575 | -1.7% | +7.3% | -9.0% |
| last 3 v last 10 (stat) | 813/1628 | -3.4% | +9.2% | -12.5% |
| minutes trend | 689/1379 | -2.5% | +10.2% | -12.7% |
| days rest | 738/1498 | -4.7% | +10.5% | -15.2% |
| back-to-back | 137/197 | -10.0% | +14.0% | -24.1% |

### real prices, NBA only: 1389 bets, 39 games, ROI +3.8%

| signal | bets it favours | ROI when it agrees | ROI when it disagrees | difference |
|---|---|---|---|---|
| he is listed questionable | 44/1389 | +27.0% | +3.1% | +24.0% |
| team-mates missing | 57/231 | -20.5% | -28.9% | +8.4% |
| form 7/10 + 3/5 | 640/1389 | +6.5% | +1.5% | +5.0% |
| weighted average v line | 692/1384 | +6.2% | +1.9% | +4.2% |
| price shortened after logging | 106/1389 | +6.9% | +3.6% | +3.4% |
| his team stronger (elo) | 686/1367 | +5.3% | +2.1% | +3.3% |
| model edge size | 694/1389 | +5.3% | +2.3% | +3.0% |
| form last 10 rate | 687/1389 | +4.4% | +3.2% | +1.2% |
| starter | 278/455 | +3.1% | +2.8% | +0.4% |
| form last 5 rate | 651/1389 | +3.9% | +3.8% | +0.1% |
| head to head v line | 337/676 | +6.0% | +5.9% | +0.1% |
| usage trend | 692/1384 | +2.8% | +4.4% | -1.6% |
| opponent concedes to his position | 674/1352 | +3.0% | +5.6% | -2.6% |
| mismatch |elo| (blowout risk) | 679/1355 | +0.3% | +8.4% | -8.0% |
| home | 499/706 | -2.1% | +7.3% | -9.5% |
| days rest | 664/1320 | -2.1% | +10.5% | -12.5% |
| minutes trend | 689/1379 | -2.5% | +10.2% | -12.7% |
| last 3 v last 10 (stat) | 691/1383 | -3.7% | +12.0% | -15.7% |
| back-to-back | 137/197 | -10.0% | +14.0% | -24.1% |

### real prices, NFL only: 263 bets, 13 games, ROI -4.6%

| signal | bets it favours | ROI when it agrees | ROI when it disagrees | difference |
|---|---|---|---|---|
| home | 88/109 | +11.3% | -30.7% | +42.0% |
| head to head v line | 17/34 | -43.3% | -68.6% | +25.3% |
| weighted average v line | 128/256 | +7.0% | -12.6% | +19.6% |
| form 7/10 + 3/5 | 79/263 | +7.9% | -9.9% | +17.9% |
| form last 10 rate | 93/263 | +5.3% | -9.9% | +15.2% |
| model edge size | 131/263 | +2.7% | -11.7% | +14.4% |
| team-mates missing | 125/245 | -1.4% | -9.5% | +8.1% |
| form last 5 rate | 75/263 | -0.2% | -6.3% | +6.2% |
| last 3 v last 10 (stat) | 122/245 | -1.2% | -6.7% | +5.5% |
| targets trend | 100/210 | -5.8% | -1.5% | -4.3% |
| opponent concedes to his position | 123/248 | -9.1% | -0.6% | -8.5% |
| his team stronger (elo) | 120/239 | -9.3% | +1.1% | -10.4% |
| mismatch |elo| (blowout risk) | 119/220 | -13.3% | +0.5% | -13.7% |
| days rest | 74/178 | -28.1% | +10.5% | -38.7% |

### Long back-test, unseen games, stand-in lines (compare columns, not the level): 26099 bets, 434 games, ROI +22.7%

| signal | bets it favours | ROI when it agrees | ROI when it disagrees | difference |
|---|---|---|---|---|
| model edge size | 13024/26099 | +34.3% | +11.2% | +23.2% |
| starter | 10979/21016 | +28.1% | +19.0% | +9.1% |
| minutes trend | 11517/23034 | +27.9% | +20.3% | +7.5% |
| team-mates missing | 4744/15717 | +24.1% | +16.9% | +7.2% |
| form last 5 rate | 9260/26099 | +26.7% | +20.5% | +6.3% |
| last 3 v last 10 (stat) | 12955/25975 | +25.4% | +20.0% | +5.5% |
| form 7/10 + 3/5 | 9075/26099 | +25.7% | +21.1% | +4.5% |
| targets trend | 1499/2959 | +14.5% | +10.7% | +3.8% |
| form last 10 rate | 10364/26099 | +24.9% | +21.3% | +3.6% |
| usage trend | 11517/23034 | +25.8% | +22.4% | +3.4% |
| his team stronger (elo) | 13007/26010 | +23.4% | +21.9% | +1.6% |
| opponent concedes to his position | 12790/25471 | +22.8% | +22.6% | +0.2% |
| home | 10248/12812 | +21.3% | +22.5% | -1.3% |
| back-to-back | 1095/2020 | +21.5% | +23.1% | -1.6% |
| mismatch |elo| (blowout risk) | 12970/25938 | +21.8% | +23.6% | -1.8% |
| days rest | 12493/24535 | +20.9% | +25.4% | -4.5% |

### Agreement: difference on real prices v long back-test

- model edge size: real +4.9%, long +23.2% (both help)
- team-mates missing: real +13.6%, long +7.2% (both help)
- form 7/10 + 3/5: real +7.4%, long +4.5% (both help)
- starter: real +0.4%, long +9.1% (both help)
- form last 5 rate: real +1.7%, long +6.3% (both help)
- form last 10 rate: real +3.9%, long +3.6% (both help)
- his team stronger (elo): real +1.2%, long +1.6% (both help)
- usage trend: real -1.6%, long +3.4% (disagree)
- targets trend: real -4.3%, long +3.8% (disagree)
- opponent concedes to his position: real -3.5%, long +0.2% (disagree)
- minutes trend: real -12.7%, long +7.5% (disagree)
- home: real -4.0%, long -1.3% (both hurt)
- last 3 v last 10 (stat): real -12.5%, long +5.5% (disagree)
- mismatch |elo| (blowout risk): real -9.0%, long -1.8% (both hurt)
- days rest: real -15.2%, long -4.5% (both hurt)
- back-to-back: real -24.1%, long -1.6% (both hurt)
