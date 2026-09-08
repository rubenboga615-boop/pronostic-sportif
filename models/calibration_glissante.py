"""Calibration réajustée au fil du temps, plutôt qu'apprise une fois pour toutes.

Pourquoi
--------
Mesuré le 08/09/2026 sur les douze saisons de Premier League : un calibrateur
ajusté sur 2023/24 ramenait l'erreur du 1N2 à 0,012 sur cette saison, mais
elle remontait à 0,067 sur 2024/25 et 2025/26. Le biais d'un modèle n'est pas
une constante — il bouge avec les effectifs, les règles, la façon dont le
marché price. Une correction apprise sur une saison figée vieillit, et l'edge
qu'elle sert à calculer redevient nuisible.

D'où ce module : à chaque match, le calibrateur est réajusté sur ce qui était
**connu à cette date-là**, et sur rien d'autre.

Anti-fuite
----------
C'est la seule chose qui compte ici. Un calibrateur ajusté sur des matchs
postérieurs à celui qu'il corrige donnerait des résultats flatteurs et faux —
exactement le défaut que le projet a déjà rencontré trois fois. La règle est
donc stricte : pour un match daté du jour J, seules les observations
**strictement antérieures à J** entrent dans l'ajustement, et le lot d'un même
jour est traité d'un bloc, avant d'être versé à l'historique.

Deux formes de fenêtre
----------------------
- **Croissante** (défaut) : tout le passé disponible. Plus l'historique grandit,
  plus l'estimation est stable.
- **Glissante** : les ``fenetre`` dernières observations seulement. Elle oublie
  volontairement le passé lointain, ce qui vaut mieux si le biais dérive
  franchement — au prix d'une estimation plus bruitée.

Laquelle choisir n'est pas une question d'opinion : le script de mesure les
compare sur le même jeu de test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from models.calibration import Calibrateur, ajuster_calibrateur

# En dessous, un calibrateur apprendrait le bruit de quelques dizaines de
# matchs. Tant que ce seuil n'est pas atteint, les probabilités passent brutes.
MINIMUM_OBSERVATIONS = 300


def calibrer_en_glissant(
    df: pd.DataFrame,
    *,
    methode: str = "platt",
    fenetre: int | None = None,
    minimum: int = MINIMUM_OBSERVATIONS,
    colonne_probabilite: str = "probability",
    colonne_issue: str = "gagnant",
    colonne_date: str = "match_date",
) -> pd.DataFrame:
    """Calibrer chaque prédiction avec ce qui était connu avant son match.

    Args:
        df: prédictions réglées d'un seul marché, avec date, probabilité et
            issue observée (1 si la sélection s'est réalisée).
        methode: ``"platt"`` ou ``"isotonic"``.
        fenetre: nombre d'observations retenues. ``None`` conserve tout le
            passé (fenêtre croissante).
        minimum: en dessous, aucune calibration n'est appliquée.
        colonne_probabilite, colonne_issue, colonne_date: noms des colonnes.

    Returns:
        Une copie de ``df`` avec deux colonnes de plus : ``p_calibree`` et
        ``calibree`` (booléen — faux tant que l'historique est trop court).
    """
    if df.empty:
        resultat = df.copy()
        resultat["p_calibree"] = []
        resultat["calibree"] = []
        return resultat

    travail = df.sort_values([colonne_date]).reset_index(drop=True).copy()
    travail["p_calibree"] = travail[colonne_probabilite].astype(float)
    travail["calibree"] = False

    historique_p: list[float] = []
    historique_y: list[float] = []
    calibrateur: Calibrateur | None = None
    reajustements = 0

    # Traitement par journée : deux matchs du même jour ne s'informent jamais
    # l'un l'autre, comme dans le pipeline de features.
    for _, journee in travail.groupby(travail[colonne_date], sort=True):
        indices = journee.index

        if calibrateur is not None:
            brutes = travail.loc[indices, colonne_probabilite].astype(float).to_numpy()
            travail.loc[indices, "p_calibree"] = calibrateur.transform(brutes)
            travail.loc[indices, "calibree"] = True

        # La journée rejoint l'historique seulement après avoir été calibrée.
        historique_p.extend(journee[colonne_probabilite].astype(float).tolist())
        historique_y.extend(journee[colonne_issue].astype(float).tolist())

        if fenetre is not None and len(historique_p) > fenetre:
            historique_p = historique_p[-fenetre:]
            historique_y = historique_y[-fenetre:]

        if len(historique_p) >= minimum and len(set(historique_y)) >= 2:
            try:
                calibrateur = ajuster_calibrateur(
                    np.asarray(historique_y), np.asarray(historique_p), methode=methode
                )
                reajustements += 1
            except ValueError:
                # Historique dégénéré : on garde le calibrateur précédent.
                pass

    part = float(travail["calibree"].mean())
    logger.info(
        f"Calibration glissante ({methode}, fenêtre={fenetre or 'croissante'}) : "
        f"{reajustements} réajustements, {part:.0%} des lignes calibrées"
    )
    return travail


def erreur_de_calibration(probabilites, issues, n_tranches: int = 10) -> float:
    """Écart moyen entre annoncé et observé, pondéré par les effectifs."""
    p = np.asarray(probabilites, dtype=float)
    y = np.asarray(issues, dtype=float)
    tranches = np.clip((p * n_tranches).astype(int), 0, n_tranches - 1)
    total, poids = 0.0, 0
    for tranche in range(n_tranches):
        masque = tranches == tranche
        effectif = int(masque.sum())
        if effectif >= 10:
            total += abs(p[masque].mean() - y[masque].mean()) * effectif
            poids += effectif
    return total / poids if poids else float("nan")


__all__ = ["MINIMUM_OBSERVATIONS", "calibrer_en_glissant", "erreur_de_calibration"]
