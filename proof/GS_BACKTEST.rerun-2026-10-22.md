# Game state walk-forward backtest

Generated 2026-10-22T11:06:00+00:00. 7167 matches, 9332 team rows, 67346 player rows. Each model fitted on everything before a test window, scored on the last 40% of dates in four windows.

Possession: predicted from both sides' usual share, error 7.3 pts; a side's usual share alone, 8.5 pts.

Log loss of the over/under at each side's own average (lower is better). M0 own average, M1 + opponent, M2 + game state, GS the page's unfitted formula.


## Team stats

| Stat | n | M0 | M1 +opp | M2 +gs | GS page | game state coef | used |
|---|---|---|---|---|---|---|---|
| Total shots | 3726 | 0.6909 | 0.6324 | 0.6323 | 0.6694 | +0.27 | no |
| Shots on target | 3778 | 0.6890 | 0.6543 | 0.6544 | 0.6805 | +0.33 | no |
| Corner kicks | 3778 | 0.6842 | 0.6388 | 0.6373 | 0.6684 | +0.49 | yes |
| Big chances | 3626 | 0.6800 | 0.6462 | 0.6470 | 0.6758 | +0.28 | no |
| Fouls | 3772 | 0.6902 | 0.6595 | 0.6597 | 0.7140 | +0.02 | no |
| Total tackles | 3716 | 0.6949 | 0.6619 | 0.6608 | 0.7049 | +0.12 | yes |
| Yellow cards | 3630 | 0.6876 | 0.6562 | 0.6561 | 0.6872 | +0.18 | no |
| Clearances | 3716 | 0.6863 | 0.6497 | 0.6488 | 0.6969 | -0.23 | yes |
| Goalkeeper saves | 3744 | 0.6964 | 0.6498 | 0.6487 | 0.6842 | +0.47 | yes |

## Player stats

| Stat | n | M0 | M1 +opp | M2 +gs | GS page | game state coef | used |
|---|---|---|---|---|---|---|---|
| Shots | 26620 | 0.6733 | 0.6646 | 0.6634 | 0.6709 | +0.70 | yes |
| Shots on target | 22957 | 0.5705 | 0.5655 | 0.5651 | 0.5694 | +0.68 | yes |
| Fouls | 26967 | 0.6689 | 0.6504 | 0.6504 | 0.6722 | +0.10 | no |
| Fouled | 26740 | 0.6656 | 0.6539 | 0.6539 | 0.6682 | +0.18 | no |
| Tackles | 27081 | 0.6710 | 0.6563 | 0.6562 | 0.6729 | +0.15 | yes |

## Player calibration at 1+, 2+, 3+

Fitted on the first 60% of dates, scored on the rest. 'Said' is the model's average chance in the bucket, 'got' how often it landed.

- Shots 1+: 50%-60%: said 55%, got 50% (n 4152); 60%-70%: said 65%, got 62% (n 4281); 70%-80%: said 75%, got 75% (n 4408); 80%-90%: said 85%, got 88% (n 4334)
- Shots 2+: 50%-60%: said 55%, got 61% (n 2705); 60%-70%: said 64%, got 69% (n 1830); 70%-80%: said 74%, got 80% (n 768); 80%-90%: said 84%, got 93% (n 103)
- Shots 3+: 50%-60%: said 54%, got 57% (n 488); 60%-70%: said 64%, got 77% (n 101)
- Shots on target 1+: 50%-60%: said 55%, got 57% (n 2396); 60%-70%: said 64%, got 69% (n 1082); 70%-80%: said 73%, got 78% (n 193)
- Fouls 1+: 50%-60%: said 56%, got 53% (n 6967); 60%-70%: said 65%, got 64% (n 12167); 70%-80%: said 73%, got 74% (n 4965); 80%-90%: said 81%, got 83% (n 105)
- Fouls 2+: 50%-60%: said 52%, got 59% (n 63)
- Fouled 1+: 50%-60%: said 55%, got 53% (n 5947); 60%-70%: said 65%, got 63% (n 7072); 70%-80%: said 74%, got 76% (n 5009); 80%-90%: said 83%, got 85% (n 1372)
- Fouled 2+: 50%-60%: said 54%, got 58% (n 1161); 60%-70%: said 64%, got 71% (n 255)
- Tackles 1+: 50%-60%: said 56%, got 53% (n 2895); 60%-70%: said 66%, got 64% (n 6304); 70%-80%: said 75%, got 75% (n 10301); 80%-90%: said 83%, got 84% (n 5184)
- Tackles 2+: 50%-60%: said 54%, got 54% (n 4724); 60%-70%: said 64%, got 66% (n 1227); 70%-80%: said 73%, got 80% (n 116)
- Tackles 3+: 50%-60%: said 53%, got 58% (n 74)
