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

- **Football-Data.co.uk** : historique, résultats HT/FT, statistiques et cotes historiques
- **Understat** : xG, xGA, NPxG, xA et tirs
- **API-Football** : calendriers, classements, événements, statistiques, blessures et cotes disponibles
- **The Odds API** : complément de cotes actuelles

## Règles

- Aucune donnée future dans les features
- Données brutes conservées
- Cache obligatoire
- Quotas surveillés
- Données manquantes signalées
- Aucune garantie de gain
- Tests obligatoires avant chaque nouvelle fonctionnalité

## Stack technique

- Python 3.12
- FastAPI
- SQLite (au début)
- pandas, scikit-learn, statsmodels
- Streamlit (dashboard)
- Docker
