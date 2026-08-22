"""Configuration des championnats."""

LEAGUE_CONFIG = {
    "E0": {
        "name": "Premier League",
        "country": "England",
        "seasons_available": ["1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324"],
    },
    "SP1": {
        "name": "La Liga",
        "country": "Spain",
        "seasons_available": ["1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324"],
    },
    "I1": {
        "name": "Serie A",
        "country": "Italy",
        "seasons_available": ["1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324"],
    },
    "D1": {
        "name": "Bundesliga",
        "country": "Germany",
        "seasons_available": ["1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324"],
    },
    "F1": {
        "name": "Ligue 1",
        "country": "France",
        "seasons_available": ["1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324"],
    },
}


def get_league_codes() -> list[str]:
    """Retourner la liste des codes de championnats."""
    return list(LEAGUE_CONFIG.keys())


def get_league_name(code: str) -> str:
    """Retourner le nom du championnat."""
    return LEAGUE_CONFIG.get(code, {}).get("name", code)
