"""Modèle de Poisson pour la prédiction de buts."""

import numpy as np
from scipy.stats import poisson
from loguru import logger


def poisson_pmf(k: int, lam: float) -> float:
    """Calculer la probabilité de Poisson."""
    return poisson.pmf(k, lam)


def estimate_lambda(
    team_goals_scored: float,
    team_goals_conceded: float,
    league_avg_goals: float,
    home_advantage: float = 0.25,
    is_home: bool = True,
) -> float:
    """Estimer lambda (buts attendus) pour une équipe."""
    attack = team_goals_scored / league_avg_goals
    defense = team_goals_conceded / league_avg_goals
    lam = attack * defense * league_avg_goals
    if is_home:
        lam *= (1 + home_advantage)
    return max(lam, 0.1)


def compute_score_matrix(
    lambda_home: float,
    lambda_away: float,
    max_goals: int = 8,
) -> np.ndarray:
    """Calculer la matrice de probabilités de score (Poisson indépendant)."""
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            matrix[i][j] = poisson_pmf(i, lambda_home) * poisson_pmf(j, lambda_away)
    return matrix


def derive_1n2(score_matrix: np.ndarray) -> dict[str, float]:
    """Dériver les probabilités 1N2 depuis la matrice de scores."""
    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    for i in range(score_matrix.shape[0]):
        for j in range(score_matrix.shape[1]):
            if i > j:
                home_win += score_matrix[i][j]
            elif i == j:
                draw += score_matrix[i][j]
            else:
                away_win += score_matrix[i][j]
    return {"home_win": home_win, "draw": draw, "away_win": away_win}


def derive_over_under(score_matrix: np.ndarray, line: float) -> dict[str, float]:
    """Dériver les probabilités Over/Under."""
    over = 0.0
    for i in range(score_matrix.shape[0]):
        for j in range(score_matrix.shape[1]):
            if i + j > line:
                over += score_matrix[i][j]
    return {"over": over, "under": 1.0 - over}


def derive_btts(score_matrix: np.ndarray) -> dict[str, float]:
    """Dériver les probabilités BTTS (Both Teams To Score)."""
    btts_yes = 0.0
    for i in range(1, score_matrix.shape[0]):
        for j in range(1, score_matrix.shape[1]):
            btts_yes += score_matrix[i][j]
    return {"btts_yes": btts_yes, "btts_no": 1.0 - btts_yes}


def derive_double_chance(probabilities_1n2: dict[str, float]) -> dict[str, float]:
    """Dériver les probabilités Double Chance."""
    return {
        "home_or_draw": probabilities_1n2["home_win"] + probabilities_1n2["draw"],
        "home_or_away": probabilities_1n2["home_win"] + probabilities_1n2["away_win"],
        "draw_or_away": probabilities_1n2["draw"] + probabilities_1n2["away_win"],
    }
