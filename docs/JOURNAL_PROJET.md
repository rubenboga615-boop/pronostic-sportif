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

## 2026-09-07 (nuit) — Recalcul des features ; le module xG était mort

### Agent
Claude Code (Opus 5)

### Demande
Lancer `python -m pipelines.feature_pipeline`.

### Actions effectuées
- Fichiers modifiés : `features/xg.py` (filtre anti-fuite + bornage saison),
  `pipelines/feature_pipeline.py` (chargement et branchement des xG),
  `docs/ETAT_ACTUEL.md`
- Fichier créé : `tests/test_features_xg.py` (14 tests)
- Base modifiée : **oui**, après sauvegarde vérifiée
  (`pronostic_avant_recalcul_features_20260907_202543.db`)

### Résultats
- Tests : 530 → **544 réussis, 4 ignorés**. Zéro violation `ruff`.
- Premier recalcul : les quinze colonnes de mi-temps se remplissent (92 %),
  calendrier 100 %, solidité 98 %. Contrôles anti-fuite tenus.
- **Mais les xG sortaient à 0 %**, alors que `xg_match_stats` portait 878
  lignes. Deux causes, cumulées :
  1. `features/xg.py` **n'était appelé nulle part** — le pipeline ne
     l'importait même pas. Le module attendait depuis le début.
  2. Son filtre comparait `retrieved_at`, la date de **collecte**, à la date du
     match cible — le défaut `M6`. Une collecte faite aujourd'hui écarte tout
     l'historique ; une collecte ancienne aurait laissé entrer des matchs
     postérieurs à la cible, soit une fuite. Le filtre porte désormais sur la
     date du match.
- Deuxième recalcul : xG à 95 %, mais **un match du 24 mai 2026 recevait une
  moyenne calculée sur des matchs de septembre 2024**. Les moyennes ont été
  **bornées à la saison**, comme la forme et la mi-temps.
- Troisième recalcul, retenu : 720 lignes de xG en 2023/24, 720 en 2024/25,
  zéro en 2025/26. `integrity_check` = ok, aucun doublon.
- **Réserve levée le soir même** (quatrième recalcul) : la fenêtre porte
  désormais sur les matchs **joués**, non sur ceux qui ont un xG. 2023/24
  conserve ses 720 lignes (médiane 7 j) ; 2024/25 tombe de 720 à 158 lignes et
  sa médiane de 108 à 13 jours, sans aucune valeur au-delà de 60 jours. Aucun
  seuil arbitraire : la règle découle de la définition de la variable et se
  corrigera seule quand la source sera complétée.
- Understat répond (HTTP 200) mais sa page ne porte plus les blocs
  `JSON.parse` : les données sont chargées dynamiquement. Compléter la source
  suppose de trouver l'endpoint appelé — travail d'étape 8 à part entière.

### Commit
- Aucun : le dépôt interdit de committer sans demande explicite.

### Décision
- Validé, sous la réserve ci-dessus.

### Prochaine étape
`python scripts/train_models.py` sur 2023/24, seule saison intégralement
décrite, avec et sans xG pour mesurer l'apport d'Understat.

---

## 2026-09-07 (soir) — Correspondances d'équipes, collecteur Understat, saison 2025/26

### Agent
Claude Code (Opus 5)

### Demande
Les trois portes d'entrée identifiées après analyse des CSV du téléphone :
générer les correspondances d'équipes, écrire le collecteur Understat pour
`game_stats.csv`, importer `season-2526.csv`.

### Actions effectuées
- Fichiers créés : `collectors/understat/game_stats.py`,
  `pipelines/understat_import.py`, `tests/test_understat_import.py`
- Fichiers modifiés : `collectors/football_data/team_normalizer.py` (24 noms
  canoniques ajoutés), `collectors/mapping/equipes.json` (34 correspondances),
  `scripts/generer_correspondances.py` (préservation du bloc `_lisez_moi`),
  `tests/test_mapping_equipes.py`, `docs/ETAT_ACTUEL.md`
- Base modifiée : **oui**, deux fois, chaque fois après sauvegarde vérifiée
- Import exécuté : **oui**, sur confirmation explicite

### Résultats
- Tests : 513 → **530 réussis, 4 ignorés**. Zéro violation `ruff`.
- **Correspondances : 165/165 équipes Understat résolues.** Le générateur
  proposait huit rapprochements faux, tous rejetés à la relecture :
  Almeria/Valencia, Rayo Vallecano/Real Valladolid, Carpi/Cagliari,
  Cremonese/Crotone, Angers/Nantes, Caen/Amiens, Nimes/Nice, et surtout
  **GFC Ajaccio → Ajaccio proposé à 1,0** alors que le Gazélec et l'AC Ajaccio
  sont deux clubs distincts ayant tous deux joué en Ligue 1. Le Gazélec a reçu
  son propre nom canonique ; un test vérifie que les deux ne se confondent pas.
