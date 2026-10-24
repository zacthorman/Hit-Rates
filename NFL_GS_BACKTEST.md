# NFL game-script backtest (22 Oct 2026)

Question: does knowing the game script before kick-off (expected margin, plays per game, how a
team's pass rate moves when it is ahead or behind, short weeks, byes) improve the NFL player
prop model?

Setup
- Features from `nflgame.py`, built strictly from earlier games; live and backtest share the code
  (parity check passed on the last game).
- Same model as production: LightGBM Poisson on the player's own weighted average, with the
  current 144 features from `usmodel/nfl_meta.json`, and then the same plus the script features.
- Split: train before 1 Sep 2025, validation Sep to Nov 2025, out of sample Dec 2025 onwards
  (186 games).
- Score: log loss at three lines per player (median and about 25 to 30% either side).
- Significance: bootstrap by game (2,000 resamples), then Holm across the 12 markets.
- Rule: adopt only if validation improves and the Holm-adjusted p is under 0.05.

## Result: no market qualifies. No model change made.

Full script set (18 features):

| Market | OOS rows | Games | Val gain | OOS change | 95% CI (log loss) | p | Holm p |
|---|---|---|---|---|---|---|---|
| pass_td | 369 | 184 | +0.0017 | +1.11% | -0.0006 to +0.0147 | 0.039 | 0.47 |
| tackles | 3649 | 186 | +0.0023 | +0.26% | -0.0002 to +0.0034 | 0.045 | 0.50 |
| rec_yds | 1611 | 186 | +0.0022 | +0.28% | -0.0011 to +0.0045 | 0.101 | 1.00 |
| rush_yds | 796 | 186 | -0.0012 | +0.25% | -0.0031 to +0.0064 | 0.272 | 1.00 |
| td | 1731 | 186 | -0.0008 | +0.11% | -0.0015 to +0.0029 | 0.294 | 1.00 |
| rush_att | 668 | 186 | +0.0029 | +0.19% | -0.0044 to +0.0067 | 0.349 | 1.00 |
| pass_rush_yds | 374 | 185 | +0.0052 | +0.36% | -0.0129 to +0.0160 | 0.387 | 1.00 |
| pass_att | 379 | 185 | +0.0073 | +0.07% | -0.0102 to +0.0112 | 0.469 | 1.00 |
| rush_rec_yds | 1506 | 186 | +0.0035 | -0.02% | -0.0033 to +0.0030 | 0.521 | 1.00 |
| pass_cmp | 377 | 185 | +0.0034 | -0.22% | -0.0134 to +0.0104 | 0.574 | 1.00 |
| rec | 1883 | 186 | -0.0008 | -0.07% | -0.0021 to +0.0013 | 0.689 | 1.00 |
| pass_yds | 372 | 185 | +0.0114 | -1.36% | -0.0232 to +0.0062 | 0.867 | 1.00 |

Compact set (expected margin, expected plays, script push, short week, bye):

| Market | OOS rows | Games | Val gain | OOS change | 95% CI (log loss) | p | Holm p |
|---|---|---|---|---|---|---|---|
| pass_td | 369 | 184 | +0.0013 | +1.15% | -0.0012 to +0.0165 | 0.045 | 0.55 |
| tackles | 3649 | 186 | +0.0013 | +0.13% | -0.0008 to +0.0023 | 0.173 | 1.00 |
| pass_rush_yds | 374 | 185 | +0.0110 | +0.97% | -0.0069 to +0.0184 | 0.191 | 1.00 |
| rec_yds | 1611 | 186 | +0.0002 | +0.14% | -0.0013 to +0.0030 | 0.223 | 1.00 |
| rush_att | 668 | 186 | +0.0010 | +0.36% | -0.0029 to +0.0073 | 0.230 | 1.00 |
| rush_rec_yds | 1506 | 186 | +0.0016 | +0.08% | -0.0018 to +0.0030 | 0.348 | 1.00 |
| rush_yds | 796 | 186 | +0.0002 | +0.06% | -0.0030 to +0.0037 | 0.405 | 1.00 |
| td | 1731 | 186 | -0.0011 | +0.03% | -0.0016 to +0.0020 | 0.416 | 1.00 |
| pass_att | 379 | 185 | +0.0096 | -0.21% | -0.0093 to +0.0075 | 0.593 | 1.00 |
| pass_cmp | 377 | 185 | +0.0063 | -1.02% | -0.0150 to +0.0037 | 0.865 | 1.00 |
| pass_yds | 372 | 185 | +0.0085 | -1.53% | -0.0216 to +0.0024 | 0.929 | 1.00 |
| rec | 1883 | 186 | +0.0003 | -0.19% | -0.0023 to -0.0001 | 0.983 | 1.00 |

Reading it
- Poisson deviance improved slightly in 10 of 12 markets, so there is some signal.
- That signal did not survive at the lines. The best markets were:
  - pass TDs, about 1.1% better, with a raw p of 0.04 (0.47 after Holm);
  - tackles, about 0.26% better, with a raw p of 0.05.
- Neither clears even an uncorrected 95% interval.
- Pass yards got worse out of sample.
- The current model already holds Elo and team and opponent style, which carry most of the
  script.
- Re-run after the 2026 season adds about 270 games:
  `python3 usmodel/training/nfl_gs_eval.py` (needs the features with `_s` from `nflgame.team_features`).
