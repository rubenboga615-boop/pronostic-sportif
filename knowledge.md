# Contexte du projet

Nous construisons un moteur de pronostic football couvrant :

- Premier League
- La Liga
- Serie A
- Bundesliga
- Ligue 1

## Phase active

- 1N2 match entier
- Double chance
- Over/Under 0.5, 1.5, 2.5 et 3.5
- BTTS
- Mi-temps la plus prolifique
- 1N2 première mi-temps
- Double chance première mi-temps
- Over/Under première mi-temps

## Phase 2 désactivée

- Handicaps
- Scores exacts
- HT/FT
- Premier buteur
- Façon de marquer
- Pénalty

## Sources

- **Football-Data.co.uk** — historique, résultats HT/FT, statistiques et cotes
  historiques. *Écrite et testée.* 12 saisons configurées, 2014/15 → 2025/26.
- **API-Football** (plan Pro) — calendriers, matchs à venir, blessures,
  compositions, cotes pré-match. *À écrire, étape 7.* C'est la source de tout ce
  qui regarde vers l'avant.
- **Understat** — xG, xGA, NPxG, xA, xGChain, xGBuildup. *À écrire, étape 8.*
  Pas d'API officielle : les données sont incrustées dans les pages. Cache
  obligatoire, débit faible, réponses brutes conservées.
- **The Odds API** — repoussée. L'endpoint cotes d'API-Football couvre le besoin,
  et 500 crédits mensuels ne suffisent pas à un relevé régulier.

### Écartée

- **football-data.org** — service distinct de Football-Data.**co.uk** malgré la
  quasi-homonymie. Vraie API REST, mais **sans cotes de bookmakers** : l'edge, le
  rendement et toute la comparaison au marché en dépendent. Voir `docs/DECISIONS.md`, D-03.

## Règles

- Aucune donnée future dans les features
- Données brutes conservées
- Cache obligatoire
- Quotas surveillés
- Données manquantes signalées
- Aucune garantie de gain
- Tests obligatoires avant chaque nouvelle fonctionnalité
- **La probabilité du marché n'est jamais une variable d'entrée** du modèle : il
  apprendrait à recopier le bookmaker et l'edge tendrait vers zéro (D-04)
- **Dixon-Coles n'est pas remplacé par un gradient boosting** : seule la matrice
  de scores donne la loi jointe dont les coupons ont besoin (D-05)
- **Aucun coupon publié** tant que le rendement n'est pas positif sur les deux
  saisons de test (D-06)
- **Pas de montante dans le moteur** : une progression ne change pas
  l'espérance, seulement la variance (D-07)
- **L'IA rédige, elle ne juge pas** et ne calcule rien (D-08)
- **Personne ne modifie un chiffre à la main**, administrateur compris (D-10)

## Stack technique

- Python **3.11 minimum** (vérifié en intégration continue sur 3.11 et 3.12)
- FastAPI
- SQLite
- pandas, numpy, scipy, SQLAlchemy, loguru — **noyau**, sans extra
- scikit-learn, statsmodels — extra `ml`, requis seulement par la calibration
- Streamlit — extra `dashboard`
- Docker

Le noyau — import, features, entraînement, prédiction, règlement, backtest —
doit tourner sans aucun extra. Un job d'intégration continue le vérifie.

## Phase produit — conditionnée

Coupons, rédaction assistée et abonnements ne démarrent **que si** le rendement
du moteur est positif sur 2024/25 et 2025/26. Construits avant, ils ne feraient
que distribuer plus efficacement un produit non validé.

Détail dans `PROJECT_SPEC.md` (génération de coupons, couche de rédaction, rôles
et interfaces) et motifs dans `docs/DECISIONS.md`.
