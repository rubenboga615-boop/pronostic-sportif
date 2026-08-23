# État actuel du projet

> Fichier de référence à lire en premier. Tenir à jour après chaque session.
> Dernière mise à jour : 2026-08-23.

## Projet
Moteur de pronostic football (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).

## État Git
- Branche : `master`
- Working tree : **non propre** (3 modifications non commitées, voir § Modifications non commitées)
- Dernier commit : `0605122 perf: add indexes for SQLite queries`

## Travaux terminés
- **Foreign keys SQLite activées** via listener SQLAlchemy sur l'événement `connect` (commit `3b14add`).
- **Cinq index non uniques** ajoutés et vérifiés (commit `0605122`) :
  `idx_matches_dedup`, `idx_teams_lookup`, `idx_seasons_lookup`, `idx_odds_match_id`, `idx_tms_match_team`.
- **94 tests passent** (88 initiaux + 6 nouveaux sur le mapping).
- **Test en mémoire du match 68** (Nottingham Forest vs Brentford, 2023-10-01) validé :
  anti-fuite vérifiée (67 matchs antérieurs, 693 exclus), `form_points_5=7`, `rest_days=8`, `league_position=12`.
- **Correctif `odds_movement`** : marché par défaut aligné sur `"1N2"` (non commité).

## Travaux en cours
- Valider le **mapping des features** (`features/mapping.py`, non commité).
- Décider la **granularité** des valeurs par match vs par équipe (`rest_days`, `odds_movement`).
- Persistance des features dans la table `features` : **pas encore réalisée**.

## Blocages / données indisponibles
- **xG** : table `xg_match_stats` vide (source Understat non chargée).
- **Blessures** : table `availability` vide (source non collectée).
- `odds_movement` corrigé mais **non commité**.
- Mapping non validé pour la persistance.

## Modifications non commitées (au 2026-08-23)
- `M  features/odds_movement.py` — défaut marché `"1n2"` → `"1N2"`.
- `?? features/mapping.py` — nouveau module de mapping.
- `?? tests/test_features_mapping.py` — 6 nouveaux tests.

## Sauvegardes
- `backups/pronostic_avant_indexes.db` (avant ajout des index, integrity_check ok).
- `data/backups/pronostic_avant_import_E0_2324.db`, `pronostic_avant_import_E0_2425.db`,
  `pronostic_avant_migration_aliases.db`, `pronostic_avant_migration_ipswich.db`.

## Règles de sécurité (non négociables)
- Ne jamais modifier la base sans sauvegarde préalable vérifiée.
- Ne jamais lancer d'import sans confirmation explicite.
- Toujours exécuter `python -m pytest -q` avant et après toute modification.
- Ne pas implémenter les marchés de Phase 2 sans validation (voir `knowledge.md`).
- Créer un commit séparé par action ; ne jamais committer sans demande explicite.
- Arrêter immédiatement au premier test échoué et afficher l'erreur complète.
- Respecter la règle anti-fuite : aucune donnée future dans les features.
