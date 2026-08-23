# Journal — 2026-08-23 — Préparation du mapping des features

## Contexte
Après le test en mémoire du match 68 (validé), préparation du code pour la future
persistance des features, sans écrire en base.

## Résumé technique

### Correctif `features/odds_movement.py`
- Défaut du paramètre `market` : `"1n2"` → `"1N2"` (aligné sur la base et l'import).
- Vérifié sur le match 68 : mouvement ≈ −2,18 % désormais calculé (au lieu de `None`).

### Nouveau module `features/mapping.py`
- `DIRECT_MAPPING` : correspondance clé module → colonne `Feature`.
- `UNMAPPED_KEYS` : sorties sans colonne dédiée (non persistées).
- `map_features_to_columns()` : convertit en dict aligné sur les colonnes ;
  colonnes sans source → `None` (jamais 0.0).
- `unconfigured_columns()` : liste les colonnes restées `None`.

### Nouveaux tests `tests/test_features_mapping.py` (6 tests)
- Défaut `"1N2"` matche la donnée ; `"1n2"` ne matche pas.
- Mapping direct ; xG/blessures → `None` ; pas de substitution valide ;
  clés non mappées non persistées.

## Résultats
- `pytest -q` : **94 passed** (88 + 6).

## État Git
```
 M features/odds_movement.py
?? features/mapping.py
?? tests/test_features_mapping.py
```

## Points restants (non résolus)
1. Granularité match/équipe (`rest_days`, `odds_movement`).
2. Règles de dérivation (`elo_rating`, `goal_difference`, `opponent_strength`).
3. Normalisation du code marché `"1n2"`/`"1N2"` dans `models/*` et tests.

## Actions NON effectuées (par consigne)
- Aucun import, aucune génération en base, aucune persistance.
- Aucune modification de schéma, aucun commit.
