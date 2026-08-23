"""Calcul du mouvement des cotes."""

import pandas as pd
from loguru import logger


def calculate_odds_movement(
    odds_data: pd.DataFrame,
    match_id: int,
    market: str = "1N2",
) -> dict:
    """Calculer le mouvement des cotes pour un match.
    
    Compare la première cote capturée avec la dernière.
    """
    if odds_data.empty:
        return {"odds_movement": None}

    match_odds = odds_data[
        (odds_data["match_id"] == match_id)
        & (odds_data["market"] == market)
    ].sort_values("captured_at")

    if match_odds.empty or len(match_odds) < 2:
        return {"odds_movement": None}

    first_odds = match_odds.iloc[0]["odds"]
    last_odds = match_odds.iloc[-1]["odds"]

    if first_odds and last_odds and first_odds > 0:
        movement = (last_odds - first_odds) / first_odds
        return {"odds_movement": movement}

    return {"odds_movement": None}
