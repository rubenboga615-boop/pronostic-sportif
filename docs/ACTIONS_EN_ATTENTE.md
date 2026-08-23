# Actions en attente

> File d'actions à traiter, par ordre de priorité suggéré.

## Priorité haute
1. **Valider le mapping des features** : trancher la granularité match/équipe
   (`rest_days`, `odds_movement`) et les règles de dérivation
   (`elo_rating`, `goal_difference`, `opponent_strength`).
2. **Committer les modifications non commitées** (après validation) :
   `features/odds_movement.py`, `features/mapping.py`, `tests/test_features_mapping.py`.

## Priorité moyenne
3. **Normaliser le code marché** `"1n2"` vs `"1N2"` (import + `market_derivation.py`
   + `poisson.py` + tests). Choisir `"1N2"` comme référence (aligné sur la base).
4. **Charger les sources manquantes** pour les features : xG (Understat) et
   disponibilités/blessures — sinon `xg_avg_5`, `xga_avg_5`, `npxg_avg_5`,
   `injury_impact` resteront `None`.
5. **Décider des index features/backtest** (identifiés par `EXPLAIN QUERY PLAN`):
   `idx_matches_home_date`, `idx_matches_away_date`, `idx_matches_comp_date`.

## Priorité basse
6. **Trancher la contrainte UNIQUE** sur `provider_match_id` (rebuild + FK).
7. **Persister les features** dans la table `features` une fois le mapping validé.

## Rappels sécurité
- Sauvegarde vérifiée avant toute modification de la base.
- `pytest -q` avant/après chaque changement.
- Pas de Phase 2 sans validation (`knowledge.md`).
