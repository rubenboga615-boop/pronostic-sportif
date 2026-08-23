# Journal du projet

> Historique des actions, par session. Une entrée par action significative.
> Chaque entrée suit le modèle ci-dessous.

---

## Modèle d'entrée

### Agent
Freebuff / Claude Code / autre

### Demande
Résumé exact de la demande.

### Actions effectuées
- Fichier(s) modifié(s) :
- Fichier(s) créé(s) :
- Commandes exécutées :
- Base modifiée : oui / non
- Import exécuté : oui / non

### Résultats
- Tests :
- Vérifications SQLite :
- Résultat obtenu :

### Commit
- Hash / message :

### Décision
- Validé / à revoir / refusé

### Prochaine étape
Description précise.

---

## 2026-08-23 — Préparation du mapping des features

### Agent
Claude Code (modèle DeepSeek)

### Demande
Corriger l'incohérence `odds_movement` (marché `"1N2"`), proposer un mapping
explicite modules → modèle `Feature`, signaler les sorties non stockables,
représenter proprement les valeurs absentes (xG/blessures), ajouter des tests.
Sans persister, sans import, sans modifier le schéma, sans commit.

### Actions effectuées
- Fichier modifié : `features/odds_movement.py` (défaut `"1n2"` → `"1N2"`).
- Fichiers créés : `features/mapping.py`, `tests/test_features_mapping.py`.
- Commandes : `pytest -q` (94 passed).
- Base modifiée : non.
- Import exécuté : non.

### Résultats
- Tests : 94 passed (6 nouveaux : odds_movement + mapping).
- Mapping : direct pour form/goals/shots/xg/odds/league_position/injury ; sorties
  non stockables listées dans `UNMAPPED_KEYS` ; valeurs absentes → `None`.
- Résultat : prêt à valider, non persisté.

### Commit
- Aucun (arrêt volontaire avant commit).

### Décision
- À valider (points restants : granularité match/équipe, règles de dérivation
  `elo_rating`/`goal_difference`/`opponent_strength`).

### Prochaine étape
Trancher la granularité `rest_days`/`odds_movement` et les règles de dérivation,
puis committer les trois fichiers avant toute persistance.

---

## 2026-08-22 — Index SQLite

### Agent
Claude Code (modèle DeepSeek)

### Demande
Analyser les index (lecture seule), proposer une migration, créer 5 index non
uniques dans une migration réversible, sans contrainte UNIQUE, sans import.

### Actions effectuées
- Fichier créé : `migrations/20260822_add_indexes.sql` (5 `CREATE INDEX IF NOT EXISTS`).
- Sauvegarde créée : `backups/pronostic_avant_indexes.db` (integrity_check ok).
- Base modifiée : oui (5 index ajoutés).
- Import exécuté : non.

### Résultats
- Tests : 88 passed.
- Vérifications : `integrity_check=ok`, `foreign_key_check` sans violation,
  `EXPLAIN QUERY PLAN` confirme l'usage des 5 index.
- Résultat : 5 index utilisés ; 3 index complémentaires identifiés pour
  features/backtest (non créés).

### Commit
- `0605122 perf: add indexes for SQLite queries`

### Décision
- Validé.

### Prochaine étape
Mesurer l'usage réel (fait), puis décider des index features/backtest.

---

## 2026-08-22 — Foreign keys SQLite

### Agent
Claude Code (modèle DeepSeek)

### Demande
Activer `PRAGMA foreign_keys=ON` via un listener SQLAlchemy sur l'événement
`connect`, sans toucher aux index ni à la base.

### Actions effectuées
- Fichier modifié : `app/database.py` (ajout `@event.listens_for(engine, "connect")`).
- Base modifiée : non.
- Import exécuté : non.

### Résultats
- Tests : 88 passed.
- Vérifications : `foreign_keys=1`, `integrity_check=ok`, `foreign_key_check` vide.
- Résultat : contrainte FK active.

### Commit
- `3b14add fix: enable SQLite foreign key enforcement`

### Décision
- Validé.

### Prochaine étape
Analyse des index (fait ensuite).

---

## 2026-08-22 — .gitignore backups

### Agent
Claude Code (modèle DeepSeek)

### Demande
Ajouter `backups/` au `.gitignore`.

### Actions effectuées
- Fichier modifié : `.gitignore` (ajout `backups/`).

### Résultats
- Working tree propre après commit.

### Commit
- `749e584 chore: ignore local backups`

### Décision
- Validé.
