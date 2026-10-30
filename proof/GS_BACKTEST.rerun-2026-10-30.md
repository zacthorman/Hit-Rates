# Game state walk-forward backtest

Generated 2026-10-30T10:15:51+00:00. 7661 matches, 10138 team rows, 73934 player rows. Each model fitted on everything before a test window, scored on the last 40% of dates in four windows.

Possession: predicted from both sides' usual share, error 7.3 pts; a side's usual share alone, 8.5 pts.

Log loss of the over/under at each side's own average (lower is better). M0 own average, M1 + opponent, M2 + game state, GS the page's unfitted formula.


## Team stats

| Stat | n | M0 | M1 +opp | M2 +gs | GS page | game state coef | used |
|---|---|---|---|---|---|---|---|
| Total shots | 4056 | 0.6903 | 0.6325 | 0.6326 | 0.6715 | +0.24 | no |
| Shots on target | 4094 | 0.6890 | 0.6523 | 0.6524 | 0.6806 | +0.27 | no |
| Corner kicks | 4094 | 0.6849 | 0.6402 | 0.6386 | 0.6693 | +0.45 | yes |
| Big chances | 3932 | 0.6800 | 0.6475 | 0.6482 | 0.6766 | +0.22 | no |
| Fouls | 4070 | 0.6907 | 0.6578 | 0.6580 | 0.7147 | +0.02 | no |
| Total tackles | 4042 | 0.6933 | 0.6593 | 0.6583 | 0.7020 | +0.12 | yes |
| Yellow cards | 3940 | 0.6858 | 0.6549 | 0.6548 | 0.6852 | +0.16 | yes |
| Clearances | 4042 | 0.6874 | 0.6517 | 0.6505 | 0.6999 | -0.23 | yes |
| Goalkeeper saves | 4048 | 0.6958 | 0.6499 | 0.6482 | 0.6830 | +0.50 | yes |

## Player stats

| Stat | n | M0 | M1 +opp | M2 +gs | GS page | game state coef | used |
|---|---|---|---|---|---|---|---|
| Shots | 29194 | 0.6729 | 0.6633 | 0.6622 | 0.6706 | +0.68 | yes |
| Shots on target | 25282 | 0.5725 | 0.5671 | 0.5667 | 0.5715 | +0.63 | yes |
| Fouls | 29615 | 0.6694 | 0.6502 | 0.6502 | 0.6726 | +0.11 | no |
| Fouled | 29311 | 0.6662 | 0.6548 | 0.6547 | 0.6687 | +0.19 | no |
| Tackles | 29595 | 0.6712 | 0.6567 | 0.6565 | 0.6729 | +0.15 | yes |

## Player calibration at 1+, 2+, 3+

Fitted on the first 60% of dates, scored on the rest. 'Said' is the model's average chance in the bucket, 'got' how often it landed.

- Shots 1+: 50%-60%: said 55%, got 51% (n 4633); 60%-70%: said 65%, got 63% (n 4753); 70%-80%: said 75%, got 74% (n 4841); 80%-90%: said 85%, got 88% (n 4761)
- Shots 2+: 50%-60%: said 55%, got 60% (n 2982); 60%-70%: said 65%, got 69% (n 2006); 70%-80%: said 74%, got 79% (n 850); 80%-90%: said 83%, got 91% (n 125)
- Shots 3+: 50%-60%: said 54%, got 57% (n 531); 60%-70%: said 64%, got 75% (n 126)
- Shots on target 1+: 50%-60%: said 55%, got 57% (n 2629); 60%-70%: said 64%, got 69% (n 1165); 70%-80%: said 73%, got 79% (n 197)
- Fouls 1+: 50%-60%: said 56%, got 53% (n 7665); 60%-70%: said 65%, got 64% (n 13338); 70%-80%: said 73%, got 74% (n 5416); 80%-90%: said 81%, got 84% (n 119)
- Fouls 2+: 50%-60%: said 52%, got 57% (n 75)
- Fouled 1+: 50%-60%: said 55%, got 53% (n 6520); 60%-70%: said 65%, got 63% (n 7770); 70%-80%: said 74%, got 75% (n 5503); 80%-90%: said 83%, got 84% (n 1509)
- Fouled 2+: 50%-60%: said 54%, got 58% (n 1248); 60%-70%: said 64%, got 69% (n 293)
- Tackles 1+: 50%-60%: said 56%, got 53% (n 3207); 60%-70%: said 66%, got 64% (n 6938); 70%-80%: said 75%, got 75% (n 11285); 80%-90%: said 83%, got 84% (n 5656)
- Tackles 2+: 50%-60%: said 54%, got 54% (n 5140); 60%-70%: said 64%, got 67% (n 1334); 70%-80%: said 73%, got 75% (n 135)
- Tackles 3+: 50%-60%: said 53%, got 54% (n 83)
