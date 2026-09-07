# Historique

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
