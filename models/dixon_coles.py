"""Modèle Dixon-Coles pour la prédiction de buts.

Améliore le modèle de Poisson en corrigeant les petits scores
(0-0, 1-0, 0-1, 1-1) via un paramètre de corrélation rho.
"""

import numpy as np
from loguru import logger
from scipy.stats import poisson


def tau(x: int, y: int, lambda_: float, mu: float, rho: float) -> float:
    """Fonction de corrélation de Dixon-Coles."""
    if x == 0 and y == 0:
        return 1 - lambda_ * mu * rho
    elif x == 0 and y == 1:
        return 1 + lambda_ * rho
    elif x == 1 and y == 0:
        return 1 + mu * rho
    elif x == 1 and y == 1:
        return 1 - rho
    else:
        return 1.0


def dixon_coles_log_likelihood(
    params: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    home_team_ids: np.ndarray,
    away_team_ids: np.ndarray,
    n_teams: int,
) -> float:
    """Log-vraisemblance négative du modèle Dixon-Coles."""
    rho = params[0]
    home_adv = params[1]
    attack = params[2 : 2 + n_teams]
    defense = params[2 + n_teams : 2 + 2 * n_teams]

    ll = 0.0
    for i in range(len(home_goals)):
        h = int(home_goals[i])
        a = int(away_goals[i])
        hi = home_team_ids[i]
        ai = away_team_ids[i]

        lambda_ = np.exp(home_adv + attack[hi] - defense[ai])
        mu = np.exp(attack[ai] - defense[hi])

        ll += np.log(tau(h, a, lambda_, mu, rho) + 1e-10)
        ll += poisson.logpmf(h, lambda_) + poisson.logpmf(a, mu)

    return -ll


def fit_dixon_coles(
    matches_df,
    max_goals: int = 8,
) -> dict:
    """Entraîner le modèle Dixon-Coles."""

    logger.info("Entraînement Dixon-Coles en cours...")

    # Simplification : estimation directe des lambdas
    # (une implémentation complète utiliserait l'optimisation scipy)
    home_goals = matches_df["home_goals"].values
    away_goals = matches_df["away_goals"].values

    # Estimation initiale simple
    lambda_home = home_goals.mean()
    lambda_away = away_goals.mean()

    # Correction rho pour les petits scores
    observed_small = sum(
        1 for h, a in zip(home_goals, away_goals) if (h, a) in [(0, 0), (1, 0), (0, 1), (1, 1)]
    )
    expected_small = sum(
        poisson.pmf(h, lambda_home) * poisson.pmf(a, lambda_away)
        for h, a in [(0, 0), (1, 0), (0, 1), (1, 1)]
    )
    rho = max(-0.5, min(0.5, (observed_small / len(home_goals) - expected_small) / expected_small))

    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "rho": rho,
    }
