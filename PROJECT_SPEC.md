# PROJECT_SPEC.md — Cahier des charges complet

> Version : 1.0 — 22 août 2026

## Règle de référence du projet

Ce fichier est la spécification principale du projet.

Avant toute modification importante, l'agent doit :

1. Lire PROJECT_SPEC.md
2. Vérifier que la modification respecte la Phase actuelle
3. Ne pas activer les marchés de Phase 2 sans validation explicite
4. Ne pas supprimer une source ou une table sans justification
5. Mettre à jour la documentation si l'architecture change
6. Ajouter ou modifier les tests correspondants

---

## Objectif du projet

Construire une application de pronostic football couvrant :

- Premier League
- La Liga
- Serie A
- Bundesliga
- Ligue 1

La première version doit prévoir uniquement les marchés suivants :

### Match entier

- 1N2
- Double chance
- Over/Under 0,5, 1,5, 2,5 et 3,5 buts
- BTTS (Both Teams To Score)
- Mi-temps la plus prolifique

### Première mi-temps

- 1N2
- Double chance
- Over/Under
- BTTS exclu de la première version

### Phase ultérieure (désactivée)

- Handicaps asiatiques et européens
- Scores exacts
- HT/FT
- Premier buteur
- Façon de marquer
- Pénalty accordé ou non

---

## Principe du moteur

Ne crée pas un modèle indépendant pour chaque marché. Construis d'abord un **moteur de buts** qui estime :

```text
lambda_home = buts attendus de l'équipe à domicile
lambda_away = buts attendus de l'équipe à l'extérieur
```

À partir de ces deux valeurs, génère une matrice de scores probables :

```text
0-0, 0-1, 0-2, ...
1-0, 1-1, 1-2, ...
2-0, 2-1, 2-2, ...
```

Les autres marchés seront dérivés de cette matrice :

- **1N2** : comparaison des buts domicile/extérieur
- **Double chance** : addition des probabilités correspondantes
- **Over/Under** : somme des scores selon le total de buts
- **BTTS** : somme des scores où les deux équipes marquent
- **Score exact** : probabilité de chaque cellule
- **Handicap** : comparaison de l'écart de buts
- **HT/FT** : combinaison de la matrice de première mi-temps et de la matrice finale

Pour le modèle initial, utilise un modèle de Poisson, puis teste Dixon-Coles pour mieux traiter les petits scores comme 0-0, 1-0 et 1-1.

---

## Sources de données

### Football-Data.co.uk

Source historique principale :

- Résultats
- Buts
- Résultats à la mi-temps
- Tirs et tirs cadrés lorsque disponibles
- Corners, fautes, cartons et autres statistiques selon les colonnes
- Cotes de plusieurs bookmakers
- Cotes de clôture pour certaines sources et saisons

Les fichiers sont disponibles en CSV/Excel et sont mis à jour au moins deux fois par semaine. Les cotes sont généralement collectées avant la clôture.

Limites :

- Pas de blessures structurées
- Pas de xG natif fiable
- Pas de suivi minute par minute des cotes
- Certaines colonnes changent selon la saison
- Les tirs de Serie A présentent une rupture de cohérence depuis 2018/19

### Understat

Source spécialisée pour :

- xG, xGA, NPxG, xA
- Tirs détaillés
- Qualité et position des tirs
- Données équipe et joueur

Understat couvre les cinq grands championnats avec une profondeur historique depuis 2014/15.

Limites :

- Pas une API commerciale officielle
- Les collecteurs peuvent casser si le site change
- La collecte doit être limitée et mise en cache
- Les conditions d'utilisation doivent être vérifiées
- Il faut conserver localement les données récupérées

### API-Football

Source opérationnelle pour :

- Calendriers et matchs à venir
- Classements
- Statistiques de matchs
- Événements
- Compositions
- Blessures, suspensions, absences
- Cotes disponibles
- Confrontations directes

