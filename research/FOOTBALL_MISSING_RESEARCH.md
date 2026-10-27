# Football: does "usual starters missing" improve the models? (26 Oct 2026)

**Verdict: no, not worth adding.** Kept out of fmodel and teammodel.

Same test as the NBA rule: the feature was added to the existing models, each model trained
on games before 1 Apr 2026 (choices made on Apr-Jun), scored on everything from 1 Jul 2026
it never saw, then on Paddy Power's real settled lines (20-26 Oct).

Feature (per team per match, strictly from earlier games): regulars = started 6+ of the team's
last 10 and played for it in the last 45 days. Missing = regulars not starting today, with their
usual attacking and defensive output (shots + key passes + 3 x xG per 90; tackles + fouls +
interceptions per 90), the same for regulars missing in his own line, the opponent's missing
regulars, and the number of rotated-in starters. 94% of player rows and 77% of team rows have it.

## Player model (fmodel), 15 lines, 27,700 unseen player-games each, 2 seeds

Average change in log loss: +0.00005 on validation, +0.00006 out of sample (positive = better):
nothing. Improved on both in 6 of 15 lines, all by 0.0004 or less. Biggest: assists 1+ (+0.0003).

On Paddy's real lines (11,196 settled lines, 96 games): log loss 0.4444 both. Value bets got worse
with it: 0%+ edge +0.3% -> -8.7%; 5%+ -1.2% -> -13.9%; 10%+ -6.0% -> -10.5%.

Why it adds nothing: the player model is scored from the confirmed line-up, and already knows who
IS starting beside him in his line (partners) and the team's style. In basketball the usage of a
missing star has to go to five other players; in football the replacement starter takes the role.

## Team model (teammodel), 10 stats, ~2,500 unseen team-games each, 3 seeds

| stat | change on validation | change out of sample |
|---|---|---|
| Big chances | +0.0014 | +0.0014 |
| Shots on target | +0.0007 | +0.0010 |
| Offsides | +0.0012 | +0.0007 |
| Total shots | +0.0007 | +0.0005 |
| Corner kicks | +0.0001 | -0.0001 |
| Goalkeeper saves | -0.0003 | +0.0010 |
| Yellow cards | +0.0003 | -0.0003 |
| Fouls | -0.0004 | -0.0003 |
| Clearances | -0.0013 | -0.0021 |
| Total tackles | -0.0001 | -0.0024 |

Four stats improve on both, by 0.05 to 0.15% of log loss: far too small to move a bet. Three get
worse. Not adopted. Revisit only if the team model is rebuilt for another reason.

Scripts (run in a scratch box on the cache, as fmodel/training): features_miss.py (fmodel features
plus the missing block), team_miss.py, team_exp.py, player_exp.py, real_test.py.
