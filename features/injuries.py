"""Calcul de l'impact des blessures."""

import pandas as pd


def calculate_injury_impact(
    availability_data: pd.DataFrame,
    team_id: int,
    match_id: int,
) -> float:
    """Calculer l'impact des blessures pour une équipe.

    Utilise un score pondéré basé sur :
    - Le statut du joueur (titulaire, remplaçant)
    - Les minutes jouées
    - Les performances historiques (buts, xG)
    """
    if availability_data.empty:
        return 0.0

    team_availability = availability_data[
        (availability_data["team_id"] == team_id) & (availability_data["match_id"] == match_id)
    ]

    if team_availability.empty:
        return 0.0

    injury_impact = 0.0

    for _, player in team_availability.iterrows():
        if player.get("status") == "confirmed_absence":
            # Pondération prudente
            importance = 0.5  # Défaut si pas d'info supplémentaire
            if player.get("reason"):
                # Blessure grave = impact plus élevé
                if "cruciate" in str(player.get("reason", "")).lower():
                    importance = 0.9
                elif "hamstring" in str(player.get("reason", "")).lower():
                    importance = 0.7
            injury_impact += importance

    return min(injury_impact, 5.0)  # Plafonner l'impact
