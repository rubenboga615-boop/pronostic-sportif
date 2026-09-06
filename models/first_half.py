"""Modèle de prédiction pour la première mi-temps."""

from models.poisson import compute_score_matrix


def estimate_first_half_lambdas(
    home_ht_goals_avg: float,
    away_ht_goals_avg: float,
    league_avg_ht_goals: float = 1.2,
    home_advantage: float = 0.15,
) -> tuple[float, float]:
    """Estimer les lambdas de première mi-temps."""
    lambda_home = home_ht_goals_avg * (1 + home_advantage)
    lambda_away = away_ht_goals_avg
    return max(lambda_home, 0.1), max(lambda_away, 0.1)


def predict_first_half(
    home_ht_goals_avg: float,
    away_ht_goals_avg: float,
    max_goals: int = 5,
) -> dict:
    """Prédire les buts de première mi-temps."""
    lambda_home, lambda_away = estimate_first_half_lambdas(home_ht_goals_avg, away_ht_goals_avg)

    matrix = compute_score_matrix(lambda_home, lambda_away, max_goals=max_goals)

    return {
        "lambda_home_ht": lambda_home,
        "lambda_away_ht": lambda_away,
        "score_matrix": matrix,
    }
