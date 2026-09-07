# ⚽ Pronostic Sportif — Moteur de pronostic football

Moteur probabiliste de pronostic football couvrant les cinq grands championnats européens.

## Championnats

- 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League
- 🇪🇸 La Liga
- 🇮🇹 Serie A
- 🇩🇪 Bundesliga
- 🇫🇷 Ligue 1

## Marchés (Phase 1)

| Marché | Match entier | 1ère mi-temps |
|--------|:---:|:---:|
| 1N2 | ✅ | ✅ |
| Double chance | ✅ | ✅ |
| Over/Under | ✅ 0.5, 1.5, 2.5, 3.5 | ✅ 0.5, 1.5, 2.5 |
| BTTS | ✅ | ❌ hors périmètre |
| Mi-temps la plus prolifique | ✅ | — |

Soit **31 sélections par match**. Les marchés de mi-temps demandent des modèles
de mi-temps entraînés ; sans eux, ils ne sont pas produits plutôt que devinés.

## Stack technique

- **Python 3.12**
- **FastAPI** — API REST
- **SQLite** — base de données (au début)
- **pandas** — manipulation de données
- **scikit-learn / statsmodels** — modèles
- **Streamlit** — dashboard
- **Docker** — conteneurisation

## Installation

### 1. Cloner le dépôt

```bash
git clone <url-du-depot>
cd pronostic-sportif
```

### 2. Créer l'environnement

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 3. Configurer les variables d'environnement

```bash
cp .env.example .env
# Éditer .env avec vos clés API
```

### 4. Initialiser la base de données

```bash
python scripts/import_historical_data.py
```

### 5. Lancer l'application

```bash
# API
uvicorn app.main:app --reload

# Dashboard
streamlit run dashboard/streamlit_app.py
```

### 6. Docker (optionnel)

```bash
docker-compose up -d
```

## Structure du projet

```text
pronostic-sportif/
├── app/            # API FastAPI
├── collectors/     # Collecteurs de données
├── data/           # Données brutes, nettoyées, features
├── database/       # Migrations et seed
├── features/       # Calcul des variables prédictives
├── models/         # Moteur de buts et dérivation de marchés
├── evaluation/     # Backtest et métriques
├── pipelines/      # Pipelines automatisés
├── dashboard/      # Interface Streamlit
├── tests/          # Tests unitaires et anti-fuite
└── scripts/        # Scripts d'automatisation
```

## Sources de données

| Source | Usage | Statut |
|--------|-------|--------|
| Football-Data.co.uk | Résultats historiques, statistiques, cotes | **Écrite** — 12 saisons, 2014/15 → 2025/26 |
| API-Football | Calendriers, matchs à venir, blessures, cotes | À écrire (étape 7), plan Pro |
| Understat | xG, xGA, NPxG, xA | À écrire (étape 8), pas d'API officielle |
| The Odds API | Cotes actuelles | Repoussée — couverte par API-Football |
| ~~football-data.org~~ | — | **Écartée** : pas de cotes de bookmakers (D-03) |

## Tests

```bash
pytest tests/ -v
```

## Documentation

- [PROJECT_SPEC.md](PROJECT_SPEC.md) — Cahier des charges complet
- [knowledge.md](knowledge.md) — Contexte du projet
- [.agents/skills/football-pronostic/SKILL.md](.agents/skills/football-pronostic/SKILL.md) — Skill de développement

## Avertissement

⚠️ **Ce projet est un outil de recherche statistique. Il ne garantit aucun gain. Les probabilités produites sont des estimations, pas des certitudes. Le paris sportif comporte des risques.**

## License

MIT
