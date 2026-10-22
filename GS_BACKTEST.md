# Game state walk-forward backtest

Generated 2026-10-21T19:02:16+00:00. 7177 matches, 9348 team rows, 67499 player rows. Each model fitted on everything before a test window, scored on the last 40% of dates in four windows.

Possession: predicted from both sides' usual share, error 7.3 pts; a side's usual share alone, 8.5 pts.

Log loss of the over/under at each side's own average (lower is better). M0 own average, M1 + opponent, M2 + game state, GS the page's unfitted formula.


## Team stats

| Stat | n | M0 | M1 +opp | M2 +gs | GS page | game state coef | used |
|---|---|---|---|---|---|---|---|
| Total shots | 3742 | 0.6908 | 0.6325 | 0.6325 | 0.6698 | +0.27 | no |
| Shots on target | 3774 | 0.6889 | 0.6547 | 0.6548 | 0.6805 | +0.33 | no |
| Corner kicks | 3774 | 0.6842 | 0.6390 | 0.6375 | 0.6684 | +0.49 | yes |
| Big chances | 3636 | 0.6800 | 0.6474 | 0.6481 | 0.6759 | +0.28 | no |
| Fouls | 3762 | 0.6902 | 0.6609 | 0.6611 | 0.7146 | +0.02 | no |
| Total tackles | 3734 | 0.6950 | 0.6618 | 0.6607 | 0.7052 | +0.12 | yes |
| Yellow cards | 3624 | 0.6875 | 0.6560 | 0.6562 | 0.6878 | +0.17 | no |
| Clearances | 3734 | 0.6862 | 0.6499 | 0.6489 | 0.6973 | -0.24 | yes |
| Goalkeeper saves | 3734 | 0.6961 | 0.6494 | 0.6483 | 0.6838 | +0.47 | yes |

## Player stats

| Stat | n | M0 | M1 +opp | M2 +gs | GS page | game state coef | used |
|---|---|---|---|---|---|---|---|
| Shots | 26604 | 0.6732 | 0.6644 | 0.6633 | 0.6708 | +0.70 | yes |
| Shots on target | 22795 | 0.5725 | 0.5672 | 0.5667 | 0.5713 | +0.68 | yes |
| Fouls | 26965 | 0.6686 | 0.6502 | 0.6502 | 0.6720 | +0.09 | no |
| Fouled | 26793 | 0.6656 | 0.6540 | 0.6540 | 0.6682 | +0.18 | no |
| Tackles | 27038 | 0.6713 | 0.6566 | 0.6564 | 0.6733 | +0.14 | yes |

## Player calibration at 1+, 2+, 3+

Fitted on the first 60% of dates, scored on the rest (run 21 October). 'Said' is the model's average chance in the bucket, 'got' how often it landed. A full `gs_backtest.py test` run also writes this section.

- Shots 1+: 55% said, 51% got; 65/62; 75/75; 85/88
- Shots 2+: 55/61; 64/69; 74/80; 83/93 (cautious)
- Shots on target 1+: 55/57; 64/70; 73/78 (cautious)
- Fouls 1+: 56/53; 65/64; 73/74; 81/83
- Fouled 1+: 55/53; 65/63; 74/76; 83/84
- Tackles 1+: 56/53; 66/64; 75/75; 83/84
- Tackles 2+: 54/54; 63/66; 73/80 (cautious)
