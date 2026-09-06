"""Calcul du classement Elo pour les équipes de football."""

import pandas as pd

DEFAULT_ELO = 1500
K_FACTOR = 32


def expected_score(elo_a: float, elo_b: float) -> float:
    """Calculer le score attendu entre deux équipes."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def update_elo(elo_winner: float, elo_loser: float, draw: bool = False) -> tuple[float, float]:
    """Mettre à jour les ratings Elo après un match."""
    if draw:
        score_winner = 0.5
        score_loser = 0.5
    else:
        score_winner = 1.0
        score_loser = 0.0

    exp_winner = expected_score(elo_winner, elo_loser)
    exp_loser = expected_score(elo_loser, elo_winner)

    new_elo_winner = elo_winner + K_FACTOR * (score_winner - exp_winner)
    new_elo_loser = elo_loser + K_FACTOR * (score_loser - exp_loser)

    return new_elo_winner, new_elo_loser


def calculate_elo_ratings(
    matches_df: pd.DataFrame,
    team_ids: dict[str, int],
) -> pd.DataFrame:
    """Calculer les ratings Elo pour tous les matchs.

    Retourne un DataFrame avec les ratings Elo de chaque équipe
    avant chaque match (anti-fuite : le rating est calculé AVANT le résultat).
    """
    elo_ratings = {team_id: DEFAULT_ELO for team_id in team_ids.values()}
    elo_history = []

    sorted_matches = matches_df.sort_values("match_date")

    for _, match in sorted_matches.iterrows():
        if pd.isna(match.get("home_goals")) or pd.isna(match.get("away_goals")):
            continue

        home_id = match["home_team_id"]
        away_id = match["away_team_id"]

        home_elo_before = elo_ratings.get(home_id, DEFAULT_ELO)
        away_elo_before = elo_ratings.get(away_id, DEFAULT_ELO)

        elo_history.append(
            {
                "match_id": match.get("id"),
                "match_date": match["match_date"],
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_elo": home_elo_before,
                "away_elo": away_elo_before,
            }
        )

        # Mettre à jour après le match
        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])

        if home_goals > away_goals:
            new_home, new_away = update_elo(home_elo_before, away_elo_before)
        elif home_goals < away_goals:
            new_away, new_home = update_elo(away_elo_before, home_elo_before)
        else:
            new_home, new_away = update_elo(home_elo_before, away_elo_before, draw=True)

        elo_ratings[home_id] = new_home
        elo_ratings[away_id] = new_away

    return pd.DataFrame(elo_history)


def get_opponent_elo_avg(
    elo_history: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    window: int = 5,
) -> float | None:
    """Calculer la force moyenne des adversaires récents."""
    team_matches = elo_history[
        ((elo_history["home_team_id"] == team_id) | (elo_history["away_team_id"] == team_id))
        & (elo_history["match_date"] < match_date)
    ].tail(window)

    if team_matches.empty:
        return None

    opponent_elos = []
    for _, row in team_matches.iterrows():
        if row["home_team_id"] == team_id:
            opponent_elos.append(row["away_elo"])
        else:
            opponent_elos.append(row["home_elo"])

    return sum(opponent_elos) / len(opponent_elos) if opponent_elos else None
