# État actuel du projet

> Fichier de référence à lire en premier. Tenir à jour après chaque session.
> Dernière mise à jour : 2026-09-08.

## Projet
Moteur de pronostic football (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).

## État Git
- Branche : `claude/audit-lecture-seule-s5yd7b`
- Working tree : **propre**
- Suite de tests : **589 réussis, 0 ignoré** (scikit-learn installé : les
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

## Corpus au 08/09/2026 — 17 251 matchs, cinq championnats

football-data.co.uk restant injoignable (503), les CSV viennent de **trois
miroirs GitHub indépendants** : `jokecamp/FootballData`,
`nemesistip-cloud/vit` et `wlrwx/football-engine`. Le fichier `E0_1920.csv`
commun aux deux premiers a le **même MD5** — ils recopient la même source, bit
à bit.

Authenticité vérifiée par croisement avec Understat **avant chaque import** :
plus de **13 000 matchs comparés, zéro discordance de score**.

| | 07/09 | 08/09 |
|---|---|---|
| Matchs | 1 140 | **17 251** |
| Cotes | 9 285 | **363 372** |
| Lignes de xG | 878 | **28 004** |
| Équipes | 23 | **156** |

| Championnat | Saisons | Matchs | Période |
|---|---|---|---|
| Premier League | **12** | 4 560 | 2014/15 → 2025/26 |
| La Liga | 9 | 3 420 | 2017/18 → 2025/26 |
| Serie A | 9 | 3 420 | 2017/18 → 2025/26 |
| Ligue 1 | 9 | 3 097 | 2017/18 → 2025/26 |
| Bundesliga | 9 | 2 754 | 2017/18 → 2025/26 |

Le corpus visé par la feuille de route (~19 900 matchs) est atteint à 87 %, et
**les cinq championnats sont désormais entraînables** — c'était la limite
bloquante de la veille. Le jeu de test compte **3 124 matchs avec cotes**, soit
environ 9 400 paris : au-delà du seuil de 2 200 nécessaire pour établir un ROI
de +5 %.

Les structures reflètent l'histoire réelle et non un remplissage : Ligue 1 à
279 matchs en 2019/20 (saison écourtée par le COVID), passage à 18 clubs en
2023/24, Bundesliga à 306 matchs depuis toujours.

## Protocole D-02 exécuté pour la première fois

Enfin conforme : chauffe 2014/15, **entraînement 2015/16 → 2022/23** (3 420
matchs), **validation 2023/24** (380), **test 2024/25 + 2025/26** (760).
Calibration ajustée sur la validation, appliquée au test par le pipeline.
Rendement contre les **cotes de clôture**.

### Premier League — le seul championnat que le modèle a appris

| Marché | Accuracy | AUC | Err. calibr. | ROI | paris |
|---|---|---|---|---|---|
| 1N2 | 0,467 | 0,638 | 0,067 | **−2,87 %** | 1 140 |
| Over/Under | 0,741 | 0,752 | 0,014 | **−1,83 %** | 760 |
| Over/Under 1re MT | 0,756 | **0,773** | 0,041 | — | — |
| 1N2 1re mi-temps | 0,443 | 0,620 | 0,033 | — | — |
| Mi-temps prolifique | 0,439 | 0,612 | 0,012 | — | — |
| BTTS | 0,526 | 0,518 | 0,005 | — | — |

| Stratégie | Paris | ROI |
|---|---|---|
| `edge ≥ 2 %` | 713 | −8,20 % |
| `edge ≥ 5 %` | 529 | **−15,40 %** |
| Naïf domicile | 380 | −16,28 % |
| **Favori du marché** | 380 | **−0,88 %** |

**Le moteur ne bat pas le marché.** Il perd 2,87 % sur le 1N2 et 1,83 % sur
l'Over/Under, là où suivre le favori du marché ne coûte que 0,88 %. Et la
sélection par edge reste contre-productive sur ce modèle : plus le seuil monte,
plus le rendement baisse.

### Mieux calibrer n'améliore pas le rendement du 1N2

La piste de la fenêtre glissante a été implémentée et mesurée
(`models/calibration_glissante.py`, calibrateur réajusté à chaque journée sur
le seul passé connu). Elle tient sa promesse **sur la calibration**, et pas du
tout **sur le rendement** :

| Probabilités | err. calibr. | ROI `edge ≥ 5 %` |
|---|---|---|
| brutes | 0,0592 | −21,78 % |
| figée (2023/24) | 0,0597 | −21,23 % |
| glissante, fenêtre croissante | **0,0346** | −22,55 % |
| glissante, 2 000 observations | **0,0339** | −23,05 % |

L'erreur de calibration baisse de 41 %, et le rendement ne bouge pas — il
empire même légèrement. **Sur le 1N2, le problème n'était donc pas la
calibration.** Mieux calibrer rapproche les probabilités du modèle de la
vérité, mais celles du marché en sont déjà plus proches : l'écart résiduel est
du bruit, et le sélectionner coûte la marge du bookmaker.

Sur l'Over/Under en revanche, la calibration change le signe — et une simple
calibration figée y suffit :

| Probabilités | err. calibr. | ROI `edge ≥ 5 %` |
|---|---|---|
| brutes | 0,0387 | −5,35 % |
| figée (2023/24) | 0,0217 | **+3,97 %** |
| glissante | 0,0205 | +3,17 % |

### Le premier résultat statistiquement établi du projet, et il est négatif

Intervalles de confiance à 95 % par bootstrap, sur le jeu de test :

| Marché | seuil | paris | ROI | IC 95 % | verdict |
|---|---|---|---|---|---|
| 1N2 | ≥ 5 % | 301 | −21,23 % | [−37,95 ; **−2,10**] | **négatif, démontré** |
| 1N2 | ≥ 2 % | 416 | −13,68 % | [−29,01 ; +2,85] | nul |
| Over/Under | ≥ 5 % | 259 | +3,97 % | [−11,36 ; +19,74] | nul |
| Over/Under | ≥ 2 % | 332 | +2,07 % | [−11,41 ; +15,55] | nul |

**Sélectionner sur l'edge du 1N2 fait perdre de l'argent, et ce n'est plus une
impression.** C'est la première conclusion que ce projet peut défendre. Elle
ferme une porte : quel que soit le générateur de coupons à venir, il ne devra
pas retenir de sélection 1N2 sur ce critère.

L'Over/Under garde un signe positif constant sur tous les seuils, mais reste
indéterminé faute de volume.

### ⚠️ Les quatre autres championnats ne sont pas mesurables
`train_models.py` entraîne **par compétition**, et la Liga, la Serie A, la
Bundesliga et la Ligue 1 n'ont que 2024/25 en base — aucun match avant la
coupure d'entraînement. Leurs 1 372 matchs ont donc été prédits avec un modèle
appris sur la **Premier League**, dont les forces d'équipes ne les décrivent
pas. Un backtest tous championnats confondus affiche 2 982 paris et −5,72 % :
**ce chiffre ne veut rien dire** et n'est pas retenu. Il faudra au moins trois
saisons par championnat avant de les mesurer.

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
**Compléter les quatre autres championnats** — il leur faut au moins trois
saisons chacun pour être entraînables, donc mesurables. Sources : les deux
miroirs déjà utilisés ne portent que 2024/25 pour eux ; il en faut d'autres, et
tout candidat doit être croisé avec Understat avant import.

**Puis reprendre la calibration.** Son erreur passe de 0,012 en validation à
0,067 en test : apprise sur une saison, elle ne se transporte pas. Une fenêtre
glissante, ou un calibrateur réajusté à chaque journée, corrigerait sans doute
ce que la sélection par edge perd aujourd'hui.

### L'ancienne action, faite
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

### Le pipeline fait désormais les trois étapes lui-même
Les trois modules orphelins sont raccordés. `run_prediction_pipeline` enchaîne
contexte anti-fuite → **calibration** → **valorisation**, sans script manuel.

- La calibration s'applique **avant** la persistance : D-10 interdit de
  retoucher une probabilité écrite, et une probabilité corrigée après coup ne
  serait plus celle qui a servi à calculer l'edge.
- Un calibrateur **par marché**, et les groupes exclusifs sont renormalisés —
  la calibration déforme chaque probabilité isolément, si bien qu'un 1N2 cesse
  de sommer à 1, ce qui fausserait l'edge sans lever d'erreur.
- `scripts/ajuster_calibration.py` enregistre les calibrateurs dans le registre,
  à la version du modèle : la calibration est versionnée et rejouable.

Effet mesuré **en passant par le pipeline seul**, sur le jeu de test :

| Stratégie | Avant | Après |
|---|---|---|
| `edge ≥ 5 %` | −17,49 % | **−6,27 %** (634 paris) |
| `edge ≥ 2 %` | −14,18 % | **−5,86 %** (858 paris) |
| Favori du marché | −2,06 % | −0,88 % |
| Naïf domicile | −18,35 % | −16,28 % |

Le moteur ne bat toujours pas le marché, mais sa sélection a cessé de nuire.

### Un défaut de mesure corrigé
`charger_evaluation` chargeait toutes les prédictions d'une version, y compris
celles de sa **saison de calibration** : le modèle était donc partiellement noté
sur les données qui avaient servi à le corriger. Le paramètre `saisons` restreint
désormais le chargement, et les chiffres ci-dessus portent sur le seul jeu de
test.

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
