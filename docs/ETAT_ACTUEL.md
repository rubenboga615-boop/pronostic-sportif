# État actuel du projet

> Fichier de référence à lire en premier. Tenir à jour après chaque session.
> Dernière mise à jour : 2026-09-07.

## Projet
Moteur de pronostic football (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).

## État Git
- Branche : `claude/audit-lecture-seule-s5yd7b`
- Working tree : **propre**
- Suite de tests : **550 réussis, 4 ignorés** (les tests ignorés sont les
  garde-fous anti-production, actifs uniquement si `data/pronostic.db` existe)
- Sans l'extra `ml` : **425 réussis, 7 ignorés** — les quatre tests de
  calibration s'ignorent faute de scikit-learn, et c'est voulu. Le noyau
  (import, features, entraînement, prédiction, règlement, backtest) n'en a pas
  besoin. Pour les exécuter : `pip install -e ".[ml]"`.
- Style : **zéro violation `ruff`**, vérifié en intégration continue
- Avertissements : **zéro** (les 2 914 dépréciations `datetime.utcnow()` sont
  corrigées)

## Feuille de route
`docs/ROADMAP.md`. **Lots A et B terminés (étapes 0 à 6.)**

**Étape 6 b terminée le 07/09/2026.** Prochaine étape de code : le lot C
(API-Football, Understat, API et interface d'administration).

Restent le lot C (API-Football, Understat, API et interface d'administration),
le lot D (automatisation, déploiement, suivi) et le lot E (coupons, rédaction
assistée, abonnements) — ce dernier **conditionné** à un rendement positif
mesuré sur les deux saisons de test.

Décisions et motifs : `docs/DECISIONS.md`.

## Corpus en base au 07/09/2026

| Saison | Matchs | Mi-temps | Arbitre | Cotes | xG |
|---|---|---|---|---|---|
| 2023/24 | 380 | 380 | — | oui | 380 matchs — **couverture complète** |
| 2024/25 | 380 | 380 | — | oui | 59 matchs — début de saison seulement |
| 2025/26 | 380 | 380 | 380 | **non** | — |

**1 140 matchs**, Premier League seulement. `xg_match_stats` porte 878 lignes
(439 matchs × 2 équipes), source `understat`, contrôlées par concordance de
score : **zéro discordance** sur les 878.

2025/26 vient d'un export sans cotes : ces 380 matchs servent à l'entraînement
et aux métriques de probabilité (log-loss, Brier, AUC), **pas au rendement**.
Aucun edge n'est calculable dessus.

## Ce qui fonctionne de bout en bout
Import → features → entraînement → prédiction → règlement → valorisation →
backtest. Vérifié sur les données réelles : 760 matchs importés avec leurs
cotes Over/Under, modèle entraîné sur 2023/24, 10 160 prédictions générées et
réglées sur 2024/25, rapport de backtest complet.

## Évaluation sur 2025/26 — saison jamais vue (08/09/2026)

Dixon-Coles entraîné sur **2023/24 + 2024/25** (760 matchs, 23 équipes),
appliqué aux 380 matchs de 2025/26. Découpage signalé au titre de D-02 :
`--train-end 2025-06-30`, faute des saisons 2015/16 → 2022/23.

| Marché | matchs | Accuracy | Log-loss | Brier | AUC | Err. calibr. |
|---|---|---|---|---|---|---|
| 1N2 | 380 | 0,463 | 0,610 | 0,210 | 0,645 | 0,046 |
| Over/Under | 380 | 0,732 | 0,544 | 0,181 | 0,752 | — |
| Over/Under 1re MT | 306 | 0,764 | 0,525 | 0,174 | **0,782** | — |
| 1N2 1re mi-temps | 306 | 0,418 | 0,608 | 0,210 | 0,630 | — |
| Mi-temps prolifique | 306 | 0,441 | 0,620 | 0,215 | 0,608 | — |
| BTTS | 380 | 0,539 | 0,729 | 0,263 | 0,534 | — |

**Aucun rendement n'est mesurable** : 2025/26 est entrée sans cotes. Les
stratégies `edge_5pct` et `edge_2pct` retiennent zéro pari, et les références
naïve et marché sont indisponibles. Seules log-loss, Brier et AUC valent ici.

### Une saison d'entraînement de plus vaut mieux qu'une saison de validation
Comparé au même protocole entraîné sur 2023/24 seule, l'ajout de 2024/25
améliore **22 des 24 comparaisons** (4 métriques × 6 marchés) — seule l'AUC du
BTTS recule, de 0,545 à 0,534. Les écarts sont petits un à un ; leur cohérence
ne l'est pas.

Le gain décisif est la **calibration, de 0,066 à 0,046**, et il porte là où il
comptait :

| Annoncé | 1 saison | 2 saisons |
|---|---|---|
| 0,55 | 0,40 | **0,48** |
| 0,64 | 0,57 | **0,66** |
| 0,74 | 0,65 | **0,75** |

La surconfiance du haut du spectre, que D-06 identifie comme rédhibitoire pour
les coupons puisqu'elle se compose en puissance, a largement disparu.

Dixon-Coles ne réglant aucun hyperparamètre sur la validation, réserver une
saison à cet usage revenait à jeter 380 matchs. Le découpage à trois volets
reprendra son sens le jour où une couche à hyperparamètres existera.

### Deux limites à connaître avant de lire ces chiffres
- **Leeds United et Sunderland n'ont jamais été vues à l'entraînement** — elles
  montent en 2025/26 — et jouent 108 des 380 matchs, soit 28 % du jeu de test.
  Le modèle n'a aucune force estimée pour elles.
- **Les marchés de mi-temps ne couvrent que 306 matchs sur 380.** Les 74
  manquants sont ceux dont les variables `ht_*` sont vides : les premières
  journées, où aucun taux n'est fondé. Pas de variable, pas de prédiction —
  cohérent, mais cela coûte 19 % des matchs sur 15 des 31 sélections.

## Travaux terminés
- **Foreign keys SQLite**, **index déclarés dans l'ORM** et **contraintes
  d'unicité** sur les clés logiques de `features`, `predictions`, `matches` et
  `actual_results`.
- **Import Football-Data** : parse, normalisation, déduplication, cotes 1N2 et
  Over/Under 2,5 (ouverture et clôture), détection des colonnes disparues,
  rapport de qualité horodaté.
- **Téléchargeur** : réessais réellement opérants sur erreur transitoire,
  écriture atomique, refus des réponses vides.
- **Pipeline de features** : contexte incrémental, coût par match indépendant
  de la taille de la base (~17 ms, soit ~5 min pour 20 000 matchs).
- **Anti-fuite** : classement, Elo, repos et variables de mi-temps bornés à la
  saison ; mouvement de cote étanche par construction ; test anti-fuite par
  historique empoisonné et mouchard de dates.
- **Première mi-temps** : dix variables décrivant le comportement des équipes
  avant la pause. Quinze des trente et une sélections en dépendent, et rien ne
  la décrivait — `HTHG`/`HTAG` étaient en base depuis le premier import, seul
  le calcul dérivé manquait.
- **Encombrement du calendrier** : matchs joués sur 7 et 14 jours, écart de
  repos entre les deux équipes.
- **Plus aucune colonne orpheline** : les quatre colonnes déclarées au schéma
  sans écrivain — `home_away_goals_*`, `opponent_strength`,
  `data_completeness` — sont toutes alimentées.
- **Dixon-Coles** entraîné par maximum de vraisemblance, avec pondération
  temporelle, ajusté par compétition, enregistré dans le registre des modèles.
- **Marchés** : 31 sélections par match (match entier + première mi-temps +
  mi-temps la plus prolifique).
- **Règlement, valorisation, backtest, calibration** : la boucle est fermée.
- **Intégration continue** : `ruff check`, `ruff format --check` et `pytest`
  sur Python 3.11 et 3.12, plus un job qui installe le noyau seul et vérifie
  que la suite reste verte sans les extras.

## Migrations — toutes appliquées le 07/09/2026

Les six migrations du dossier `migrations/` sont passées et inscrites au
registre `schema_migrations`. Vérifié après coup : `PRAGMA integrity_check` = ok,
`PRAGMA foreign_key_check` sans violation, schéma **conforme à l'ORM** sur les
sept tables contrôlées, 760 matchs / 1 520 features / 9 285 cotes préservés.

Quatre d'entre elles — `20260822_add_indexes`, `20260906_add_unique_indexes`,
`20260906_add_prediction_traceability` et `20260906_purge_odds_movement` —
avaient en réalité **déjà été appliquées à la main**, avant l'existence du
lanceur. Le registre les ignorait, et
`20260906_add_prediction_traceability.sql` n'est pas idempotente : rejouée,
elle échouait sur `duplicate column name: data_cutoff_at` et **bloquait les
deux migrations réellement en attente**.

D'où l'option `--marquer-appliquee` ajoutée au lanceur : elle inscrit une
migration au registre **sans l'exécuter**, après sauvegarde vérifiée, en
refusant tout nom inconnu avant la moindre écriture. C'est le cas d'une base
modifiée avant l'adoption d'un outil de migration ; sans cette porte, la seule
issue est un `INSERT` manuel que rien ne trace.

Les deux migrations réellement appliquées ce jour-là :
`20260907_add_half_time_features.sql` (quinze colonnes) et
`20260907_add_referee.sql`.

**Reste à faire** : recalculer les features
(`python -m pipelines.feature_pipeline`). La migration crée les quinze
colonnes de mi-temps, elle ne les remplit pas — elles sont NULL aujourd'hui.
À faire de préférence **après** l'import des 12 saisons, pour n'avoir à le
faire qu'une fois. Le classement, l'Elo et les jours de repos actuellement en
base ont par ailleurs été calculés avec les défauts corrigés depuis.

## Features recalculées le 07/09/2026
2 280 lignes, deux par match. Remplissage :

- **mi-temps** 92 %, **calendrier** 100 %, **solidité** 98 % — les quinze
  colonnes migrées le matin même sont désormais alimentées ; les vides sont les
  premières journées de chaque saison, où aucun taux n'est fondé.
- **xG** : 720 lignes en 2023/24, 158 en 2024/25, aucune en 2025/26 (non
  couverte par la source). Aucune valeur ne s'appuie sur un xG de plus de
  60 jours.
- Contrôles : `MAX(league_position)` = 20, `odds_movement` nul partout, aucun
  doublon, `integrity_check` = ok.

### Deux défauts corrigés au passage
`features/xg.py` existait depuis le début et **n'était appelé nulle part** : les
trois colonnes seraient restées vides même une fois `xg_match_stats` peuplée.
Son filtre anti-fuite comparait de plus `retrieved_at`, la date de **collecte**,
à la date du match — le défaut `M6` de la feuille de route. Une collecte faite
aujourd'hui écartait tout l'historique ; une collecte ancienne aurait laissé
entrer des matchs postérieurs à la cible. Le filtre porte désormais sur la date
du match, et les moyennes sont **bornées à la saison**, comme la forme et les
variables de mi-temps.

### La fenêtre xG porte sur les matchs joués, pas sur les matchs couverts
Troisième correctif de la soirée, et le plus structurant. Le calcul retenait
les cinq derniers matchs **pour lesquels un xG existait** : la source s'arrêtant
au 29/09/2024, un match de mai 2025 recevait la moyenne des cinq premières
journées de la saison, présentée comme sa forme du moment — 108 jours d'âge
médian, 72 % des lignes au-delà de 60 jours.

La fenêtre porte désormais sur les matchs **réellement joués**, et la valeur
n'est produite que si ces matchs-là sont couverts :

| Saison | Lignes avant | Lignes après | Âge médian | > 60 j |
|---|---|---|---|---|
| 2023/24 | 720 | **720** | 7 j → 7 j | 0 % |
| 2024/25 | 720 | **158** | 108 j → **13 j** | **0 %** |

La saison complètement couverte ne perd rien ; seules disparaissent les 562
valeurs qui décrivaient une forme révolue. Aucun seuil d'ancienneté arbitraire
n'a été introduit : la règle découle de la définition de la variable, et les
valeurs reviendront d'elles-mêmes le jour où la source sera complétée.

## Prochaine action
**Le moteur ne consomme pas les features.** C'est le constat le plus important
de la journée du 07/09. Sur les 38 colonnes de `features`, `market_assembly`
n'en lit que deux — `goals_for_avg_5` et `goals_against_avg_5`. Les 878 xG
importés et les quinze variables de mi-temps calculées **n'atteignent aucun
modèle** : Dixon-Coles s'estime sur les buts seuls, conformément à D-05, et la
couche de gradient boosting que cette décision qualifie d'« éventuelle »
n'existe pas.

Tant qu'elle n'existe pas, mesurer l'apport d'Understat est impossible, et la
question laissée ouverte par l'étape 6 b — l'effet des variables de mi-temps sur
l'AUC du 1N2 de première période — reste sans réponse.

Deux directions, à trancher :
1. **Ouvrir la couche qui consomme les features** (D-05). C'est ce qui rendrait
   utile le travail des étapes 6 b et 8. Le hors-périmètre de `ROADMAP.md`
   l'autorise depuis la fin de l'étape 6.
2. **Poursuivre le lot C** — étape 9, l'API et l'interface d'administration —
   en laissant les features en attente d'un consommateur.

### L'import des 12 saisons reste à faire
`football-data.co.uk` renvoie un **503** depuis toutes les machines essayées
(07/09/2026), y compris celle de l'utilisateur. Contournement praticable, celui
qui a servi pour 2025/26 : déposer le CSV dans
`data/raw/football_data/{code}/{code}_{saison}.csv`, puis
`python scripts/import_historical_data.py --skip-download`. L'export Understat
local couvre déjà 18 381 matchs des cinq championnats : leurs xG s'importeront
d'eux-mêmes à mesure que les matchs entreront en base.

## Blocages / données indisponibles
- **xG** : partiellement levé. Le collecteur Understat est écrit
  (`collectors/understat/game_stats.py`, `pipelines/understat_import.py`) et
  `xg_match_stats` porte 878 lignes. L'export local couvre 18 381 matchs des
  cinq championnats (2014/15 → 2023/24) : le reste s'importera à mesure que les
  matchs correspondants entreront en base.
- **API-Football** : `API_FOOTBALL_KEY` **n'est pas définie** — aucun `.env`,
  seulement `.env.example`. La sonde `scripts/sonde_api_football.py` s'exécute
  mais ne tente **aucun appel** et rapporte « injoignable » partout (vérifié le
  07/09/2026, quota consommé : 0). Rien de l'étape 7 ne peut être mesuré tant
  que la clé n'est pas fournie.
- **football-data.co.uk injoignable** : 503 systématique, y compris depuis la
  machine de l'utilisateur (07/09/2026). Bloque l'import des 12 saisons.
- **Blessures** : `availability` vide, collecteur API-Football non écrit (étape 7).
- **Matchs à venir** : aucune source de calendrier, d'où l'absence de
  prédictions sur des matchs non joués (étape 7).
- **`odds_movement`** : restera `None` tant qu'aucune source ne fournira
  plusieurs relevés pré-match horodatés. C'est volontaire.
- `requirements.txt` épingle des versions inexistantes sur PyPI (numpy 2.5.2) :
  `make install` échoue. La CI installe depuis `pyproject.toml`.
- Convention de nommage `B365_close` / `PS_close` dans la colonne `bookmaker` :
  `is_closing` porte déjà l'information, ce doublon est à nettoyer un jour.

## Sauvegardes
- `data/backups/pronostic_avant_recalcul_features_20260907_202543.db` (avant recalcul)
- `data/backups/pronostic_avant_import_understat_20260907_111841.db` (avant les xG)
- `data/backups/pronostic_avant_import_2526_20260907_202014.db` (avant la saison 2025/26)
- `data/backups/pronostic_avant_migrations_20260907_081633.db` (avant marquage)
- `data/backups/pronostic_avant_migrations_20260907_081657.db` (avant les deux
  dernières migrations)
- `data/backups/pronostic_avant_import_E0_2324.db`, `pronostic_avant_import_E0_2425.db`,
  `pronostic_avant_migration_aliases.db`, `pronostic_avant_migration_ipswich.db`
- `data/pronostic.db.before-features-20260823-2029.bak`
- `data/pronostic.db.before-odds-movement-fix-20260823-2247.bak`

## Règles de sécurité (non négociables)
- Ne jamais modifier la base sans sauvegarde préalable vérifiée.
- Ne jamais lancer d'import sans confirmation explicite.
- Toujours exécuter `python -m pytest -q` avant et après toute modification.
- Ne pas implémenter les marchés de Phase 2 sans validation (voir `knowledge.md`).
- Ne publier aucun coupon tant que le rendement n'est pas positif sur les deux
  saisons de test (`docs/DECISIONS.md`, D-06).
- Ne jamais modifier une probabilité, une cote, un edge ou un résultat réglé
  hors migration versionnée (D-10).
- Créer un commit séparé par action ; ne jamais committer sans demande explicite.
- Arrêter immédiatement au premier test échoué et afficher l'erreur complète.
- Respecter la règle anti-fuite : aucune donnée future dans les features.
