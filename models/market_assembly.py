"""Assemblage en mémoire des marchés de match entier (Phase 1).

Construit, à partir des features des deux équipes et de la moyenne de buts de la
ligue, la liste des prédictions des marchés 1N2, Double chance, Over/Under
(0.5/1.5/2.5/3.5) et BTTS, sans aucune écriture en base.
"""

from __future__ import annotations

import math
from typing import Any

from models.market_derivation import (
    derive_1n2,
    derive_btts,
    derive_double_chance,
    derive_over_under,
)
from models.poisson import compute_score_matrix, estimate_lambda

# Lignes Over/Under officielles de la Phase 1 (match entier).
OVER_UNDER_LINES: tuple[float, ...] = (0.5, 1.5, 2.5, 3.5)


def estimate_match_lambdas(
    home_features: dict[str, Any],
    away_features: dict[str, Any],
    league_avg_goals: float,
    home_advantage: float = 0.25,
) -> tuple[float, float]:
    """Estimer ``(lambda_home, lambda_away)`` à partir des features.

    Les features manquantes (``None``/``NaN``) retombent sur un fallback neutre :
    attaque ou défense = ``league_avg_goals`` (ratio neutre = 1.0).

    Raises:
        ValueError: si ``league_avg_goals`` n'est pas strictement positif.
    """
    if league_avg_goals <= 0:
        raise ValueError("league_avg_goals doit être strictement positif")

    home_attack = _neutral(home_features.get("goals_for_avg_5"), league_avg_goals)
    home_defense = _neutral(home_features.get("goals_against_avg_5"), league_avg_goals)
    away_attack = _neutral(away_features.get("goals_for_avg_5"), league_avg_goals)
    away_defense = _neutral(away_features.get("goals_against_avg_5"), league_avg_goals)

    lambda_home = estimate_lambda(
        home_attack,
        away_defense,
        league_avg_goals,
        home_advantage=home_advantage,
        is_home=True,
    )
    lambda_away = estimate_lambda(
        away_attack,
        home_defense,
        league_avg_goals,
        home_advantage=home_advantage,
        is_home=False,
    )
    return lambda_home, lambda_away


def build_match_markets(
    home_features: dict[str, Any],
    away_features: dict[str, Any],
    league_avg_goals: float,
    home_advantage: float = 0.25,
    max_goals: int = 8,
) -> list[dict[str, Any]]:
    """Assembler les prédictions des marchés de match entier (Phase 1).

    Args:
        home_features: features de l'équipe à domicile (dict de colonnes Feature).
        away_features: features de l'équipe à l'extérieur.
        league_avg_goals: buts moyens par équipe et par match (strictement > 0).
        home_advantage: avantage du terrain appliqué à ``lambda_home``.
        max_goals: borne supérieure de buts de la matrice de scores.

    Returns:
        ``list[dict]`` de 16 prédictions au format
        ``{"market", "selection", "probability", "fair_odds"}``.

    Raises:
        ValueError: si ``league_avg_goals`` n'est pas strictement positif.
    """
    lambda_home, lambda_away = estimate_match_lambdas(
        home_features,
        away_features,
        league_avg_goals,
        home_advantage=home_advantage,
    )
    score_matrix = compute_score_matrix(lambda_home, lambda_away, max_goals=max_goals)

    markets: list[dict[str, Any]] = []
    probs_1n2 = derive_1n2(score_matrix)
    markets.extend(probs_1n2)
    markets.extend(derive_double_chance(probs_1n2))
    for line in OVER_UNDER_LINES:
        markets.extend(derive_over_under(score_matrix, line))
    markets.extend(derive_btts(score_matrix))
    return markets


def _neutral(value: Any, league_avg_goals: float) -> float:
    """Fallback neutre : attaque/défense = moyenne de ligue si valeur absente."""
    if value is None:
        return float(league_avg_goals)
    f = float(value)
    return float(league_avg_goals) if math.isnan(f) else f
