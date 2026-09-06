"""Calcul du classement de ligue."""

import pandas as pd


def calculate_standings(
    matches_df: pd.DataFrame,
    match_date: pd.Timestamp,
    competition_id: int | None = None,
) -> pd.DataFrame:
    """Calculer le classement au moment d'un match donné.

    ⚠️ Anti-fuite : seuls les matchs AVANT match_date sont utilisés.
    """
    relevant = matches_df[matches_df["match_date"] < match_date]
    if competition_id is not None:
        relevant = relevant[relevant["competition_id"] == competition_id]

    if relevant.empty:
        return pd.DataFrame()

    standings = {}

    for _, match in relevant.iterrows():
        if pd.isna(match.get("home_goals")) or pd.isna(match.get("away_goals")):
            continue

        home_id = match["home_team_id"]
        away_id = match["away_team_id"]
        hg = int(match["home_goals"])
        ag = int(match["away_goals"])

        for team_id in [home_id, away_id]:
            if team_id not in standings:
                standings[team_id] = {
                    "played": 0,
                    "won": 0,
                    "drawn": 0,
                    "lost": 0,
                    "gf": 0,
                    "ga": 0,
                    "points": 0,
                }

        standings[home_id]["played"] += 1
        standings[away_id]["played"] += 1
        standings[home_id]["gf"] += hg
        standings[home_id]["ga"] += ag
        standings[away_id]["gf"] += ag
        standings[away_id]["ga"] += hg

        if hg > ag:
            standings[home_id]["won"] += 1
            standings[home_id]["points"] += 3
            standings[away_id]["lost"] += 1
        elif hg == ag:
            standings[home_id]["drawn"] += 1
            standings[home_id]["points"] += 1
            standings[away_id]["drawn"] += 1
            standings[away_id]["points"] += 1
        else:
            standings[away_id]["won"] += 1
            standings[away_id]["points"] += 3
            standings[home_id]["lost"] += 1

    df = pd.DataFrame.from_dict(standings, orient="index")
    df.index.name = "team_id"
    df = df.sort_values("points", ascending=False)
    df["position"] = range(1, len(df) + 1)

    return df


def get_team_position(
    standings: pd.DataFrame,
    team_id: int,
) -> int | None:
    """Obtenir la position d'une équipe dans le classement."""
    if team_id in standings.index:
        return int(standings.loc[team_id, "position"])
    return None
