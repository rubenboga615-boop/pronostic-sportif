"""Assemblage en mémoire des marchés de match entier (Phase 1).

Construit, à partir des features des deux équipes et de la moyenne de buts de la
ligue, la liste des prédictions des marchés 1N2, Double chance, Over/Under
(0.5/1.5/2.5/3.5) et BTTS, sans aucune écriture en base.

Les fonctions canoniques de ``market_derivation`` produisent des noms internes
(``"1n2"``, ``"home_win"``, ``"btts"``, …). Ce module les mappe vers un contrat
public cohérent avec ``odds_snapshots`` et les résultats, via
:func:`normalize_prediction`.
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

# ── Contrat public des identifiants de marchés (Prediction / settlement) ──

# Marchés publics du contrat (Phase 1, match entier).
PUBLIC_MARKETS: frozenset[str] = frozenset({"1N2", "double_chance", "over_under", "BTTS"})

# Sélections publiques par marché.
PUBLIC_SELECTIONS: dict[str, frozenset[str]] = {
    "1N2": frozenset({"home", "draw", "away"}),
    "double_chance": frozenset({"home_or_draw", "home_or_away", "draw_or_away"}),
    "over_under": frozenset(
        {f"over_{line}" for line in OVER_UNDER_LINES}
        | {f"under_{line}" for line in OVER_UNDER_LINES}
    ),
    "BTTS": frozenset({"yes", "no"}),
}

# Mapping nom interne (market_derivation) -> contrat public.
MARKET_TO_PUBLIC: dict[str, str] = {"1n2": "1N2", "btts": "BTTS"}
SELECTION_TO_PUBLIC: dict[str, str] = {"home_win": "home", "away_win": "away"}

# Réverses (contrat public -> nom interne), utiles pour le settlement.
PUBLIC_TO_MARKET: dict[str, str] = {v: k for k, v in MARKET_TO_PUBLIC.items()}
PUBLIC_TO_SELECTION: dict[str, str] = {v: k for k, v in SELECTION_TO_PUBLIC.items()}


def normalize_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    """Mapper une prédiction interne vers le contrat public.

    ``market`` et ``selection`` sont mappés vers leurs identifiants publics ;
    ``probability`` et ``fair_odds`` sont conservés à l'identique.
    """
    return {
        "market": MARKET_TO_PUBLIC.get(prediction["market"], prediction["market"]),
        "selection": SELECTION_TO_PUBLIC.get(
            prediction["selection"], prediction["selection"]
        ),
        "probability": prediction["probability"],
        "fair_odds": prediction["fair_odds"],
    }


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
        ``{"market", "selection", "probability", "fair_odds"}``, avec les
        identifiants **publics** (``"1N2"``, ``"home"``, ``"BTTS"``, …).

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

    return [normalize_prediction(p) for p in markets]


def _neutral(value: Any, league_avg_goals: float) -> float:
    """Fallback neutre : attaque/défense = moyenne de ligue si valeur absente."""
    if value is None:
        return float(league_avg_goals)
    f = float(value)
    return float(league_avg_goals) if math.isnan(f) else f
