# Looking for profit in the Paddy Power log, 23 Oct 2026

Data: every settled Paddy Power player line in pplog. NBA 3,848 lines from 13 games (20 to 22 Oct),
NFL 720 lines from 2 games, football 4,917 lines from 34 games (20 to 22 Oct). Lines in one game
move together, so the sample is the number of games, not lines. This is far too little to prove
anything; it is enough to choose what to test.

## What was found

1. **pplog had never scored the NBA or NFL models.** It logged the old last-10 chance. Fixed for new
   rows (pplog.py `_usmodel_p`); `research/uscheck.py` rebuilds the model's pre-game chance for the
   old ones.
2. **NBA model against Paddy (13 games).** Log loss: model 0.533, page blend 0.536, old chance 0.594,
   Paddy implied 0.522. Calibrated overall (said 38.3%, landed 38.5%). Betting its value flags:
   -10% at 0%+ edge, -17% at 10%+. A logistic blend of model and margin-free market, fitted on the
   first 7 games, gave the model a negative weight and lost on the last 6. **The model does not beat
   the market on its own or added to it, on this sample.**
3. **Paddy's NBA main-line overs look priced short.** On the 841 lines where both sides are offered
   (average overround 7.7%), the over landed 43.8% against a margin-free 49%. Overs at 1.60 to 2.20
   lost 9.5% on the first 7 games and 26% on the last 6; unders at the same prices -6.6% then
   +15.9%. As fixed rules over all 13 games: unders +3.3% (90% range by game -9% to +16%), overs
   -18.7% (-31% to -7%). Plausible causes: books shading overs because the public backs them, and
   early-season minutes. Either can fade.
4. **Model agreement on top of the unders** was +8.4% against +3.3% (in sample), but by size of edge
   there is no pattern (5 to 15%: +14%; 15 to 50%: +2%; under -5%: about -2%). Tracked as its own
   rule; not to be trusted until live.
5. **NFL: 2 games.** Nothing can be read. The NFL model rarely agrees with receiving overs (4 bets).
6. **Football blind lines lose 47%**, but "1+ fouls" at prices implying 80% landed 48%, which no
   book misses by. The likely cause is settling substitutes who barely played as losers rather than
   voids. The football value box already takes starters only; worth fixing in pplog settle before
   any football rule is judged.
7. **Closing line value**: on the NBA unders the price moved in only about 5% of bets between first
   and last sighting, so CLV says little yet. sharp.py's Betfair check has 2 rows stamped so far.

## Rules frozen for the trial (ruletrack.py)

| Rule | Why |
|---|---|
| NBA under, main line, 1.60 to 2.20 | finding 3 |
| the same, model agrees by 5%+ | finding 4 |
| NFL receiving over, 2.20 or shorter, model agrees by 5%+ | the log's NFL receiving overs, small |
| Paddy 2%+ over Betfair's fair price, 10.0 or shorter | sharp.py; the standard soft-v-sharp edge |
| Control: NBA over, main line, 1.60 to 2.20 | should lose; if it stops, rule 1 is not what it looks like |

Judge each on its Live rows in RULES_TRACK.md after about 40 games, by the 90% range. A rule whose
range sits above zero with CLV positive is an edge; anything else is not yet.
