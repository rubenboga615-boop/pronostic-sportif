"""Calcul des variables de forme (5 et 10 derniers matchs)."""

import pandas as pd


def calculate_form_points(results: pd.Series, window: int = 5) -> pd.Series:
    """Calculer les points de forme sur une fenêtre donnée.

    Résultat : W=3, D=1, L=0
    """
    points_map = {"W": 3, "D": 1, "L": 0}
    points = results.map(points_map)
    return points.rolling(window, min_periods=max(1, window // 2)).sum()


def calculate_form_features(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    windows: list[int] = [5, 10],
) -> dict:
    """Calculer les features de forme pour une équipe avant un match donné.

    ⚠️ Anti-fuite : seuls les matchs AVANT match_date sont utilisés.
    """
    team_matches = matches_df[
        ((matches_df["home_team_id"] == team_id) | (matches_df["away_team_id"] == team_id))
        & (matches_df["match_date"] < match_date)
    ].sort_values("match_date")

    if team_matches.empty:
        return {}

    features = {}
    for window in windows:
        recent = team_matches.tail(window)
        if len(recent) < max(1, window // 2):
            continue

        # Points
        points = 0
        wins = draws = losses = 0
        gf = ga = 0
        clean_sheets = 0

        for _, match in recent.iterrows():
            is_home = match["home_team_id"] == team_id
            mgf = match["home_goals"] if is_home else match["away_goals"]
            mga = match["away_goals"] if is_home else match["home_goals"]

            if pd.isna(mgf) or pd.isna(mga):
                continue

            mgf, mga = int(mgf), int(mga)
            gf += mgf
            ga += mga

            if mgf > mga:
                points += 3
                wins += 1
            elif mgf == mga:
                points += 1
                draws += 1
            else:
                losses += 1

            if mga == 0:
                clean_sheets += 1

        n = max(len(recent), 1)
        features[f"form_points_{window}"] = points
        features[f"form_wins_{window}"] = wins
        features[f"form_draws_{window}"] = draws
        features[f"form_losses_{window}"] = losses
        features[f"goals_for_avg_{window}"] = gf / n
        features[f"goals_against_avg_{window}"] = ga / n
        features[f"clean_sheets_{window}"] = clean_sheets

    return features
