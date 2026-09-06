"""Dérivation des marchés depuis la matrice de scores.

Chaque fonction retourne une liste de dictionnaires avec :
- market : nom du marché
- selection : sélection
- probability : probabilité
- fair_odds : cote équitable (1/probabilité)
"""

import numpy as np


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
        {
            "market": "1n2",
            "selection": "home_win",
            "probability": home_win,
            "fair_odds": fair_odds(home_win),
        },
        {"market": "1n2", "selection": "draw", "probability": draw, "fair_odds": fair_odds(draw)},
        {
            "market": "1n2",
            "selection": "away_win",
            "probability": away_win,
            "fair_odds": fair_odds(away_win),
        },
    ]


def derive_double_chance(probabilities_1n2: list[dict]) -> list[dict]:
    """Dériver les probabilités Double Chance depuis 1N2."""
    probs = {p["selection"]: p["probability"] for p in probabilities_1n2}
    return [
        {
            "market": "double_chance",
            "selection": "home_or_draw",
            "probability": probs["home_win"] + probs["draw"],
            "fair_odds": fair_odds(probs["home_win"] + probs["draw"]),
        },
        {
            "market": "double_chance",
            "selection": "home_or_away",
            "probability": probs["home_win"] + probs["away_win"],
            "fair_odds": fair_odds(probs["home_win"] + probs["away_win"]),
        },
        {
            "market": "double_chance",
            "selection": "draw_or_away",
            "probability": probs["draw"] + probs["away_win"],
            "fair_odds": fair_odds(probs["draw"] + probs["away_win"]),
        },
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
        {
            "market": "over_under",
            "selection": f"over_{line}",
            "probability": over,
            "fair_odds": fair_odds(over),
        },
        {
            "market": "over_under",
            "selection": f"under_{line}",
            "probability": under,
            "fair_odds": fair_odds(under),
        },
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
        {
            "market": "btts",
            "selection": "yes",
            "probability": btts_yes,
            "fair_odds": fair_odds(btts_yes),
        },
        {
            "market": "btts",
            "selection": "no",
            "probability": btts_no,
            "fair_odds": fair_odds(btts_no),
        },
    ]


# Lignes Over/Under de première mi-temps. Au-delà de 2,5 buts en une seule
# période, le marché n'est plus proposé par les bookmakers.
FIRST_HALF_LINES: tuple[float, ...] = (0.5, 1.5, 2.5)


def derive_first_half_markets(first_half_matrix: np.ndarray) -> list[dict]:
    """Dériver les marchés de première mi-temps : 1N2, double chance, O/U.

    BTTS de première mi-temps est volontairement exclu : le cahier des charges
    l'écarte de la première version.
    """
    probs_1n2 = derive_1n2(first_half_matrix)
    results = list(probs_1n2)
    results.extend(derive_double_chance(probs_1n2))
    for line in FIRST_HALF_LINES:
        results.extend(derive_over_under(first_half_matrix, line))
    return results


def derive_most_productive_half(
    first_half_matrix: np.ndarray,
    second_half_matrix: np.ndarray,
) -> list[dict]:
    """Déterminer la mi-temps la plus prolifique.

    Seul le nombre total de buts de chaque période compte : on réduit d'abord
    chaque matrice à la distribution de son total, puis on croise les deux.
    La comparaison directe des deux matrices demandait quatre boucles
    imbriquées — 6 561 itérations Python par match, soit plus de cent millions
    sur un historique complet.

    Les deux périodes sont supposées indépendantes conditionnellement aux
    forces des équipes ; c'est l'hypothèse habituelle, et la seule que les
    données disponibles permettent de soutenir.
    """
    totaux_1h = _distribution_du_total(first_half_matrix)
    totaux_2h = _distribution_du_total(second_half_matrix)

    # Produit extérieur : conjointe[a, b] = P(1re mi-temps = a et 2nde = b).
    conjointe = np.outer(totaux_1h, totaux_2h)
    indices_1h = np.arange(len(totaux_1h))[:, None]
    indices_2h = np.arange(len(totaux_2h))[None, :]

    prob_first = float(conjointe[indices_1h > indices_2h].sum())
    prob_second = float(conjointe[indices_1h < indices_2h].sum())
    prob_equal = float(conjointe[indices_1h == indices_2h].sum())

    return [
        {
            "market": "most_productive_half",
            "selection": "first_half",
            "probability": prob_first,
            "fair_odds": fair_odds(prob_first),
        },
        {
            "market": "most_productive_half",
            "selection": "second_half",
            "probability": prob_second,
            "fair_odds": fair_odds(prob_second),
        },
        {
            "market": "most_productive_half",
            "selection": "equal",
            "probability": prob_equal,
            "fair_odds": fair_odds(prob_equal),
        },
    ]


def _distribution_du_total(matrice: np.ndarray) -> np.ndarray:
    """Probabilité de chaque total de buts, depuis une matrice de scores."""
    lignes, colonnes = matrice.shape
    totaux = np.zeros(lignes + colonnes - 1)
    for i in range(lignes):
        for j in range(colonnes):
            totaux[i + j] += matrice[i][j]
    return totaux


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
        {
            "market": "asian_handicap",
            "selection": f"home_{handicap}",
            "probability": handicap_home,
            "fair_odds": fair_odds(handicap_home),
        },
        {
            "market": "asian_handicap",
            "selection": f"away_{-handicap}",
            "probability": handicap_away,
            "fair_odds": fair_odds(handicap_away),
        },
    ]
