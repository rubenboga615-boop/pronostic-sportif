"""Métriques d'évaluation du modèle de pronostic.

`PROJECT_SPEC.md` est explicite : « Ne jamais présenter uniquement l'accuracy ».
Une accuracy élevée peut recouvrir un modèle inutilisable — prédire la victoire
à domicile à chaque match en obtient déjà près de 45 % — tandis qu'un modèle
mal calibré perd de l'argent en pariant même quand il a souvent raison.

Les métriques sont donc de trois familles :

- **exactitude** : accuracy, contre laquelle on compare toujours une stratégie
  naïve ;
- **qualité probabiliste** : log loss, Brier, courbe de calibration, AUC. Ce
  sont elles qui disent si une probabilité annoncée de 60 % se réalise
  effectivement six fois sur dix ;
- **rendement** : ROI et drawdown, calculés contre des cotes réellement
  offertes — jamais contre la cote équitable du modèle lui-même.
"""

from __future__ import annotations

import numpy as np

EPSILON = 1e-15


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    """Proportion de prédictions exactes."""
    if not y_true:
        return 0.0
    return sum(1 for t, p in zip(y_true, y_pred, strict=False) if t == p) / len(y_true)


def log_loss(y_true, y_prob, epsilon: float = EPSILON) -> float:
    """Log loss binaire (entropie croisée).

    Pénalise durement une probabilité confiante et fausse : c'est la métrique
    qui distingue un modèle prudent d'un modèle qui a de la chance.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), epsilon, 1 - epsilon)
    if y_true.size == 0:
        return float("nan")
    return float(-np.mean(y_true * np.log(y_prob) + (1 - y_true) * np.log(1 - y_prob)))


def brier_score(y_true, y_prob) -> float:
    """Erreur quadratique moyenne entre probabilité annoncée et issue observée."""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    if y_true.size == 0:
        return float("nan")
    return float(np.mean((y_true - y_prob) ** 2))


def auc(y_true, y_prob) -> float:
    """Aire sous la courbe ROC, calculée par la statistique de Mann-Whitney.

    Retourne ``nan`` si toutes les issues sont identiques : l'AUC n'est pas
    définie sans au moins un succès et un échec.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    positifs = y_true == 1
    negatifs = y_true == 0
    if not positifs.any() or not negatifs.any():
        return float("nan")

    rangs = _rangs_moyens(y_prob)
    somme_positifs = rangs[positifs].sum()
    n_pos = int(positifs.sum())
    n_neg = int(negatifs.sum())
    return float((somme_positifs - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _rangs_moyens(valeurs: np.ndarray) -> np.ndarray:
    """Rangs de 1 à n, les ex æquo recevant leur rang moyen."""
    ordre = np.argsort(valeurs, kind="stable")
    rangs = np.empty(len(valeurs), dtype=float)
    rangs[ordre] = np.arange(1, len(valeurs) + 1)

    triees = valeurs[ordre]
    debut = 0
    for i in range(1, len(triees) + 1):
        if i == len(triees) or triees[i] != triees[debut]:
            if i - debut > 1:
                rangs[ordre[debut:i]] = rangs[ordre[debut:i]].mean()
            debut = i
    return rangs


def calibration_curve(y_true, y_prob, n_bins: int = 10) -> list[tuple[float, float, int]]:
    """Courbe de calibration : (probabilité moyenne annoncée, observée, effectif).

    Un modèle calibré aligne les deux premières valeurs sur chaque tranche : ce
    qu'il annonce à 60 % doit se produire six fois sur dix.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    if y_true.size == 0:
        return []

    bornes = np.linspace(0, 1, n_bins + 1)
    resultats = []
    for i in range(n_bins):
        # La dernière tranche est fermée à droite, sinon p = 1 en sortirait.
        if i == n_bins - 1:
            masque = (y_prob >= bornes[i]) & (y_prob <= bornes[i + 1])
        else:
            masque = (y_prob >= bornes[i]) & (y_prob < bornes[i + 1])
        if masque.sum():
            resultats.append(
                (
                    float(y_prob[masque].mean()),
                    float(y_true[masque].mean()),
                    int(masque.sum()),
                )
            )
    return resultats


def erreur_de_calibration(y_true, y_prob, n_bins: int = 10) -> float:
    """Écart moyen de calibration, pondéré par les effectifs (ECE).

    Résume la courbe en un nombre : 0 signifie parfaitement calibré.
    """
    courbe = calibration_curve(y_true, y_prob, n_bins)
    if not courbe:
        return float("nan")
    total = sum(effectif for _, _, effectif in courbe)
    return float(sum(abs(p - o) * n for p, o, n in courbe) / total)


def roi_simulation(issues, cotes, mises=None) -> dict:
    """Simuler le rendement d'une série de paris.

    Args:
        issues: pour chaque pari, ``"won"``, ``"lost"`` ou ``"push"``.
        cotes: cote décimale **réellement offerte** pour chaque pari.
        mises: mise de chaque pari ; 1 unité partout par défaut.

    Returns:
        Mise totale, retour, profit, ROI en pourcentage, drawdown maximal et
        nombre de paris. Le drawdown est mesuré depuis le sommet du solde
        cumulé, y compris lorsque celui-ci n'est jamais repassé positif.
    """
    issues = list(issues)
    cotes = list(cotes)
    mises = [1.0] * len(issues) if mises is None else list(mises)

    mise_totale = 0.0
    retour_total = 0.0
    solde = 0.0
    sommet = 0.0
    drawdown_max = 0.0
    paris = 0
    gagnants = 0

    for issue, cote, mise in zip(issues, cotes, mises, strict=False):
        if cote is None or cote <= 1.0 or mise <= 0:
            continue

        mise_totale += mise
        paris += 1

        if issue == "push":
            retour_total += mise
        elif issue == "won":
            retour_total += mise * cote
            solde += mise * (cote - 1)
            gagnants += 1
        else:
            solde -= mise

        sommet = max(sommet, solde)
        drawdown_max = max(drawdown_max, sommet - solde)

    roi = ((retour_total - mise_totale) / mise_totale * 100) if mise_totale else 0.0
    return {
        "mise_totale": mise_totale,
        "retour_total": retour_total,
        "profit": retour_total - mise_totale,
        "roi_pct": roi,
        "drawdown_max": drawdown_max,
        "paris": paris,
        "paris_gagnants": gagnants,
        "taux_de_reussite": (gagnants / paris) if paris else 0.0,
    }