Le plan gratuit est limité à 100 requêtes par jour. Utiliser API-Football pour les informations récentes, pas comme base historique principale.

### The Odds API

Complément pour les cotes actuelles. Le forfait gratuit est limité à 500 crédits mensuels. Ne pas interroger pour tous les marchés de tous les matchs. Sélectionner les matchs et conserver les snapshots.

---

## Arborescence du projet

```text
pronostic-sportif/
├── .agents/
│   └── skills/
│       └── football-pronostic/
│           ├── SKILL.md
│           ├── references/
│           │   ├── data-sources.md
│           │   ├── markets.md
│           │   └── validation.md
│           └── scripts/
│               └── validate_data.py
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── logging_config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── dependencies.py
│   └── routes/
│       ├── __init__.py
│       ├── health.py
│       ├── matches.py
│       ├── predictions.py
│       ├── sources.py
│       └── admin.py
├── collectors/
│   ├── __init__.py
│   ├── football_data/
│   │   ├── __init__.py
│   │   ├── downloader.py
│   │   ├── parser.py
│   │   └── league_config.py
│   ├── understat/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── parser.py
│   │   └── rate_limiter.py
│   ├── api_football/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── endpoints.py
│   │   └── quota.py
│   └── odds/
│       ├── __init__.py
│       ├── client.py
│       └── snapshots.py
├── data/
│   ├── raw/
│   │   ├── football_data/
│   │   ├── understat/
│   │   ├── api_football/
│   │   └── odds/
│   ├── cleaned/
│   ├── features/
│   ├── exports/
│   └── backups/
├── database/
│   ├── migrations/
│   └── seed/
├── features/
│   ├── __init__.py
│   ├── form.py
│   ├── home_away.py
│   ├── goals.py
│   ├── xg.py
│   ├── shots.py
│   ├── standings.py
│   ├── elo.py
│   ├── rest_days.py
│   ├── injuries.py
│   ├── odds_movement.py
│   └── comparable_teams.py
├── models/
│   ├── __init__.py
│   ├── poisson.py
│   ├── dixon_coles.py
│   ├── first_half.py
│   ├── market_derivation.py
│   ├── calibration.py
│   └── model_registry.py
├── evaluation/
│   ├── __init__.py
│   ├── backtest.py
│   ├── metrics.py
│   ├── calibration_report.py
│   ├── roi_simulation.py
│   └── reports.py
├── pipelines/
│   ├── __init__.py
│   ├── historical_import.py
│   ├── daily_update.py
│   ├── feature_pipeline.py
│   ├── prediction_pipeline.py
│   └── validation_pipeline.py
├── dashboard/
│   ├── streamlit_app.py
│   ├── pages/
│   └── components/
├── tests/
│   ├── __init__.py
│   ├── test_parsers.py
│   ├── test_features.py
│   ├── test_models.py
│   ├── test_markets.py
│   ├── test_no_data_leakage.py
│   └── test_collectors.py
├── scripts/
│   ├── import_historical_data.py
│   ├── collect_daily.py
│   ├── train_models.py
│   ├── generate_predictions.py
│   └── create_backup.py
├── PROJECT_SPEC.md
├── knowledge.md
├── CHANGELOG.md
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pyproject.toml
└── Makefile
```

---

## Tables de base de données

### `competitions`

```text
id
name
country
provider_code
active
created_at
```

Exemples de codes :

```text
E0   Premier League
SP1  La Liga
I1   Serie A
D1   Bundesliga
F1   Ligue 1
```

### `seasons`

```text
id
competition_id
season_name
start_date
end_date
status
```

### `teams`

```text
id
canonical_name
country
provider
provider_team_id
active
```

### `matches`

```text
id
provider
provider_match_id
competition_id
season_id
match_date
home_team_id
away_team_id
status
home_goals
away_goals
home_ht_goals
away_ht_goals
home_shots
away_shots
home_shots_on_target
away_shots_on_target
source_created_at
source_updated_at
```

### `team_match_stats`

