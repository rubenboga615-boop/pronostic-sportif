"""Calibration des probabilités du modèle.

Une probabilité calibrée tient sa promesse : ce qui est annoncé à 60 % se
produit six fois sur dix. Un modèle peut très bien classer correctement les
matchs — bonne AUC — tout en étant systématiquement trop confiant, et perdre
de l'argent pour cette seule raison : un edge est un écart de probabilités, il
n'a aucun sens si l'une des deux est biaisée.

Sur les données réelles, la courbe de calibration du Dixon-Coles montrait
exactement ce défaut : les sélections annoncées à 84 % ne se réalisaient que
dans 67 % des cas.

Deux méthodes sont disponibles :

- **Platt** : une régression logistique sur le logit de la probabilité brute.
  Deux paramètres, donc peu de risque de surapprentissage, mais elle ne corrige
  qu'une déformation régulière ;
- **isotonique** : une régression monotone, plus souple, capable de corriger
  une déformation quelconque — au prix d'un besoin de données plus important.

Règle non négociable : le calibrateur s'ajuste sur un **jeu de validation**,
jamais sur le jeu de test. L'ajuster sur les données qui serviront à mesurer la
performance reviendrait à s'auto-évaluer sur ses propres réponses.

Le module précédent annonçait ces deux méthodes et retournait ses entrées
inchangées, dans les deux cas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from loguru import logger

EPSILON = 1e-6
METHODES = ("platt", "isotonic")


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPSILON, 1 - EPSILON)
    return np.log(p / (1 - p))


@dataclass
class Calibrateur:
    """Transformation apprise, applicable à de nouvelles probabilités."""

    methode: str
    parametres: dict[str, Any]
    n_ajustement: int

    def transform(self, probabilites) -> np.ndarray:
        """Appliquer la calibration à des probabilités brutes."""
        p = np.asarray(probabilites, dtype=float)
        if p.size == 0:
            return p

        if self.methode == "platt":
            a = self.parametres["a"]
            b = self.parametres["b"]
            return 1.0 / (1.0 + np.exp(-(a * _logit(p) + b)))

        seuils = np.asarray(self.parametres["seuils"], dtype=float)
        valeurs = np.asarray(self.parametres["valeurs"], dtype=float)
        return np.clip(np.interp(p, seuils, valeurs), 0.0, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "methode": self.methode,
            "parametres": self.parametres,
            "n_ajustement": self.n_ajustement,
        }

    @classmethod
    def from_dict(cls, donnees: dict[str, Any]) -> Calibrateur:
        return cls(
            methode=donnees["methode"],
            parametres=donnees["parametres"],
            n_ajustement=int(donnees.get("n_ajustement", 0)),
        )


def ajuster_calibrateur(y_true, y_prob, methode: str = "platt") -> Calibrateur:
    """Apprendre une calibration sur un jeu de validation.

    Args:
        y_true: issues observées, 1 si la sélection s'est réalisée.
        y_prob: probabilités brutes du modèle.
        methode: ``"platt"`` ou ``"isotonic"``.

    Returns:
        Le calibrateur ajusté.

    Raises:
        ValueError: si la méthode est inconnue, si le jeu est vide, ou s'il ne
            contient qu'une seule issue — rien à apprendre dans ce cas.
    """
    if methode not in METHODES:
        raise ValueError(f"Méthode inconnue : {methode!r}. Attendu : {METHODES}")

    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_prob, dtype=float)
    if y.size == 0:
        raise ValueError("Jeu de calibration vide")
    if len(np.unique(y)) < 2:
        raise ValueError("Une seule issue observée : la calibration n'a rien à apprendre")

    if methode == "platt":
        parametres = _ajuster_platt(y, p)
    else:
        parametres = _ajuster_isotonique(y, p)

    logger.info(f"Calibrateur {methode} ajusté sur {len(y)} observations")
    return Calibrateur(methode=methode, parametres=parametres, n_ajustement=int(len(y)))


MESSAGE_SANS_SKLEARN = (
    "La calibration demande scikit-learn, qui n'est pas installé.\n"
    '  pip install -e ".[ml]"\n'
    "Le reste du projet — import, features, entraînement, prédiction, "
    "règlement, backtest — fonctionne sans."
)


def _ajuster_platt(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    """Régression logistique à une variable sur le logit des probabilités."""
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError as erreur:  # pragma: no cover — dépend de l'installation
        raise ImportError(MESSAGE_SANS_SKLEARN) from erreur

    modele = LogisticRegression(C=1e6, solver="lbfgs")
    modele.fit(_logit(p).reshape(-1, 1), y)
    return {"a": float(modele.coef_[0][0]), "b": float(modele.intercept_[0])}


def _ajuster_isotonique(y: np.ndarray, p: np.ndarray) -> dict[str, list[float]]:
    """Régression monotone, résumée par ses points d'appui.

    Les points sont conservés plutôt que l'objet scikit-learn : ils sont
    sérialisables en JSON, donc enregistrables dans le registre des modèles et
    rejouables des années plus tard.
    """
    try:
        from sklearn.isotonic import IsotonicRegression
    except ImportError as erreur:  # pragma: no cover — dépend de l'installation
        raise ImportError(MESSAGE_SANS_SKLEARN) from erreur

    modele = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    modele.fit(p, y)

    seuils = np.unique(np.clip(p, 0.0, 1.0))
    valeurs = modele.predict(seuils)
    return {"seuils": [float(v) for v in seuils], "valeurs": [float(v) for v in valeurs]}


def calibrate_probabilities(raw_probabilities, calibrateur: Calibrateur | None = None):
    """Appliquer une calibration, ou retourner les probabilités inchangées.

    Sans calibrateur, les probabilités passent telles quelles — et le signalent
    dans le journal, plutôt que de laisser croire à une calibration effective.
    """
    if calibrateur is None:
        logger.warning("Aucun calibrateur fourni : probabilités laissées brutes")
        return np.asarray(raw_probabilities, dtype=float)
    return calibrateur.transform(raw_probabilities)
