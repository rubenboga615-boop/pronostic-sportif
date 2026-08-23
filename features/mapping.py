"""Mapping explicite entre les sorties des modules de features et les colonnes
du modèle ORM ``Feature``.

Chaque module de ``features/*.py`` renvoie un dictionnaire de clés « libres ».
Le modèle ``app.models.Feature``, lui, définit un schéma de colonnes précis. Ce
module centralise la correspondance pour éviter les dérives et rendre auditable
ce qui est réellement persisté.

Règle générale :
- une valeur calculée est reportée telle quelle ;
- une valeur **indisponible** (source absente) est ``None`` et NE doit JAMAIS
  être remplacée par une valeur plausible (ex. 0.0) ;
- une sortie **non stockable** (aucune colonne correspondante) est simplement
  ignorée, mais listée dans ``UNMAPPED_KEYS`` pour visibilité.
"""

from __future__ import annotations

from typing import Any


# Correspondance directe : clé produite par un module -> colonne du modèle.
DIRECT_MAPPING: dict[str, str] = {
    # form.py
    "form_points_5": "form_points_5",
    "form_points_10": "form_points_10",
    "goals_for_avg_5": "goals_for_avg_5",
    "goals_against_avg_5": "goals_against_avg_5",
    # goals.py (mêmes colonnes, redondance assumée)
    "avg_goals_for": "goals_for_avg_5",
    "avg_goals_against": "goals_against_avg_5",
    # shots.py
    "shots_avg_5": "shots_avg_5",
    "shots_on_target_avg_5": "shots_on_target_avg_5",
    # xg.py (indisponible tant que xg_match_stats est vide)
    "xg_avg_5": "xg_avg_5",
    "xga_avg_5": "xga_avg_5",
    "npxg_avg_5": "npxg_avg_5",
    # odds_movement.py (marché "1N2")
    "odds_movement": "odds_movement",
    # standings.py
    "league_position": "league_position",
    # injuries.py (indisponible tant que availability est vide)
    "injury_impact": "injury_impact",
}

# Sorties produites par les modules mais sans colonne dédiée dans Feature.
# Elles ne sont pas persistées en l'état (candidats à une évolution du schéma).
UNMAPPED_KEYS: set[str] = {
    "form_wins_5", "form_wins_10",
    "form_draws_5", "form_draws_10",
    "form_losses_5", "form_losses_10",
    "clean_sheets_5", "clean_sheets_10",
    "total_goals_for", "total_goals_against",
    "max_goals_for", "min_goals_for",
    "goals_for_avg_10", "goals_against_avg_10",
    "home_goals_for_avg", "home_goals_against_avg",
    "away_goals_for_avg", "away_goals_against_avg",
    "home_rest_days", "away_rest_days", "rest_days_difference",
    "comparable_teams", "opponent_elo_avg_5",
}

# NOTE : le modèle Feature ne dispose pas de colonnes de fenêtre 10 pour les
# moyennes de buts. Les clés ``*_10`` sont donc dans UNMAPPED_KEYS (ignorées).
# À revoir si le schéma ajoute des colonnes dédiées.


def map_features_to_columns(raw_features: dict[str, Any]) -> dict[str, Any]:
    """Convertir les sorties brutes des modules en un dictionnaire aligné sur
    les colonnes de ``Feature``.

    Args:
        raw_features: dict plat regroupant les sorties des modules de features.

    Returns:
        dict dont les clés sont des colonnes du modèle ``Feature``. Les colonnes
        sans source disponible valent ``None``.
    """
    mapped: dict[str, Any] = {}

    for key, column in DIRECT_MAPPING.items():
        if key in raw_features and raw_features[key] is not None:
            mapped[column] = raw_features[key]

    # Colonnes du modèle sans correspondance directe : explicitement None
    # (jamais remplacées par une valeur valide par défaut).
    for column in (
        "xg_avg_5",
        "xga_avg_5",
        "npxg_avg_5",
        "injury_impact",
        "opponent_strength",
        "goal_difference",
        "elo_rating",
        "rest_days",
        "data_completeness",
    ):
        mapped.setdefault(column, None)

    return mapped


def unconfigured_columns(mapped: dict[str, Any]) -> set[str]:
    """Retourner les colonnes restées à ``None`` après mapping (à inspecter)."""
    return {k for k, v in mapped.items() if v is None}
