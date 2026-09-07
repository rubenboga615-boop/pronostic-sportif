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

## Première évaluation hors échantillon
Modèle Dixon-Coles entraîné sur 2023/24, appliqué aux 380 matchs de 2024/25 :

| Marché | Accuracy | Log-loss | Brier | AUC | ROI |
|---|---|---|---|---|---|
| 1N2 | 0,508 | 0,590 | 0,201 | 0,693 | −3,16 % |
| Over/Under | 0,721 | 0,539 | 0,182 | 0,805 | −2,16 % |
| 1N2 1re mi-temps | 0,393 | 0,621 | 0,215 | 0,609 | — |
| BTTS | 0,518 | 0,735 | 0,266 | 0,537 | — |

Références : pari naïf sur le domicile **−16,60 %**, favori du marché
**−3,56 %**. Le modèle bat nettement la stratégie naïve et se tient au niveau
du marché, sur une seule saison d'entraînement.

Sa courbe de calibration montre un excès de confiance dans le haut du spectre
(annoncé 0,84 → observé 0,67) : c'est ce que la calibration doit corriger, une
fois qu'il y aura une saison de validation distincte.

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
**Entraîner** (`python scripts/train_models.py`) sur 2023/24, seule saison
intégralement décrite — xG compris — puis lancer le pipeline de prédiction. Un
entraînement avec et sans xG donnera la première mesure de l'apport d'Understat.

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
