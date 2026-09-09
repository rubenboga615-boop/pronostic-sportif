"""Intervalles de confiance sur un rendement mesuré.

Un ROI sans intervalle ne dit presque rien. Le projet en a fait l'expérience :
l'Over/Under a été annoncé à **+3,97 %** sur 262 paris, chiffre qui paraissait
encourageant jusqu'à ce que son intervalle — [−11,36 ; +19,74] — montre qu'il
était indistinguable de zéro. Décider sur un point sans sa dispersion revient à
confondre le bruit avec un signal.

Méthode : bootstrap **par pari**, avec remise. Chaque tirage rejoue le même
nombre de paris que la mesure d'origine et recalcule le rendement ; la
distribution des rendements simulés donne les bornes. Le pari est l'unité de
rééchantillonnage parce que c'est l'unité de décision — c'est lui qu'on prend
ou qu'on laisse.

Limite à connaître : le bootstrap suppose les paris échangeables. Plusieurs
sélections d'un même match ne le sont pas tout à fait (un 1N2 et un
Over/Under du même match partagent le score), si bien que l'intervalle est un
peu **trop étroit** pour un lot multi-marchés. Il reste honnête sur un marché
pris seul, où chaque match ne contribue qu'une fois par sélection.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Assez pour que les bornes soient stables à la deuxième décimale, sans rendre
# la mesure coûteuse sur des dizaines de milliers de paris.
TIRAGES_PAR_DEFAUT = 2000


def gains_unitaires(issues, cotes) -> np.ndarray:
    """Gain net d'une mise de 1 sur chaque pari.

    Un pari gagné rapporte ``cote − 1``, un pari perdu coûte 1, un pari annulé
    (``void``, ligne remboursée) rapporte 0. Les issues inconnues sont exclues
    en amont par l'appelant.
    """
    issues = pd.Series(issues).reset_index(drop=True)
    cotes = pd.Series(cotes).reset_index(drop=True).astype(float)

    gains = np.where(issues == "won", cotes - 1.0, -1.0)
    return np.where(issues == "void", 0.0, gains)


def intervalle_de_confiance_roi(
    issues,
    cotes,
    niveau: float = 0.95,
    tirages: int = TIRAGES_PAR_DEFAUT,
    graine: int = 20260909,
) -> dict[str, Any]:
    """Intervalle de confiance du ROI, par bootstrap sur les paris.

    Args:
        issues: issues réglées (``won`` / ``lost`` / ``void``).
        cotes: cotes obtenues, alignées sur ``issues``.
        niveau: niveau de confiance (0,95 par défaut).
        tirages: nombre de rééchantillonnages.
        graine: graine du générateur — une mesure doit être rejouable à
            l'identique, sans quoi deux lectures du même backtest divergent.

    Returns:
        ``{"roi_pct", "borne_basse", "borne_haute", "paris", "tirages",
        "niveau", "significatif"}``. ``significatif`` est vrai quand
        l'intervalle ne contient pas zéro — c'est-à-dire quand le signe du
        rendement est établi, et lui seul.
    """
    gains = gains_unitaires(issues, cotes)
    n = len(gains)
    if n == 0:
        return {
            "roi_pct": None,
            "borne_basse": None,
            "borne_haute": None,
            "paris": 0,
            "tirages": 0,
            "niveau": niveau,
            "significatif": False,
        }

    generateur = np.random.default_rng(graine)
    indices = generateur.integers(0, n, size=(tirages, n))
    rois = gains[indices].mean(axis=1) * 100.0

    alpha = (1.0 - niveau) / 2.0
    basse, haute = np.quantile(rois, [alpha, 1.0 - alpha])

    return {
        "roi_pct": float(gains.mean() * 100.0),
        "borne_basse": float(basse),
        "borne_haute": float(haute),
        "paris": int(n),
        "tirages": int(tirages),
        "niveau": niveau,
        "significatif": bool(basse > 0.0 or haute < 0.0),
    }
