"""Calcul du mouvement des cotes."""

import pandas as pd
from loguru import logger


def calculate_odds_movement(
    odds_data: pd.DataFrame,
    match_id: int,
    market: str = "1N2",
    selection: str = "home",
) -> dict:
    """Calculer le mouvement de cote d'un match pour une sélection donnée.

    Compare la cote d'ouverture (bookmaker ``B365``, ``is_closing=0``) à la cote
    de clôture (``B365_close``, ``is_closing=1``) pour la même sélection. Ne
    mélange ni les sélections ni les bookmakers.

    Retourne ``{"odds_movement": None}`` si la paire ouverture/clôture est
    incomplète ou invalide (cote manquante, non numérique ou <= 0).
    """
    if odds_data.empty:
        return {"odds_movement": None}

    match_odds = odds_data[
        (odds_data["match_id"] == match_id)
        & (odds_data["market"] == market)
        & (odds_data["selection"] == selection)
    ]

    opening = match_odds[
        (match_odds["bookmaker"] == "B365") & (match_odds["is_closing"] == 0)
    ]["odds"]
    closing = match_odds[
        (match_odds["bookmaker"] == "B365_close") & (match_odds["is_closing"] == 1)
    ]["odds"]

    if opening.empty or closing.empty:
        return {"odds_movement": None}

    opening_odds = opening.iloc[0]
    closing_odds = closing.iloc[0]

    if pd.isna(opening_odds) or pd.isna(closing_odds):
        return {"odds_movement": None}
    if opening_odds <= 0:
        return {"odds_movement": None}

    return {"odds_movement": (closing_odds - opening_odds) / opening_odds}
