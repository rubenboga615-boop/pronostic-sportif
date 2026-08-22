"""Dérivation des marchés depuis la matrice de scores.

Chaque fonction retourne une liste de dictionnaires avec :
- market : nom du marché
- selection : sélection
- probability : probabilité
- fair_odds : cote équitable (1/probabilité)
"""

import numpy as np
from loguru import logger


def fair_odds(probability: float) -> float:
    """Calculer la cote équitable."""
    if probability <= 0:
        return 999.0
    return round(1.0 / probability, 4)


def derive_1n2(score_matrix: np.ndarray) -> list[dict]:
    """Dériver les probabilités 1N2."""
    home_win = float(np.sum(np.tril(score_matrix, k=-1)))
    draw = float(np.sum(np.diag(score_matrix)))
    away_win = float(np.sum(np.triu(score_matrix, k=1)))

    return [
        {"market": "1n2", "selection": "home_win", "probability": home_win, "fair_odds": fair_odds(home_win)},
        {"market": "1n2", "selection": "draw", "probability": draw, "fair_odds": fair_odds(draw)},
        {"market": "1n2", "selection": "away_win", "probability": away_win, "fair_odds": fair_odds(away_win)},
    ]


def derive_double_chance(probabilities_1n2: list[dict]) -> list[dict]:
    """Dériver les probabilités Double Chance depuis 1N2."""
    probs = {p["selection"]: p["probability"] for p in probabilities_1n2}
    return [
        {"market": "double_chance", "selection": "home_or_draw", "probability": probs["home_win"] + probs["draw"], "fair_odds": fair_odds(probs["home_win"] + probs["draw"])},
        {"market": "double_chance", "selection": "home_or_away", "probability": probs["home_win"] + probs["away_win"], "fair_odds": fair_odds(probs["home_win"] + probs["away_win"])},
        {"market": "double_chance", "selection": "draw_or_away", "probability": probs["draw"] + probs["away_win"], "fair_odds": fair_odds(probs["draw"] + probs["away_win"])},
    ]


def derive_over_under(score_matrix: np.ndarray, line: float) -> list[dict]:
    """Dériver les probabilités Over/Under pour une ligne donnée."""
    rows, cols = score_matrix.shape
    over = 0.0
    for i in range(rows):
        for j in range(cols):
            if i + j > line:
                over += score_matrix[i][j]
    under = 1.0 - over
    return [
        {"market": "over_under", "selection": f"over_{line}", "probability": over, "fair_odds": fair_odds(over)},
        {"market": "over_under", "selection": f"under_{line}", "probability": under, "fair_odds": fair_odds(under)},
    ]


def derive_btts(score_matrix: np.ndarray) -> list[dict]:
    """Dériver les probabilités BTTS."""
    btts_yes = 0.0
    rows, cols = score_matrix.shape
    for i in range(1, rows):
        for j in range(1, cols):
            btts_yes += score_matrix[i][j]
    btts_no = 1.0 - btts_yes
    return [
        {"market": "btts", "selection": "yes", "probability": btts_yes, "fair_odds": fair_odds(btts_yes)},
        {"market": "btts", "selection": "no", "probability": btts_no, "fair_odds": fair_odds(btts_no)},
    ]


def derive_first_half_markets(first_half_matrix: np.ndarray) -> list[dict]:
    """Dériver les marchés de première mi-temps."""
    results = []
    results.extend(derive_1n2(first_half_matrix))
    for line in [0.5, 1.5, 2.5]:
        results.extend(derive_over_under(first_half_matrix, line))
    return results


def derive_most_productive_half(
    first_half_matrix: np.ndarray,
    second_half_matrix: np.ndarray,
) -> list[dict]:
    """Déterminer la mi-temps la plus prolifique."""
    # Probabilité que la 1ère MT ait plus de buts
    prob_first = 0.0
    prob_second = 0.0
    prob_equal = 0.0

    for i in range(first_half_matrix.shape[0]):
        for j in range(first_half_matrix.shape[1]):
            for k in range(second_half_matrix.shape[0]):
                for l in range(second_half_matrix.shape[1]):
                    total_1h = i + j
                    total_2h = k + l
                    joint = first_half_matrix[i][j] * second_half_matrix[k][l]
                    if total_1h > total_2h:
                        prob_first += joint
                    elif total_1h < total_2h:
                        prob_second += joint
                    else:
                        prob_equal += joint

    return [
        {"market": "most_productive_half", "selection": "first_half", "probability": prob_first, "fair_odds": fair_odds(prob_first)},
        {"market": "most_productive_half", "selection": "second_half", "probability": prob_second, "fair_odds": fair_odds(prob_second)},
        {"market": "most_productive_half", "selection": "equal", "probability": prob_equal, "fair_odds": fair_odds(prob_equal)},
    ]


def derive_asian_handicap(score_matrix: np.ndarray, handicap: float) -> list[dict]:
    """Dériver les probabilités de handicap asiatique."""
    handicap_home = 0.0
    handicap_away = 0.0
    handicap_push = 0.0

    rows, cols = score_matrix.shape
    for i in range(rows):
        for j in range(cols):
            adjusted_diff = (i + handicap) - j
            if adjusted_diff > 0:
                handicap_home += score_matrix[i][j]
            elif adjusted_diff < 0:
                handicap_away += score_matrix[i][j]
            else:
                handicap_push += score_matrix[i][j]

    return [
        {"market": "asian_handicap", "selection": f"home_{handicap}", "probability": handicap_home, "fair_odds": fair_odds(handicap_home)},
        {"market": "asian_handicap", "selection": f"away_{-handicap}", "probability": handicap_away, "fair_odds": fair_odds(handicap_away)},
    ]