- 24 clubs n'avaient aucun nom canonique — ils manquaient à
  `team_normalizer.py`. Sans eux, 4 441 matchs sur 18 381 étaient irrécupérables
  (51 % de la Ligue 1). Les graphies Football-Data ajoutées restent **à
  confirmer au premier import réel** : elles n'ont pas pu être vérifiées, le
  site étant injoignable.
- **xG importés : 878 lignes** (439 matchs × 2), `scores_discordants = 0`. Le
  contrôle de concordance de score valide le rattachement, qui se fait par
  (club, jour, camp) — l'export n'a aucun identifiant de match, et (ligue, date)
  ne suffit pas : jusqu'à dix matchs partagent la même heure en dernière journée.
- **Saison 2025/26 importée** : 380 matchs, mi-temps et arbitre à 100 %, aucune
  cote. Les 760 matchs déjà en base ont été reconnus comme doublons.
- Base après import : 1 140 matchs, `integrity_check` = ok,
  `foreign_key_check` sans violation, aucun doublon.

### Commit
- Aucun : le dépôt interdit de committer sans demande explicite.

### Décision
- Validé.

### Prochaine étape
`python -m pipelines.feature_pipeline` — les quinze colonnes de mi-temps sont
créées mais vides, 380 matchs sont nouveaux, et les xG sont désormais
disponibles sur 439 matchs.

---

## 2026-09-07 — Migrations appliquées ; sonde et import bloqués faute d'accès

### Agent
Claude Code (Opus 5)

### Demande
Lancer sur cette machine les trois opérations impossibles ailleurs faute de
réseau : `appliquer_migrations.py --etat` puis sans `--etat`,
`sonde_api_football.py`, et `import_historical_data.py` (12 saisons).

### Actions effectuées
- Fichiers modifiés : `scripts/appliquer_migrations.py` (option
  `--marquer-appliquee`), `tests/test_appliquer_migrations.py` (7 tests),
  `docs/ETAT_ACTUEL.md`, `docs/JOURNAL_PROJET.md`
- Commandes exécutées : `pytest -q` (avant et après), `ruff check`,
  `appliquer_migrations.py --etat`, `--marquer-appliquee` ×4, puis sans option
- Base modifiée : **oui** — `data/pronostic.db`, après sauvegarde vérifiée
- Import exécuté : **non** — impossible, voir Résultats

### Résultats
- Tests : 506 réussis / 4 ignorés avant, **513 réussis / 4 ignorés** après.
  Zéro violation `ruff`.
- **Blocage rencontré** : le registre `schema_migrations` était vide alors que
  quatre migrations avaient déjà été appliquées à la main, avant que le lanceur
  n'existe. `20260906_add_prediction_traceability.sql` n'est pas idempotente :
  rejouée, elle échouait sur `duplicate column name: data_cutoff_at` et
  bloquait les deux migrations réellement en attente. Reproduit sur une copie
  avant tout contact avec la base réelle.
- **Levée** : option `--marquer-appliquee` ajoutée au lanceur — inscrit une
  migration au registre sans l'exécuter, après sauvegarde vérifiée, en
  refusant tout nom inconnu avant d'écrire quoi que ce soit.
- Vérifications SQLite : `integrity_check` = ok, `foreign_key_check` sans
  violation, schéma **conforme à l'ORM** sur les sept tables contrôlées,
  760 matchs / 1 520 features / 9 285 cotes préservés.
- **Sonde API-Football : non exécutable.** `API_FOOTBALL_KEY` n'est pas
  définie (aucun `.env`, seulement `.env.example`). La sonde s'exécute mais
  tente **0 appel** et rapporte « injoignable » partout. Aucun quota consommé.
- **Import des 12 saisons : non exécutable.** `football-data.co.uk` renvoie
  **503** à chaque essai depuis cette machine (page de blocage nginx, réponse
  identique avec un user-agent de navigateur), alors que `example.com` répond
  200. Le blocage réseau décrit dans `ROADMAP.md` vaut donc aussi ici. Seuls
  les deux CSV `E0_2324` et `E0_2425` sont présents en local.

### Commit
- Aucun : le dépôt interdit de committer sans demande explicite.

### Décision
- Migrations : appliquées et vérifiées.
- Sonde et import : reportés, faute de clé API et d'accès réseau.

### Prochaine étape
Recalculer les features (`python -m pipelines.feature_pipeline`) : la migration
crée les quinze colonnes de mi-temps, elle ne les remplit pas. À faire de
préférence **après** l'import des 12 saisons, pour n'avoir à le faire qu'une
fois.

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
