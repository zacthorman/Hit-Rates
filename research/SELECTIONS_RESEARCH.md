# Best selections: how the filter was tested (26 Oct 2026)

The filter (selections.py): Paddy price 1.60 to 2.30; NBA/NFL model chance beats it by 3%+;
7+ of the last 10 and 3+ of the last 5 at that line; one per player, two per game, eight a
day per sport, most model edge first. Football excluded.

## 1. Paddy Power's real prices, 13 to 25 Oct (the number to trust)

`research/selections_bt.py` + `_sel_an.py` on settled pplog rows, first logged price, £1 a bet.

| Layer | NBA over | NBA under | NFL over | NFL under |
|---|---|---|---|---|
| every line | -24.9% (7613) | -3.0% (2041) | -11.5% (3402) | -8.7% (433) |
| model value 3%+ | -11.8% | +3.5% | -1.7% | +1.8% |
| + price 1.60-2.30 | +4.1% | +4.6% | +8.5% | +0.8% |
| + form 7/10, 3/5 | +6.4% | +12.0% | +18.4% | +0.1% |
| + one per player | +4.6% (75) | +9.5% (114) | +18.5% (11) | +8.1% (27) |

Daily list (selections.pick on first prices): **39 bets, 7 days, 62% won, +21.8%**, resampled
over days 90% range +6% to +49%. Each layer helped in every column but one. Football player
lines lost at every layer (-25% to -62%) and are left out.

## 2. Long back-test, games the models never saw (direction only, not money)

`research/selbt.py` refits the NBA/NFL models on games before the validation end (NFL
1 Dec 2025, NBA 1 Apr 2026) and scores everything after: NFL 30 Nov 2025 to 25 Oct 2026
(199 games), NBA 31 Mar to 25 Oct 2026 (235 games). There are no historical bookmaker lines,
so `selbt2.py` fits a stand-in Paddy line from October's real main lines (weighted average,
last 3/5/10/20 means, last-10 median; 25 to 50% closer to Paddy's line than the plain median),
priced at Paddy's average main-line prices (over 1.91, under 1.84).

Same ordering as on real prices: every line -6.5%; model value 3%+ NFL +12%, NBA +24%;
+ form NFL +13%, NBA +26%; daily list NFL +28% (168 bets), NBA +64% (318 bets), profitable
in every month. **These returns are not believable as money**: on October, where both exist,
the stand-in said NBA +58% against roughly +5 to +10% on Paddy's real prices. The stand-in
line is softer than Paddy's, and ranking by edge picks exactly the lines it got most wrong.
What it does show is that the model and the form filter both add, on many months of unseen
games, and that form without the model does little in the NFL (-1%).

Judge the live record (selections/log.jsonl, `python selections.py report`) over weeks.
