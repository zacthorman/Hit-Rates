# NBA and NFL player models: results (21 October 2026)

Log loss of the chance of OVER at three lines per player-game (his last-10
median and 25-30% either side), on games the model never saw. Lower is better.
"site now" is model.price_player as the page priced it on 21 Oct (NBA with the
withdrawn basketball calibration removed); "site recalibrated" is the same
refitted on the training period, so a calibration fix is not counted as the
model's gain; "live (chosen)" is what the page uses: the model alone or blended
with the site, chosen inside validation.

## NFL (train 2020 to Aug 2025, validation Sep to Nov 2025, out of sample Dec 2025 to 20 Oct 2026)

| market | lines | site now | site recalibrated | new model | live (chosen) | coin |
|---|---|---|---|---|---|---|
| pass_yds | 1116 | 0.6060 | 0.5990 | 0.5846 | 0.5846 (model) | 0.6914 |
| pass_cmp | 1131 | 0.5536 | 0.5233 | 0.5381 | 0.5381 (model) | 0.6902 |
| pass_att | 1137 | 0.5486 | 0.5252 | 0.5290 | 0.5051 (blend) | 0.6929 |
| pass_td | 1107 | 0.6430 | 0.6347 | 0.6262 | 0.6262 (model) | 0.6828 |
| rush_yds | 2388 | 0.6473 | 0.6408 | 0.6369 | 0.6369 (model) | 0.6853 |
| rush_att | 2004 | 0.6037 | 0.5876 | 0.5612 | 0.5612 (model) | 0.6890 |
| rec_yds | 4833 | 0.6692 | 0.6645 | 0.6509 | 0.6509 (model) | 0.6873 |
| rec | 5649 | 0.6498 | 0.6395 | 0.6233 | 0.6233 (model) | 0.6843 |
| rush_rec_yds | 4518 | 0.6612 | 0.6570 | 0.6453 | 0.6453 (model) | 0.6888 |
| pass_rush_yds | 1122 | 0.5965 | 0.5882 | 0.5674 | 0.5674 (model) | 0.6927 |
| tackles | 10947 | 0.6340 | 0.6201 | 0.6063 | 0.6063 (model) | 0.6864 |
| td | 1731 | 0.6065 | 0.5830 | 0.5723 | 0.5723 (model) | 0.5964 |

## NBA (train Oct 2025 to Jan 2026, validation Feb to Mar 2026, out of sample Apr to Jun 2026 and opening week)

| market | lines | site now | site recalibrated | new model | live (chosen) | coin |
|---|---|---|---|---|---|---|
| points | 9795 | 0.6440 | 0.6376 | 0.5913 | 0.5941 (blend) | 0.6905 |
| rebounds | 9636 | 0.6447 | 0.6346 | 0.6002 | 0.6002 (model) | 0.6899 |
| assists | 7047 | 0.6570 | 0.6508 | 0.6080 | 0.6080 (model) | 0.6835 |
| threes | 7113 | 0.6545 | 0.6440 | 0.6299 | 0.6299 (model) | 0.6826 |
| steals | 5295 | 0.6242 | 0.5992 | 0.5918 | 0.5910 (blend) | 0.6524 |
| blocks | 1992 | 0.6138 | 0.5753 | 0.5731 | 0.5731 (model) | 0.6348 |
| turnovers | 7308 | 0.6395 | 0.6261 | 0.6086 | 0.6086 (model) | 0.6791 |
| pra | 9639 | 0.6178 | 0.6100 | 0.5575 | 0.5595 (blend) | 0.6917 |
| pr | 9945 | 0.6338 | 0.6275 | 0.5747 | 0.5779 (blend) | 0.6911 |
| pa | 9354 | 0.6303 | 0.6240 | 0.5742 | 0.5768 (blend) | 0.6910 |
| ra | 9807 | 0.6332 | 0.6236 | 0.5697 | 0.5697 (model) | 0.6900 |

## Paddy Power's real settled lines (pplog), train-only models

NFL, 49ers v Commanders (19 Oct 2026):
```
nfl: 320 settled Paddy lines matched (of 320)
  paddy    log loss 0.5043  said 46%  landed 45%
  p_site   log loss 0.5200  said 43%  landed 45%
  p_new    log loss 0.5284  said 36%  landed 45%
  p_blend  log loss 0.5039  said 38%  landed 45%
  value by p_site :  14 bets, won 79%, P/L +5.0u, ROI +36%
  value by p_blend:  21 bets, won 52%, P/L -0.9u, ROI -4%
```
NBA, Spurs v Thunder (20 Oct 2026, opening night, every record last season's):
```
nba: 561 settled Paddy lines matched (of 561)
  paddy    log loss 0.5550  said 45%  landed 39%
  p_site   log loss 0.5686  said 44%  landed 39%
  p_new    log loss 0.5737  said 37%  landed 39%
  p_blend  log loss 0.5729  said 37%  landed 39%
  value by p_site :  34 bets, won 41%, P/L -6.0u, ROI -18%
  value by p_blend:  70 bets, won 44%, P/L -13.5u, ROI -19%
```
One game each, 320 and 561 lines that move together: a check that the model is
in Paddy's league, not a measure of profit. pplog keeps settling every line;
rerun ppcheck_us.py after a few weeks before trusting the value flags.
