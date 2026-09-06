# État actuel du projet

> Fichier de référence à lire en premier. Tenir à jour après chaque session.
> Dernière mise à jour : 2026-09-06.

## Projet
Moteur de pronostic football (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).

## État Git
- Branche : `claude/audit-lecture-seule-s5yd7b`
- Working tree : **propre**
- Suite de tests : **223 réussis, 3 ignorés** (les tests ignorés sont les
  garde-fous anti-production, actifs uniquement si `data/pronostic.db` existe)
- Style : **zéro violation `ruff`**, vérifié en intégration continue

## Feuille de route
`docs/ROADMAP.md` découpe le travail restant en treize étapes, du nettoyage des
données au déploiement. **L'étape 0 est terminée ; la suite commence à
l'étape 1.**

## Travaux terminés
- **Foreign keys SQLite activées** via listener SQLAlchemy sur l'événement `connect`.
- **Cinq index non uniques** ajoutés (`migrations/20260822_add_indexes.sql`).
- **Import historique** Football-Data.co.uk : parse, normalisation des équipes,
  déduplication, rapport de qualité, `provider_match_id` déterministe.
- **Pipeline de features** : calcul et persistance de deux lignes par match,
  mapping explicite vers les colonnes du modèle `Feature`.
- **Pipeline de prédiction** : contexte anti-fuite, assemblage des 16 marchés de
  match entier, persistance idempotente, une transaction par match.
- **Date de coupure** : seuls les matchs strictement postérieurs à une
  `reference_date` fournie par l'appelant sont prédits. Le pipeline ne rejoue
  plus tout l'historique à chaque exécution.
- **Intégration continue** : `ruff check`, `ruff format --check` et `pytest` à
  chaque poussée.
- **Paquet installable** : backend de build corrigé, `pydantic-settings` et
  `scipy` déclarés.

## Contenu réel de la base (`data/pronostic.db`)
| Table | Lignes |
|---|---|
| `competitions` | 1 (Premier League) |
| `seasons` | 2 (2023/24, 2024/25) |
| `matches` | 760, du 11/08/2023 au 25/05/2025, aucun sans score |
| `teams` | 23, sans fragmentation de noms |
| `odds_snapshots` | 9 285, marché 1N2 uniquement |
| `features` | 1 520 |
| `predictions` | **0** — le pipeline n'a jamais été exécuté sur cette base |
| `actual_results`, `xg_match_stats`, `availability` | **0** |

## Défauts connus, à traiter dans l'ordre de la feuille de route
- **C1 — fuite de données** : `odds_movement` est calculé depuis les cotes de
  **clôture** (`B365_close`) et persisté sur 100 % des lignes de `features`. Ses
  valeurs corrèlent avec le résultat des matchs. Interdit par `PROJECT_SPEC.md`.
- **C2 — classement inter-saisons** : `calculate_standings` ne filtre pas par
  saison. `league_position` monte à 23 dans un championnat à 20 équipes, et
  Arsenal démarre 2024/25 à la 2ᵉ place avec +62 de différence de buts. Même
  cause pour `rest_days`, qui atteint 92 jours (trêve estivale).
- **C3 — évaluation** : le ROI du backtest est calculé contre les cotes du
  modèle lui-même ; l'accuracy porte sur toutes les sélections sans retenir la
  plus probable.
- **C4 — test anti-fuite tautologique** : `tests/test_no_data_leakage.py`
  n'exerce pas le code de production.
- **E1 — Dixon-Coles factice** : `fit_dixon_coles` ne réalise aucune estimation.
- **E6 — complexité quadratique** du pipeline de features.
- Détail complet et repères `E*`, `M*`, `F*`, `N*` : voir `docs/ROADMAP.md`.

## Blocages / données indisponibles
- **xG** : `xg_match_stats` vide, collecteur Understat non écrit (étape 8).
- **Blessures** : `availability` vide, collecteur API-Football non écrit (étape 7).
- **Matchs à venir** : aucune source de calendrier, d'où l'absence de prédictions.
- **Cotes Over/Under** : présentes dans les CSV, ignorées par le parseur (étape 3).
- `requirements.txt` épingle des versions inexistantes sur PyPI (numpy 2.5.2) :
  `make install` échoue. La CI installe depuis `pyproject.toml`.

## Sauvegardes
- `data/backups/pronostic_avant_import_E0_2324.db`, `pronostic_avant_import_E0_2425.db`,
  `pronostic_avant_migration_aliases.db`, `pronostic_avant_migration_ipswich.db`
- `data/pronostic.db.before-features-20260823-2029.bak`
- `data/pronostic.db.before-odds-movement-fix-20260823-2247.bak`

## Règles de sécurité (non négociables)
- Ne jamais modifier la base sans sauvegarde préalable vérifiée.
- Ne jamais lancer d'import sans confirmation explicite.
- Toujours exécuter `python -m pytest -q` avant et après toute modification.
- Ne pas implémenter les marchés de Phase 2 sans validation (voir `knowledge.md`).
- Créer un commit séparé par action ; ne jamais committer sans demande explicite.
- Arrêter immédiatement au premier test échoué et afficher l'erreur complète.
- Respecter la règle anti-fuite : aucune donnée future dans les features.
