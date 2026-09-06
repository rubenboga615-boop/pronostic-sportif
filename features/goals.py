"""Calcul des statistiques de buts."""

import pandas as pd


def calculate_goals_features(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    window: int = 10,
) -> dict:
    """Calculer les statistiques de buts d'une équipe.

    ⚠️ Anti-fuite : seuls les matchs AVANT match_date sont utilisés.
    """
    team_matches = (
        matches_df[
            ((matches_df["home_team_id"] == team_id) | (matches_df["away_team_id"] == team_id))
            & (matches_df["match_date"] < match_date)
        ]
        .sort_values("match_date")
        .tail(window)
    )

    if team_matches.empty or len(team_matches) < 3:
        return {}

    gf_list = []
    ga_list = []

    for _, match in team_matches.iterrows():
        is_home = match["home_team_id"] == team_id
        gf = match["home_goals"] if is_home else match["away_goals"]
        ga = match["away_goals"] if is_home else match["home_goals"]

        if pd.notna(gf):
            gf_list.append(int(gf))
        if pd.notna(ga):
            ga_list.append(int(ga))

    if not gf_list:
        return {}

    return {
        "total_goals_for": sum(gf_list),
        "total_goals_against": sum(ga_list),
        "avg_goals_for": sum(gf_list) / len(gf_list),
        "avg_goals_against": sum(ga_list) / len(ga_list),
        "max_goals_for": max(gf_list),
        "min_goals_for": min(gf_list),
    }
