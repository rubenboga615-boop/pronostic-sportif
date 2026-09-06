"""Calcul des features de tirs."""

import pandas as pd


def calculate_shots_features(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    window: int = 5,
) -> dict:
    """Calculer les features de tirs pour une équipe.

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

    if team_matches.empty or len(team_matches) < 2:
        return {
            "shots_avg_5": None,
            "shots_on_target_avg_5": None,
        }

    shots_list = []
    sot_list = []

    for _, match in team_matches.iterrows():
        is_home = match["home_team_id"] == team_id
        shots_col = "home_shots" if is_home else "away_shots"
        sot_col = "home_shots_on_target" if is_home else "away_shots_on_target"

        if pd.notna(match.get(shots_col)):
            shots_list.append(int(match[shots_col]))
        if pd.notna(match.get(sot_col)):
            sot_list.append(int(match[sot_col]))

    return {
        "shots_avg_5": sum(shots_list) / len(shots_list) if shots_list else None,
        "shots_on_target_avg_5": sum(sot_list) / len(sot_list) if sot_list else None,
    }
