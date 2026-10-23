# Leg watch: split parlays from now on, and the learner's calibration

Two jobs, written 23 October 2026 on the `leg-watch` branch.

1. **A watch on split parlays,** run every time besttrack settles. PARLAY-CHECK.md (#16) found that parlays with legs on both teams looked optimistic, but it picked that subgroup after seeing the data. The watch tests the idea only on tickets nobody had seen when it was framed. Parlay pricing is not changed.
2. **A check of `learner.py`.** acca-correlation (#11) found that published legs land about 5% more often than they say. Is learner.py leaving that on the table? The check covers best_bets.json and the cache, by sport and leg kind, fitted on earlier nights and scored on later ones. **It is not, and learner.py is unchanged.**

## 1. The split-parlay watch

`parlay_watch.py`; `besttrack.py settle` calls it after every settle and writes `parlay_watch.json`. `python parlay_watch.py` prints the same summary.

These rules were fixed before any of the tickets settled:

- **Which tickets count.** Distinct published parlays (`Pick: parlay` in best_bets.json) first recorded on or after **24 October 2026 (UTC)**, settled win or lose. A ticket first seen before that date stays out, even if it is snapshotted again later. A ticket with a void leg is left out and counted, because its stated price includes the leg that voided (besttrack settles it on the rest).
- **Split or one side.** Split means the legs are on both teams; one side means they are all on one.
- **Said.** One over the ticket's published fair price.
- **The alternative.** The product of the legs' own record rates (hits / total). This is the price PARLAY-CHECK.md's exploratory fit pointed to.
- **The decision.** It is taken once, when 300 split tickets have settled. That is the sample PARLAY-CHECK.md estimated for an effect of its size to clear zero. The hypothesis holds only if two things are both true:
  - the 95% interval on split landed / said lies wholly below 1;
  - pricing split tickets off the multiplied legs lowers their log loss, with a 95% interval wholly below zero.

  Otherwise parlay pricing stays as it is. Intervals resample whole nights. Until 300 split tickets have settled, the watch reports and decides nothing.

Today it holds nothing: 0 of 300, all 146 published parlays having been recorded before 24 October. As a check that it counts what PARLAY-CHECK.md counted, I pointed it at the whole record with the start date removed. It gives split 10 of 42 (said 31.0%) and one side 17 of 44 (said 30.2%), the figures in PARLAY-CHECK.md, with 47 tickets left out for a void leg and 13 still open.

At the rate parlays are published now (about 146 entries in four weeks, 86 settled cleanly, half of them split), 300 split tickets is several months away. That is the price of testing the idea honestly.

The watch never touches the settle itself: a fault in it is printed and skipped.

## 2. Is learner.py leaving the 5% on the table?

`leg_calib.py` replays the correction night by night. For every night from 9 October, each method is fitted on the legs settled before that night and scores that night's legs. The methods are:

- **identity:** the chances as published, which is what learner.py learns from (`chance_base`, or one over fair).
- **learner, live:** `learner.fit`, switched on only when `learner.check` passes on the legs before that night, exactly as `learner.model()` runs it.
- **learner, on:** the same fit with no gate.
- **shift:** one log-odds shift per sport and leg kind, with the same 100-leg prior and 10-day half-life.
- **shift + slope:** a and b per sport and leg kind, with no market terms.

**The rule, fixed before the run.** A method replaces learner.py's fit only if, on the scored nights, it lowers log loss against "learner, live" with a 95% interval (whole nights resampled) wholly below zero, and does not raise log loss in any sport and kind with 100 or more scored legs.

### What it found

**On best_bets.json** (2,291 legs over 14 nights, 9 to 22 October):

- **The under-statement is there.** Overall the legs said 68.7% and landed 71.7%: 1.04 (1.00 to 1.08). Football team legs were 1.06 (1.01 to 1.10) and football player legs 1.05 (0.94 to 1.13), the figures acca-correlation saw.
- **When the learner is on, it closes the gap.** "learner, live" says 71.5% where 71.7% landed. Football team legs come out at 74.6% for 73.6%, and darts at 64.6% for 66.3%.
- **Correcting the level is worth very little in log loss.** "learner, on" beats "learner, live" by 0.0009 (−0.0024 to +0.0000), and the two simple shifts by 0.0008 and 0.0006, with intervals across zero. No method passes the rule. A shift of a few points on legs priced 60% to 80% moves log loss by about a thousandth, which is less than the night-to-night noise in 14 nights.
- **The gate is the one live-relevant detail.** It was on for 12 of the 14 nights (1,929 of the 2,291 legs) and off on 19 and 21 October. The committed `learned.json` (22 October) has it off: corrected 0.6079 against 0.6030 on its newest fifth. So the page shows the uncorrected chance today. On this evidence that costs under 0.001 in log loss, and switching the gate off permanently (identity) loses to "learner, live" in football team legs. Neither direction passes the rule.

**On the cache** (170,581 walk-forward legs over 192 nights, April to October 2026, refitted monthly on the previous 90 days):

These are acca-correlation's record-only legs, a copy of the page rather than its prices, so they test the method and not the live numbers.

- **Here the copy is badly calibrated** (football team legs 1.11, football player legs 0.97, darts 0.91, baseball 0.89).
- **learner.py's fit fixes most of it.** It is better than identity by 0.0060 (0.0054 to 0.0065), and better in every sport and kind.
- **Its gate stayed on every month.**
- **The simpler shifts do worse than the full fit** (+0.0046 and +0.0009 against it, intervals clear of zero). The market terms earn their place.

**Verdict.** learner.py is the right tool, and when its gate is on it already takes the 5% off. The record cannot tell it from leaving the chances alone, and nothing simpler does better. learner.py is not changed.

Two cautions:

- **Tiny gains can still matter.** The published replay is 14 nights. A real gain of 0.001 in log loss would need a few months of settled legs to show.
- **The gate check is small.** learner.check scores only the newest fifth of the record (about 450 legs), so whether the gate is on can change from one publish to the next on noise. A longer test window would make it steadier. That is a design change I have not made, because nothing here shows it would help.

## Files

- `parlay_watch.py`: the watch (part 1), reading best_bets.json and writing parlay_watch.json.
- `besttrack.py`: `settle` calls the watch after saving. It is wrapped, so a fault in the watch never costs the settle.
- `leg_calib.py`: the replay (part 2). `--dump ACCA_DIR CACHE` builds the cache legs with acca_corr.py from the acca-correlation branch.
- `tests/test_parlay_watch.py` (8 tests) and `tests/test_leg_calib.py` (9 tests), synthetic data only.

Neither writes learned.json. The test suite keeps learned.json untouched through `tests/conftest.py` and `tests/test_tracked_files.py`.

Reproducing part 2:

    python -B leg_calib.py
    python -B leg_calib.py --cache-legs legs.json --dump ACCA_CHECKOUT CACHE   # about 90 seconds; the cache unpacked from cache_backtest.tar.zst

## Every table

The output of the second command.

Generated 2026-10-23 20:52 UTC by `leg_calib.py`. Intervals resample whole nights, 2000 draws, seed 20261024.

### Published legs (best_bets.json), nights from 2026-10-09

2,291 legs over 14 nights, 2026-10-09 to 2026-10-22. The live gate (learner.check on the legs before each night) was on for 1929 of them.

| sport and kind | legs | nights | said | landed | landed / said (95% by night) | log loss identity | log loss learner, live | log loss learner, on | log loss shift | log loss shift + slope |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | 2,291 | 14 | 0.687 | 0.717 | 1.04 (1.00 to 1.08) | 0.5906 | 0.5906 | 0.5897 | 0.5898 | 0.5900 |
| football|team | 1,183 | 13 | 0.696 | 0.736 | 1.06 (1.01 to 1.10) | 0.5700 | 0.5674 | 0.5664 | 0.5673 | 0.5672 |
| football|player | 401 | 13 | 0.702 | 0.738 | 1.05 (0.94 to 1.13) | 0.5822 | 0.5827 | 0.5803 | 0.5813 | 0.5817 |
| darts|team | 190 | 6 | 0.620 | 0.663 | 1.07 (0.97 to 1.22) | 0.6401 | 0.6451 | 0.6451 | 0.6431 | 0.6431 |
| american-football|player | 171 | 8 | 0.679 | 0.690 | 1.02 (0.95 to 1.13) | 0.6293 | 0.6296 | 0.6295 | 0.6302 | 0.6306 |
| basketball|player | 156 | 3 | 0.704 | 0.699 | 0.99 (0.94 to 1.38) | 0.6104 | 0.6115 | 0.6115 | 0.6111 | 0.6113 |
| baseball|player | 88 | 6 | 0.674 | 0.670 | 1.00 (0.76 to 1.17) | 0.6309 | 0.6420 | 0.6420 | 0.6362 | 0.6389 |
| american-football|team | 60 | 6 | 0.657 | 0.583 | 0.89 (0.32 to 1.23) | 0.6683 | 0.6809 | 0.6800 | 0.6736 | 0.6770 |
| basketball|team | 29 | 3 | 0.658 | 0.759 | 1.15 (0.79 to 1.37) | 0.5229 | 0.5229 | 0.5229 | 0.5229 | 0.5229 |
| baseball|team | 13 | 5 | 0.683 | 0.538 | 0.79 (0.29 to 1.30) | 0.7819 | 0.7819 | 0.7819 | 0.7819 | 0.7819 |

Against "learner, live", log loss difference with a 95% interval resampling whole nights (negative is better):

| sport and kind | legs | identity | learner, on | shift | shift + slope |
|---|---:|---:|---:|---:|---:|
| all | 2,291 | -0.0000 (-0.0053 to +0.0057) | -0.0009 (-0.0024 to +0.0000) | -0.0008 (-0.0028 to +0.0015) | -0.0006 (-0.0023 to +0.0011) |
| football|team | 1,183 | +0.0026 (-0.0070 to +0.0119) | -0.0010 (-0.0034 to +0.0000) | -0.0000 (-0.0039 to +0.0039) | -0.0002 (-0.0029 to +0.0023) |
| football|player | 401 | -0.0005 (-0.0071 to +0.0032) | -0.0024 (-0.0055 to +0.0004) | -0.0013 (-0.0051 to +0.0029) | -0.0010 (-0.0048 to +0.0034) |
| darts|team | 190 | -0.0050 (-0.0179 to +0.0039) | +0.0000 (+0.0000 to +0.0000) | -0.0020 (-0.0079 to +0.0019) | -0.0020 (-0.0085 to +0.0020) |
| american-football|player | 171 | -0.0004 (-0.0080 to +0.0089) | -0.0001 (-0.0005 to +0.0000) | +0.0006 (-0.0041 to +0.0044) | +0.0010 (-0.0038 to +0.0037) |
| basketball|player | 156 | -0.0011 (-0.0026 to +0.0000) | +0.0000 (+0.0000 to +0.0000) | -0.0004 (-0.0009 to +0.0000) | -0.0002 (-0.0006 to +0.0000) |
| baseball|player | 88 | -0.0111 (-0.0367 to +0.0157) | +0.0000 (+0.0000 to +0.0000) | -0.0058 (-0.0184 to +0.0073) | -0.0031 (-0.0097 to +0.0036) |
| american-football|team | 60 | -0.0126 (-0.0378 to +0.0120) | -0.0009 (-0.0069 to +0.0000) | -0.0073 (-0.0236 to +0.0018) | -0.0039 (-0.0113 to +0.0029) |

Corrected chance against landed, per method:

| sport and kind | identity | learner, live | learner, on | shift | shift + slope | landed |
|---|---:|---:|---:|---:|---:|---:|
| all | 0.687 | 0.715 | 0.719 | 0.713 | 0.717 | 0.717 |
| football|team | 0.696 | 0.746 | 0.751 | 0.740 | 0.749 | 0.736 |
| football|player | 0.702 | 0.694 | 0.700 | 0.699 | 0.697 | 0.738 |
| darts|team | 0.620 | 0.646 | 0.646 | 0.640 | 0.639 | 0.663 |
| american-football|player | 0.679 | 0.695 | 0.696 | 0.694 | 0.694 | 0.690 |
| basketball|player | 0.704 | 0.709 | 0.709 | 0.707 | 0.708 | 0.699 |
| baseball|player | 0.674 | 0.648 | 0.648 | 0.660 | 0.654 | 0.670 |
| american-football|team | 0.657 | 0.672 | 0.671 | 0.666 | 0.670 | 0.583 |

The fixed rule (beats "learner, live" overall with the interval below zero, and is not worse in any sport and kind with 100+ legs):

- identity: does not hold (overall -0.0000 (-0.0053 to +0.0057); worse in football|team)
- learner, on: does not hold (overall -0.0009 (-0.0024 to +0.0000))
- shift: does not hold (overall -0.0008 (-0.0028 to +0.0015); worse in american-football|player)
- shift + slope: does not hold (overall -0.0006 (-0.0023 to +0.0011); worse in american-football|player)

### Cache walk-forward legs, nights from 2026-04-01

170,581 legs over 192 nights, 2026-04-01 to 2026-10-19. The live gate (learner.check on the legs before each night) was on for 170581 of them.

| sport and kind | legs | nights | said | landed | landed / said (95% by night) | log loss identity | log loss learner, live | log loss learner, on | log loss shift | log loss shift + slope |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | 170,581 | 192 | 0.587 | 0.579 | 0.99 (0.98 to 0.99) | 0.6754 | 0.6694 | 0.6694 | 0.6740 | 0.6703 |
| football|player | 145,085 | 183 | 0.592 | 0.574 | 0.97 (0.96 to 0.97) | 0.6762 | 0.6703 | 0.6703 | 0.6756 | 0.6713 |
| football|team | 21,794 | 182 | 0.548 | 0.611 | 1.11 (1.10 to 1.13) | 0.6685 | 0.6615 | 0.6615 | 0.6620 | 0.6616 |
| darts|team | 2,085 | 63 | 0.608 | 0.556 | 0.91 (0.87 to 0.95) | 0.6943 | 0.6913 | 0.6913 | 0.6928 | 0.6928 |
| american-football|team | 1,109 | 19 | 0.597 | 0.601 | 1.01 (0.95 to 1.07) | 0.6511 | 0.6507 | 0.6507 | 0.6509 | 0.6509 |
| baseball|team | 508 | 34 | 0.617 | 0.551 | 0.89 (0.81 to 0.98) | 0.7049 | 0.7012 | 0.7012 | 0.7028 | 0.7023 |

Against "learner, live", log loss difference with a 95% interval resampling whole nights (negative is better):

| sport and kind | legs | identity | learner, on | shift | shift + slope |
|---|---:|---:|---:|---:|---:|
| all | 170,581 | +0.0060 (+0.0054 to +0.0065) | +0.0000 (+0.0000 to +0.0000) | +0.0046 (+0.0042 to +0.0050) | +0.0009 (+0.0007 to +0.0011) |
| football|player | 145,085 | +0.0059 (+0.0053 to +0.0066) | +0.0000 (+0.0000 to +0.0000) | +0.0053 (+0.0048 to +0.0058) | +0.0010 (+0.0008 to +0.0013) |
| football|team | 21,794 | +0.0070 (+0.0057 to +0.0082) | +0.0000 (+0.0000 to +0.0000) | +0.0005 (+0.0002 to +0.0008) | +0.0001 (-0.0002 to +0.0003) |
| darts|team | 2,085 | +0.0030 (-0.0000 to +0.0059) | +0.0000 (+0.0000 to +0.0000) | +0.0016 (-0.0005 to +0.0036) | +0.0015 (-0.0005 to +0.0035) |
| american-football|team | 1,109 | +0.0004 (-0.0003 to +0.0014) | +0.0000 (+0.0000 to +0.0000) | +0.0002 (-0.0001 to +0.0004) | +0.0002 (-0.0001 to +0.0005) |
| baseball|team | 508 | +0.0037 (-0.0015 to +0.0101) | +0.0000 (+0.0000 to +0.0000) | +0.0017 (-0.0006 to +0.0045) | +0.0011 (-0.0008 to +0.0033) |

Corrected chance against landed, per method:

| sport and kind | identity | learner, live | learner, on | shift | shift + slope | landed |
|---|---:|---:|---:|---:|---:|---:|
| all | 0.587 | 0.575 | 0.575 | 0.576 | 0.575 | 0.579 |
| football|player | 0.592 | 0.572 | 0.572 | 0.574 | 0.572 | 0.574 |
| football|team | 0.548 | 0.592 | 0.592 | 0.590 | 0.591 | 0.611 |
| darts|team | 0.608 | 0.586 | 0.586 | 0.595 | 0.593 | 0.556 |
| american-football|team | 0.597 | 0.601 | 0.601 | 0.601 | 0.600 | 0.601 |
| baseball|team | 0.617 | 0.609 | 0.609 | 0.612 | 0.612 | 0.551 |

The fixed rule (beats "learner, live" overall with the interval below zero, and is not worse in any sport and kind with 100+ legs):

- identity: does not hold (overall +0.0060 (+0.0054 to +0.0065); worse in american-football|team, baseball|team, darts|team, football|player, football|team)
- learner, on: does not hold (overall +0.0000 (+0.0000 to +0.0000))
- shift: does not hold (overall +0.0046 (+0.0042 to +0.0050); worse in american-football|team, baseball|team, darts|team, football|player, football|team)
- shift + slope: does not hold (overall +0.0009 (+0.0007 to +0.0011); worse in american-football|team, baseball|team, darts|team, football|player, football|team)

