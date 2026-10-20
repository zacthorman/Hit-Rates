# How the player model was built (20 October 2026)

These are the backtest scripts behind `fmodel/` and `fmodel_live.py`, kept so
the model can be checked or retrained. They were run in a scratch Linux box
with LightGBM, pyarrow and scikit-learn installed; the paths inside point at
`/home/claude/bt` and need changing to run anywhere else. The Mac does not
need any of this to use the model.

Order of play:

1. `build.py`: parse the SofaScore cache (`cache/`) into matches, teams and
   players tables (6,788 finished matches, 286,053 player rows).
2. `features.py`: pre-kick-off features for every starter, strictly from
   earlier matches (form, team style, opponent style, league and Elo,
   positional concession, partners, the nearest opponents, head to head).
3. `baseline.py`: the site's own chance (model.price_player) replayed on the
   same rows, to compare against.
4. `evaluate.py ablate`: one LightGBM model per line, adding one group of
   features at a time. Train before 1 April 2026, validation April to June
   (early stopping and the choice of groups), out of sample from 1 July.
5. `evaluate.py auto`: the final fit with the groups chosen on validation.
6. `calib.py`: calibration check out of sample.
7. `export_models.py`: refit on train plus validation and dump the trees
   to JSON (compressed to `fmodel/*.json.gz`).
8. `sim_test.py`: feeds finished matches through `fmodel_live.py` as if
   they were upcoming and checks the features and chances match the
   backtest exactly.

Results: `results_auto.csv` (final) and `results_auto_before_fix.csv` (before
the team-style column bug was fixed). Log loss, lower is better: "site" is
the page's chance as it was, "site_fair" the same recalibrated on the training
period, "new" the model. An independent audit found no leakage.
