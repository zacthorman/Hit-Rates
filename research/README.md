# Research

- `open_eval.py`: the style (open game) model. Trains `teammodel/open_goals.json.gz`.
- `flank.py`, `flank_eval.py`: flank and involvement features against the player model (not adopted).
- `odds/`: historical closing odds for testing the result model against the market. From your Mac's terminal:

      cd ~/Vaults/"Cowork Base/03 Code Projects/Football stats"
      for L in E0 E1 SP1 I1 D1 F1; do for S in 2526 2627; do curl -sfo research/odds/${L}_${S}.csv https://www.football-data.co.uk/mmz4281/$S/$L.csv; done; done

  (Premier League, Championship, LaLiga, Serie A, Bundesliga, Ligue 1; seasons 2025-26 and 2026-27.)