```text
id
match_id
team_id
shots
shots_on_target
shots_off_target
corners
fouls
yellow_cards
red_cards
possession
passes
accurate_passes
source
quality_status
```

### `xg_match_stats`

```text
id
match_id
team_id
xg
xga
npxg
xa
shots
source
retrieved_at
quality_status
```

### `availability`

```text
id
match_id
team_id
player_id
player_name
status
reason
confirmed
source
retrieved_at
```

Les valeurs `unknown`, `confirmed_absence` et `available` doivent être différentes. Une absence d'information ne doit jamais être interprétée comme une absence de blessure.

### `odds_snapshots`

```text
id
match_id
bookmaker
market
selection
odds
captured_at
is_closing
source
```

### `features`

```text
id
match_id
team_id
calculated_at
form_points_5
form_points_10
goals_for_avg_5
goals_against_avg_5
home_away_goals_for_avg
home_away_goals_against_avg
xg_avg_5
xga_avg_5
npxg_avg_5
shots_avg_5
shots_on_target_avg_5
league_position
goal_difference
elo_rating
opponent_strength
rest_days
injury_impact
odds_movement
data_completeness
```

### `predictions`

```text
id
match_id
model_version
generated_at
market
selection
probability
fair_odds
offered_odds
edge
confidence
data_quality
status
```

### `actual_results`

```text
id
match_id
market
selection
actual_outcome
settled_at
```

### `source_health`

```text
source
last_success_at
last_attempt_at
last_error
records_last_run
status
quota_remaining
```

Statuts possibles : `healthy`, `degraded`, `failed`, `stale`

---

## Règle anti-fuite de données

C'est l'une des parties les plus importantes du projet.

Pour un match du 15 septembre, les variables doivent être calculées seulement avec :

- Les matchs antérieurs au 15 septembre
- Les blessures connues avant l'heure de génération
- Les cotes capturées avant la prédiction
- Le classement disponible au moment de la prédiction

Les statistiques du match lui-même, les cotes de clôture et les événements futurs ne doivent pas entrer dans les variables prédictives.

Exemple correct :

```python
features = (
    matches.sort_values("match_date")
    .groupby("team_id")["goals_for"]
    .transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
)
```

Le test `test_no_data_leakage.py` doit vérifier automatiquement qu'aucune date de donnée utilisée n'est postérieure à la date de prédiction.

---

## Variables à calculer

### Forme

```text
points_5, points_10
wins_5, draws_5, losses_5
goals_for_5, goals_against_5
clean_sheets_5
```

### Domicile et extérieur

Pour l'équipe à domicile :

```text
home_goals_for_avg, home_goals_against_avg
home_xg_avg, home_xga_avg
```

Pour l'équipe extérieure :

```text
away_goals_for_avg, away_goals_against_avg
away_xg_avg, away_xga_avg
```

### Force des adversaires

Classement Elo :

```text
elo_expected = 1 / (1 + 10 ** ((elo_away - elo_home) / 400))
elo_update = K * (actual_result - elo_expected)
```

Ajouter ensuite :

```text
opponent_elo_avg_5
opponent_elo_avg_10
```

### Jours de repos

```text
home_rest_days
away_rest_days
rest_days_difference
```

### Blessures

Impact pondéré :

```text
injury_impact = somme(valeur_joueur × temps_de_jeu_attendu × importance_positionnelle)
```

Si la valeur du joueur n'est pas disponible, utiliser une pondération prudente basée sur les minutes jouées, le statut de titulaire et les buts/xG historiques.

### Cotes

Convertir les cotes en probabilités implicites :

```text
probabilite_brute = 1 / cote
```

Pour le 1N2, normaliser la marge :

```text
probabilite_normalisee = probabilite_brute / somme(probabilites_brutes)
```

Comparer ensuite :

```text
edge = probabilite_modele - probabilite_marche_normalisee
```

---

## Modèles de la Phase 1

### Modèle 1 : Poisson

Prévoir les buts domicile et extérieur.

