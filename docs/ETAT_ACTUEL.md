# État actuel du projet

> Fichier de référence à lire en premier. Tenir à jour après chaque session.
> Dernière mise à jour : 2026-09-08.

## Projet
Moteur de pronostic football (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).

## État Git
- Branche : `claude/audit-lecture-seule-s5yd7b`
- Working tree : **propre**
- Suite de tests : **562 réussis, 0 ignoré** (scikit-learn installé : les
  quatre tests de calibration ne s'ignorent plus) (les tests ignorés sont les
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

## Ce qui fonctionne de bout en bout
Import → features → entraînement → prédiction → règlement → valorisation →
backtest. Vérifié sur les données réelles : 760 matchs importés avec leurs
cotes Over/Under, modèle entraîné sur 2023/24, 10 160 prédictions générées et
réglées sur 2024/25, rapport de backtest complet.

## Corpus débloqué le 08/09/2026 — 3 420 matchs

football-data.co.uk restant injoignable (503), les CSV ont été récupérés sur un
**miroir GitHub** (`jokecamp/FootballData`), au format d'origine et complets :
mi-temps, arbitre, sept bookmakers, Over/Under 2,5 et **cotes de clôture
Pinnacle**.

Authenticité vérifiée avant import, par croisement avec une source
indépendante : **2 254 matchs comparés aux scores d'Understat, zéro
discordance**.

| | avant | après |
|---|---|---|
| Matchs | 1 140 | **3 420** (9 saisons) |
| Cotes | 9 285 | **46 516** |
| Lignes de xG | 878 | **5 386** |
| Lignes de features | 2 280 | **6 840** |

Saisons en base : 2014/15 → 2019/20, puis 2023/24 → 2025/26. **Manquent
2020/21, 2021/22 et 2022/23** : le miroir s'arrête en janvier 2021.

## Rendement mesuré, et l'effet de la calibration

Protocole enfin conforme à l'esprit de D-02 : entraînement sur 2014/15 →
2019/20 (2 214 matchs), **calibration ajustée sur 2023/24**, saison absente de
l'entraînement, puis appliquée à 2024/25 et 2025/26. Rendement contre les cotes
de **clôture**.

### La calibration change tout sur le 1N2

| Marché | probabilités | toutes | edge ≥ 0 | edge ≥ 2 % | edge ≥ 5 % |
|---|---|---|---|---|---|
| 1N2 | brutes | −2,87 | −11,17 | −14,15 | −16,16 |
| 1N2 | **Platt** | −2,87 | −6,25 | −5,33 | **−6,05** |
| Over/Under | brutes | −1,83 | −3,85 | −5,15 | −7,63 |
| Over/Under | **Platt** | −1,83 | +0,00 | +2,46 | **+6,55** |

Platt ramène l'erreur de calibration de **0,107 à 0,044**, améliore log-loss
(0,672 → 0,631) et Brier (0,232 → 0,219), et récupère **dix points de ROI** sur
la sélection à 5 % du 1N2. La méthode isotonique fait moins bien (0,067) : elle
demande plus de données, comme l'annonce son module.

Sur l'Over/Under calibré, le rendement **croît avec le seuil d'edge**
(0,00 → +2,46 → +6,55). C'est le comportement qu'on attend d'un edge porteur
d'information, et l'inverse exact de ce qu'on observait sans calibration.

### ⚠️ Mais rien n'est prouvé — les intervalles englobent zéro

| Marché | seuil | paris | ROI | IC 95 % (bootstrap) |
|---|---|---|---|---|
| 1N2 | ≥ 5 % | 405 | −6,05 % | [−24,91 ; +13,97] |
| Over/Under | ≥ 2 % | 326 | +2,46 % | [−11,05 ; +15,46] |
| Over/Under | ≥ 5 % | 262 | **+6,55 %** | **[−9,18 ; +22,15]** |

**Aucun de ces chiffres n'est statistiquement distinguable de zéro.** Le +6,55 %
est un signe encourageant, pas un résultat. L'écart-type du gain par pari est de
1,19 : il faudrait

- **~2 200 paris** pour établir un ROI de +5 % (≈ 3 saisons),
- ~6 100 pour +3 %,
- ~13 600 pour +2 %.

Nous en avons **262**. C'est l'argument décisif pour compléter le corpus : les
quatre autres championnats et les saisons manquantes, non pour mieux entraîner,
mais pour pouvoir **mesurer**.

**D-06 reste non remplie** : la condition est un rendement positif *démontré*.
Le lot E reste fermé.

### Métriques de probabilité (760 matchs de test)

| Marché | matchs | Accuracy | Log-loss | Brier | AUC |
|---|---|---|---|---|---|
| 1N2 | 760 | 0,458 | 0,616 | 0,212 | 0,644 |
| Over/Under | 760 | 0,737 | 0,527 | 0,176 | 0,751 |
| Over/Under 1re MT | 684 | 0,752 | 0,539 | 0,179 | 0,767 |
| 1N2 1re mi-temps | 684 | 0,392 | 0,615 | 0,213 | 0,616 |
| Mi-temps prolifique | 684 | 0,442 | 0,624 | 0,217 | 0,606 |
| BTTS | 760 | 0,553 | 0,702 | 0,253 | 0,561 |

### Un troisième module écrit et jamais branché
`evaluation/pricing.py` calcule `offered_odds` et `edge` depuis
`odds_snapshots`. **Aucun pipeline ne l'appelle** : les 22 420 prédictions
étaient toutes sans prix, et le rendement restait `None` faute d'être
calculable. Il a fallu l'invoquer à la main pour obtenir les chiffres ci-dessus.
C'est le même défaut que `features/xg.py` la veille — à brancher.

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
**Compléter le corpus, pour pouvoir mesurer.** C'est désormais le seul verrou :
le protocole tient, la calibration fonctionne, l'Over/Under montre un signe
positif — mais 262 paris ne permettent de rien conclure. Il faut les quatre
autres championnats, et les saisons 2020/21 à 2022/23.

Piste établie le 08/09/2026 : football-data.co.uk reste bloqué, mais **GitHub
est accessible** et des miroirs existent. Celui qui a servi
(`jokecamp/FootballData`) s'arrête en janvier 2021 et n'a de structure par
saison que pour l'Angleterre ; les autres pays y sont en fichiers numérotés,
dont la saison se déduit des dates. Toute source retenue doit être **croisée
avec Understat avant import**, comme les six saisons anglaises l'ont été
(2 254 matchs, zéro discordance).

### Ce qui reste à brancher
La calibration a été appliquée **à la main** : `models/calibration.py` n'est
toujours pas dans le chemin du pipeline, pas plus que
`evaluation/pricing.py`. Trois modules corrects et non raccordés, c'est un
motif — à traiter comme tel.

### L'ancienne question, résolue
**Pourquoi l'edge était-il anti-corrélé.** C'est la question qui bloque
tout le reste : un moteur dont la sélection dégrade le rendement ne peut ni
publier de coupons (D-06), ni justifier une couche supplémentaire.

Trois pistes, par ordre de coût :
1. **Calibrer** avant de calculer l'edge. `models/calibration.py` existe et
   n'est pas dans le chemin. Le modèle sous-estime les événements peu probables
   et surestime les probables : l'edge hérite de ce biais, et le sélectionner
   revient à parier sur l'erreur de calibration. Une saison de validation
   distincte existe désormais (2023/24).
2. **Brancher `evaluation/pricing.py`** dans le pipeline, pour que le prix et
   l'edge cessent d'être un calcul manuel.
3. **Compléter le corpus** : 2020/21, 2021/22 et 2022/23 manquent, et les quatre
   autres championnats aussi. Le rendement n'est mesuré que sur 380 matchs — à
   ce volume, un ROI de −5,9 % n'est pas distinguable de −2 % ni de −10 %.

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
