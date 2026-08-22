"""Calcul des statistiques domicile/extérieur."""

import pandas as pd
from loguru import logger


def calculate_home_away_features(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    window: int = 10,
) -> dict:
    """Calculer les statistiques domicile/extérieur d'une équipe.
    
    ⚠️ Anti-fuite : seuls les matchs AVANT match_date sont utilisés.
    """
    # Matchs à domicile
    home_matches = matches_df[
        (matches_df["home_team_id"] == team_id)
        & (matches_df["match_date"] < match_date)
    ].sort_values("match_date").tail(window)

    # Matchs à l'extérieur
    away_matches = matches_df[
        (matches_df["away_team_id"] == team_id)
        & (matches_df["match_date"] < match_date)
    ].sort_values("match_date").tail(window)

    features = {}

    # Domicile
    if not home_matches.empty and len(home_matches) >= 3:
        home_gf = home_matches["home_goals"].dropna()
        home_ga = home_matches["away_goals"].dropna()
        features["home_goals_for_avg"] = home_gf.mean() if len(home_gf) > 0 else None
        features["home_goals_against_avg"] = home_ga.mean() if len(home_ga) > 0 else None
    else:
        features["home_goals_for_avg"] = None
        features["home_goals_against_avg"] = None

    # Extérieur
    if not away_matches.empty and len(away_matches) >= 3:
        away_gf = away_matches["away_goals"].dropna()
        away_ga = away_matches["home_goals"].dropna()
        features["away_goals_for_avg"] = away_gf.mean() if len(away_gf) > 0 else None
        features["away_goals_against_avg"] = away_ga.mean() if len(away_ga) > 0 else None
    else:
        features["away_goals_for_avg"] = None
        features["away_goals_against_avg"] = None

    return features