### Modèle 2 : Dixon-Coles

Corriger mieux certains résultats bas, notamment :

- 0-0
- 1-0
- 0-1
- 1-1

### Modèle 3 : modèle machine learning

Tester ensuite :

- Régression logistique pour 1N2
- Random Forest comme référence
- XGBoost ou LightGBM si l'environnement le permet

Le modèle machine learning ne doit pas remplacer automatiquement le modèle de buts. Comparer les performances hors échantillon.

### Modèle première mi-temps

Utiliser les buts historiques `HTHG` et `HTAG`. Estimer séparément les buts attendus de la première mi-temps et de la seconde.

---

## Marchés à générer

Créer un module `market_derivation.py` avec des fonctions indépendantes :

```python
derive_1n2(score_matrix)
derive_double_chance(probabilities_1n2)
derive_over_under(score_matrix, line)
derive_btts(score_matrix)
derive_first_half_markets(first_half_matrix)
derive_most_productive_half(first_half_matrix, second_half_matrix)
derive_asian_handicap(score_matrix, handicap)
```

Chaque fonction doit retourner :

```json
{
  "market": "over_under",
  "selection": "over_2.5",
  "probability": 0.61,
  "fair_odds": 1.64
}
```

La cote équitable est :

```text
fair_odds = 1 / probability
```

---

## Validation chronologique

Ne pas utiliser un découpage aléatoire classique. Utiliser une validation dans le temps :

```text
Chauffe       : saison 2014/15            (importée, exclue de l'entraînement)
Entraînement  : saisons 2015/16 à 2022/23  (8 saisons, ~14 500 matchs)
Validation    : saison 2023/24             (calibration, réglage de ξ)
Test          : saisons 2024/25 et 2025/26 (~1 300 matchs, jamais touchées)
```

Ce découpage remplace celui de la rédaction initiale (entraînement 2015/16 à
2021/22, validation 2022/23, test 2023/24), écrit quand 2023/24 était la
dernière saison terminée. Il a été décalé de deux saisons en septembre 2026.

Trois raisons de le fixer ainsi :

- **La saison de chauffe.** Elo, forme et classement démarrent à froid. Sans
  saison antérieure, la première saison d'entraînement est la plus mal décrite
  de toutes. 2014/15 est importée pour cela, et pour cela seulement.
- **Deux saisons de test, pas une.** Sur 380 matchs, l'intervalle de confiance
  d'un rendement simulé couvre plusieurs points : un ROI de −3 % n'y est
  distinguable ni de 0 %, ni de −8 %. Doubler l'échantillon de test resserre la
  mesure bien plus sûrement qu'ajouter une saison à un entraînement qui en
  compte déjà huit — la pondération temporelle du Dixon-Coles, de demi-vie
  proche d'un an, ne « voit » de toute façon que les dernières saisons.
- **Une saison de validation distincte.** Elle est la condition d'existence de
  la calibration : ajuster un calibrateur sur le jeu de test reviendrait à se
  noter sur ses propres réponses. C'est ce qui manquait jusqu'ici.

Une fois le protocole passé et les métriques publiées, le modèle **de
production** se réentraîne sur toutes les saisons disponibles, jusqu'au dernier
match joué. Le découpage sert à mesurer, pas à brider.

Les saisons exactes devront être ajustées selon la disponibilité des données —
en décalant l'ensemble, jamais en empiétant sur le test.

Pour la saison en cours, ne pas l'utiliser pour déclarer la rentabilité du modèle avant qu'elle soit terminée.

---

## Métriques obligatoires

Pour chaque marché, calculer :

- Nombre de matchs
- Accuracy
- Log loss
- Brier score
- Courbe de calibration
- AUC lorsque pertinent
- Rendement simulé
- ROI
- Drawdown maximal
- Nombre de paris simulés
- Résultat par championnat
- Résultat par saison
- Résultat par tranche de cote

Ne jamais présenter uniquement l'accuracy.

---

## Gestion des données pendant 12 mois

