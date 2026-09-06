"""Calcul des features xG (Expected Goals)."""

import pandas as pd


def calculate_xg_features(
    xg_data: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    window: int = 5,
) -> dict:
    """Calculer les features xG pour une équipe.

    ⚠️ Anti-fuite : seuls les matchs AVANT match_date sont utilisés.
    """
    if xg_data.empty:
        return {}

    team_xg = (
        xg_data[(xg_data["team_id"] == team_id) & (xg_data["retrieved_at"] < match_date)]
        .sort_values("retrieved_at")
        .tail(window)
    )

    if team_xg.empty or len(team_xg) < 2:
        return {
            "xg_avg_5": None,
            "xga_avg_5": None,
            "npxg_avg_5": None,
        }

    return {
        "xg_avg_5": team_xg["xg"].mean(),
        "xga_avg_5": team_xg["xga"].mean(),
        "npxg_avg_5": team_xg["npxg"].mean() if "npxg" in team_xg.columns else None,
    }
