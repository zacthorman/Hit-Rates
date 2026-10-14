---
type: analysis
project: Code Projects
status: active
date: 2026-10-13
tags: [project/code-projects, type/analysis]
---

# Football stats: best bets calibration, 13 October 2026

`best_bets.json` scored as it stood on 13 October: every best bet the site published from 27 September to 12 October, 788 settled (voids and unsettled left out), across 189 fixtures. Read-only, nothing in the project changed. Script: `score_best_bets.py` alongside this note, output in `best_bets_calibration.csv`.

**The question it can answer:** when the site says a bet has a 70% chance, does it land 70% of the time? **The question it cannot answer:** whether any of it made money. The record holds the site's fair price but no bookmaker price, so profit is not computable.

## The answer

**The site's stated chances are honest on average, and that is about all they are.**

- Said 61.6%, landed 65.5%. The 95% interval on the gap (resampling whole fixtures, because legs in one match move together) runs from -0.8 to +8.2 points. If anything the site undersells itself.
- **The shrinkage works.** For singles the raw hit record said 77%, the site's shrunk figure said 67.7%, and 70.8% landed. Without the shrinkage the site would overclaim by 6 points. That fixes the LESSONS table's overconfident top band.
- **But the numbers barely tell good bets from ordinary ones.** On singles, the site's per-bet chance scores a Brier of 0.209 against 0.207 for simply saying 70.8% for every bet. Calibrated on average, almost no sorting power within a fortnight's sample.

## Where it is wrong

| Group | Bets | Site said | Landed | Gap, 95% interval |
|---|---|---|---|---|
| Team legs (singles) | 424 | 65.9% | 73.1% | **+2.8 to +11.4**, understated |
| Player legs (singles) | 193 | 71.7% | 65.8% | -15.8 to +3.6, probably overstated |
| Player and team "Shots" | 33 | 70.3% | 51.5% | the worst market |
| Baseball | 23 (2 fixtures) | 58.8% | 21.7% | too few fixtures to read |

Team markets (cards, corners, team shots on target, goals) are the one place where the gap clears zero. Player markets lean the other way. Twenty-odd stat types were compared, so expect one or two of the per-stat gaps to be luck; the team versus player split is the one that holds up.

## What to do with it

- **Break-even odds, from what actually landed:** 1.37 for a team single, 1.52 for a player single, 1.53 across everything. A bookmaker price below those loses money on this record, whatever the site says.
- **Log the bookmaker price with every best bet.** One field at snapshot time turns this from a calibration check into a profit check. It is a change to `besttrack.py`, so it is Zac's call, not done here.
- **Re-run in a month.** Sixteen days and 189 fixtures is enough to see the team versus player split, not enough to trust anything per stat.