### Collecte historique (à faire une fois)

```text
download_historical_data → validate_files → normalize_columns
→ deduplicate_matches → load_database
```

### Collecte quotidienne (1-2 fois par jour)

```text
download_new_csvs → collect_upcoming_fixtures
→ collect_recent_results → collect_available_injuries
→ collect_selected_odds → validate_sources
→ generate_predictions → create_backup
```

### Collecte avant match (48h)

- Actualiser les blessures
- Actualiser les compositions disponibles
- Capturer les cotes
- Recalculer les variables
- Générer une nouvelle version de prédiction
- Conserver l'ancienne prédiction

Chaque prédiction doit avoir :

```text
generated_at
model_version
data_cutoff_at
source_versions
```

---

## Protection contre les pannes

Le pipeline doit :

- Réessayer les requêtes échouées
- Respecter les limites de chaque fournisseur
- Mettre en cache les réponses
- Ne pas supprimer les anciennes données en cas de réponse vide
- Détecter les changements de colonnes CSV
- Vérifier les doublons
- Vérifier les matchs sans score
- Vérifier les cotes nulles ou négatives
- Marquer les données anciennes
- Créer une sauvegarde quotidienne
- Envoyer une alerte en cas d'échec

---

## Calendrier de développement (2 mois)

### Semaine 1 : fondations

- Créer le dépôt
- Créer l'environnement Python
- Ajouter `.env.example`
- Ajouter SQLite
- Ajouter Docker
- Créer les tables
- Ajouter les logs
- Ajouter les tests de base

### Semaine 2 : import historique

- Télécharger les CSV des cinq championnats
- Normaliser les noms d'équipes
- Normaliser les dates
- Charger les résultats finaux et mi-temps
- Ajouter la déduplication
- Produire un rapport de qualité

### Semaine 3 : statistiques

- Forme 5 et 10 matchs
- Domicile/extérieur
- Buts pour/contre
- Classement historique
- Jours de repos
- Elo
- Force des adversaires

### Semaine 4 : moteur de buts

- Poisson
- Dixon-Coles
- Matrice des scores
- 1N2
- Double chance
- Over/Under
- BTTS

### Semaine 5 : xG et première mi-temps

- Collecte Understat
- Normalisation des équipes
- xG/xGA
- Modèle première mi-temps
- Mi-temps la plus prolifique
- Tests anti-fuite

### Semaine 6 : API-Football et cotes

- Calendrier futur
- Statistiques récentes
- Blessures
- Suspensions
- Cotes ciblées
- Cache
- Suivi du quota

### Semaine 7 : évaluation

- Backtest chronologique
- Brier score
- Log loss
- Calibration
- ROI simulé
- Analyse par championnat

### Semaine 8 : interface et automatisation

- Dashboard
- Historique des prédictions
- Score de qualité des données
- Pipeline quotidien
- Sauvegardes
- Alertes
- Documentation de déploiement

---

## Définition de réussite de la première année

À la fin de l'année, pouvoir répondre objectivement à ces questions :

- Combien de matchs ont été prédits ?
- Quelle est la performance par marché ?
- Le modèle est-il calibré ?
- Les résultats sont-ils stables par championnat ?
- Les résultats restent-ils positifs avec les cotes de clôture ?
- Quelle est la performance sans Understat ?
- Quelle est la performance sans blessures ?
- Quelle est la performance avec le marché comme référence ?
- Combien de données étaient manquantes ?
- Combien de jours le pipeline a-t-il échoué ?
- Le modèle est-il meilleur qu'une stratégie naïve ?

Le livrable de première année comprend :

```text
application fonctionnelle
base de données historique
pipeline automatisé
journal des sources
modèles versionnés
rapports de backtest
historique de prédictions réelles
rapport de stabilité
documentation complète
```

---

## Propositions en attente

```markdown
- Nouvelle variable :
- Source nécessaire :
- Risque de fuite :
- Tests requis :
- Décision :
```
