# Décisions

> Décisions techniques et de conception, avec leur justification. À compléter au fil de l'eau.

## Validées

### 1. `provider_match_id` déterministe (SHA-256)
- Identifiant `fd_{league}_{season}_{digest}` calculé sur la clé canonique
  `league_code|season_name|date_iso|home|away`.
- **Pourquoi** : stable entre processus/machines (pas de `hash()` salé).

### 2. Déduplication applicative par `provider + date + home + away`
- `_find_existing_match` s'appuie sur ces 4 colonnes.
- **Écart relevé** : `provider_match_id` est calculé mais **non utilisé** pour dédupliquer,
  et **non unique** en base. À trancher plus tard (contrainte UNIQUE ? index ?).

### 3. `PRAGMA foreign_keys=ON` via listener `connect`
- **Pourquoi** : SQLite ne l'active pas par défaut ; le listener garantit l'activation
  sur chaque connexion sans modifier les modèles.

### 4. Cinq index non uniques
- `idx_matches_dedup`, `idx_teams_lookup`, `idx_seasons_lookup`,
  `idx_odds_match_id`, `idx_tms_match_team`.
- **Pourquoi** : accélérer l'import (dédup/upsert) et les jointures. Uniques volontairement
  évités (pas de contrainte UNIQUE demandée).

### 5. Valeurs absentes (xG/blessures) → `None`/`NULL`
- **Pourquoi** : ne jamais substituer une valeur valide (ex. 0.0) à une donnée
  indisponible. La table `features` accepte les `NULL`.

## À décider

### A. Granularité match vs équipe
- `rest_days`, `odds_movement`, `rest_days_difference` : la table `features` est par
  `(match_id, team_id)`, mais certaines grandeurs sont par match.
- Options : dupliquer sur les deux lignes, ou déplacer vers une table match-level.

### B. Règles de dérivation manquantes
- `elo_rating` (à partir des Elo pré-match), `goal_difference` (standings),
  `opponent_strength` (équipes comparables) : il faut une règle explicite
  pour transformer les sorties des modules en valeur unique de colonne.

### C. Normalisation du code marché `"1n2"` vs `"1N2"`
- L'import et la base utilisent `"1N2"`, mais `models/market_derivation.py` et
  `models/poisson.py` produisent `"1n2"`, et `tests/test_models.py` asserte `"1n2"`.
- Décision nécessaire : harmoniser partout sur `"1N2"` (ou l'inverse).

### D. Contrainte UNIQUE sur `provider_match_id`
- Données déjà uniques (0 doublon). Implique un rebuild de table + coordination
  avec `PRAGMA foreign_keys=ON`. Non tranché.
