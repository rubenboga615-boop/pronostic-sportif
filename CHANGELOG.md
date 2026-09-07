# Historique

## 2026-09-07 - Étape 6 b : les calculs dérivés qui manquaient

- **Dix variables de première mi-temps** (`features/half_time.py`) — quinze
  des trente et une sélections d'un match y portent, et rien ne la décrivait.
  `HTHG`/`HTAG` étaient en base depuis le premier import ; seuls le transport
  et le calcul dérivé manquaient.
- **Encombrement du calendrier** — matchs sur 7 et 14 jours, écart de repos.
  Information absente des résultats passés, contrairement à la forme, à l'Elo
  et au classement, tous dérivés du même registre de buts.
- **`failed_to_score_5`** — pendant du clean sheet, autre moitié du BTTS.
- **Les quatre colonnes orphelines sont alimentées** : `home_away_goals_*` par
  côté, `opponent_strength` par l'Elo des adversaires récents,
  `data_completeness` par la part de colonnes renseignées.
- **L'AUC se mesure désormais par groupe exclusif.** Le BTTS à 0,537 passait
  pour un défaut face à l'over/under à 0,805 ; la simulation depuis un modèle
  parfait montre l'inverse — plafonds de 0,606 et 0,819 respectivement. La
  seconde mesure était flatteuse, gonflée par le mélange de quatre lignes de
  fréquences différentes. Aucun code n'était en cause.
- **Arbitre importé** — inutile en Phase 1, central en Phase 2, et perdu pour
  toujours si le fournisseur retire la colonne.
- **Les cinq migrations sont transactionnelles.** Un test de concordance
  migration/ORM entre au dépôt et trouve aussitôt que les quatre migrations
  existantes ne l'étaient pas — dont le purge d'`odds_movement`, qui
  interrompu entre ses deux `UPDATE` aurait laissé la base dans un état
  qu'aucune version du code ne sait interpréter.
- Suite : **429 réussis, 3 ignorés**.

## 2026-09-07 - Décisions produit et périmètre

- Corpus étendu à **12 saisons** (2014/15 → 2025/26), dont 2014/15 en saison de
  chauffe : importée, exclue de l'entraînement
- **Protocole de validation décalé de deux saisons** : entraînement 2015/16 →
  2022/23, validation 2023/24, test 2024/25 **et** 2025/26
- Journal des décisions créé : `docs/DECISIONS.md`, onze décisions motivées
- **football-data.org écarté** — pas de cotes de bookmakers
- **The Odds API repoussée** — l'endpoint cotes d'API-Football couvre le besoin
- Spécification de la **génération de coupons** : une sélection par match,
  calibration avant multiplication, edge contre la cote combinée offerte,
  publication conditionnée à un rendement positif mesuré
- **Montante écartée du moteur** ; mise fixe puis Kelly fractionnaire
- Spécification de la **couche de rédaction assistée** : elle rédige, ne juge
  pas, ne calcule rien ; vérification numérique des sorties ; repli sans IA
- Spécification des **quatre rôles** et de l'**interface d'administration** :
  neuf écrans, promotion et retour arrière de modèle, interrupteur d'arrêt,
  journal d'audit en ajout seul
- Interdit par construction : modifier une probabilité, une cote, un edge ou un
  résultat réglé depuis l'interface
- **Étape 6 b** ajoutée à la feuille de route : les calculs dérivés manquants,
  dont dix variables de mi-temps, sans aucune source nouvelle

## 2026-08-22 - Version 1.0

- Périmètre limité aux cinq grands championnats (PL, La Liga, Serie A, Bundesliga, Ligue 1)
- Phase 1 définie : 1N2, double chance, Over/Under, BTTS, mi-temps prolifique, marchés 1ère MT
- Phase 2 désactivée : handicaps, scores exacts, HT/FT, premier buteur, façon de marquer, pénalty
- Sources principales définies : Football-Data.co.uk, Understat, API-Football, The Odds API
- Architecture du projet établie (collectors, features, models, evaluation, pipelines, app, dashboard)
- Schéma de base de données défini (12 tables)
- Règles anti-fuite de données établies
- Métriques de validation obligatoires définies
- Calendrier de développement sur 2 mois planifié
- Ajout d'une Skill spécialisée pour Freebuff
- Ajout de fichiers de contexte (knowledge.md, references/)
- Ajout de règles de gestion des pannes et de tolérance aux erreurs

## Propositions en attente

```markdown
- Nouvelle variable :
- Source nécessaire :
- Risque de fuite :
- Tests requis :
- Décision :
```
