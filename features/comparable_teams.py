"""Équipes comparables et force des adversaires affrontés.

Deux équipes à onze points ne valent pas la même chose si l'une les a pris
contre le haut du tableau et l'autre contre le bas. La force du calendrier déjà
joué corrige cette lecture.
"""

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


def calculate_opponent_strength(
    matches_df: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    elo_de,
    window: int = 5,
) -> dict:
    """Force moyenne des adversaires récemment affrontés.

    Args:
        matches_df: historique de l'équipe.
        team_id: équipe décrite.
        match_date: borne stricte ; rien à cette date ou après n'est compté.
        elo_de: fonction ``team_id -> Elo``, évaluée **au moment de la
            prédiction**. Tous les matchs qu'elle résume sont antérieurs à
            ``match_date`` : la règle anti-fuite est respectée.
        window: nombre d'adversaires récents retenus.

    Returns:
        ``{"opponent_elo_avg_5": float}``, ou ``None`` faute d'adversaire connu.
    """
    cle = f"opponent_elo_avg_{window}"
    if matches_df is None or matches_df.empty:
        return {cle: None}

    joues = (
        matches_df[
            ((matches_df["home_team_id"] == team_id) | (matches_df["away_team_id"] == team_id))
            & (matches_df["match_date"] < match_date)
        ]
        .sort_values("match_date")
        .tail(window)
    )
    if joues.empty:
        return {cle: None}

    adversaires = [
        int(m["away_team_id"]) if m["home_team_id"] == team_id else int(m["home_team_id"])
        for _, m in joues.iterrows()
    ]
    ratings = [elo_de(adverse) for adverse in adversaires]
    ratings = [r for r in ratings if r is not None]

    return {cle: sum(ratings) / len(ratings) if ratings else None}
