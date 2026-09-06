"""Calcul des équipes comparables."""

import pandas as pd


def find_comparable_teams(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    n_teams: int = 5,
) -> list[int]:
    """Trouver les équipes de force comparable.

    Utilise les résultats récents pour identifier des adversaires
    de niveau similaire.
    """
    team_matches = (
        matches_df[
            ((matches_df["home_team_id"] == team_id) | (matches_df["away_team_id"] == team_id))
            & (matches_df["match_date"] < match_date)
        ]
        .sort_values("match_date")
        .tail(20)
    )

    if team_matches.empty:
        return []

    # Calculer les buts moyens de l'équipe
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
        return []

    avg_gf = sum(gf_list) / len(gf_list)
    avg_ga = sum(ga_list) / len(ga_list)

    # Identifier les adversaires et leurs performances moyennes
    opponents = {}
    for _, match in team_matches.iterrows():
        is_home = match["home_team_id"] == team_id
        opp_id = match["away_team_id"] if is_home else match["home_team_id"]
        opp_gf = match["away_goals"] if is_home else match["home_goals"]
        opp_ga = match["home_goals"] if is_home else match["away_goals"]

        if pd.notna(opp_gf) and pd.notna(opp_ga):
            if opp_id not in opponents:
                opponents[opp_id] = {"gf": [], "ga": []}
            opponents[opp_id]["gf"].append(int(opp_gf))
            opponents[opp_id]["ga"].append(int(opp_ga))

    # Calculer la force de chaque adversaire
    opp_strength = {}
    for opp_id, stats in opponents.items():
        if stats["gf"] and stats["ga"]:
            opp_avg_gf = sum(stats["gf"]) / len(stats["gf"])
            opp_avg_ga = sum(stats["ga"]) / len(stats["ga"])
            opp_strength[opp_id] = abs(opp_avg_gf - avg_gf) + abs(opp_avg_ga - avg_ga)

    # Trier par force comparable (écart le plus faible)
    sorted_opponents = sorted(opp_strength.items(), key=lambda x: x[1])

    return [opp_id for opp_id, _ in sorted_opponents[:n_teams]]
