"""Dixon-Coles ajusté sur les buts attendus plutôt que sur les buts marqués.

Le moteur ajusté sur les buts reproduit ce que le marché sait déjà : mesuré sur
les cinq championnats et 3 504 matchs de test, il perd 5,44 % sur le 1N2 et
3,46 % sur l'Over/Under, quand suivre le favori du marché ne coûte rien
(`docs/ETAT_ACTUEL.md`, 09/09/2026). Reste une idée jamais essayée : estimer les
forces d'attaque et de défense depuis les **xG** — la qualité des occasions —
plutôt que depuis le score final.

L'argument est celui de la variance. Un but est un tirage de Bernoulli sur une
occasion : une équipe qui se crée 2,1 xG et marque une fois a joué le même match
qu'une équipe qui en marque trois. Le score final mêle donc la force réelle et
le bruit de conversion ; le xG ne retient que la première. Si le marché
sur-réagit aux résultats récents, un modèle qui les ignore peut voir ce que le
prix ne voit pas.

Deux points d'implémentation méritent d'être explicités.

**La vraisemblance est un noyau de Poisson sur une observation continue.** Un
xG vaut 1,37, pas 1. La log-vraisemblance de Poisson s'écrit
``x·log(λ) − λ − log(x!)`` ; seul le dernier terme exige un entier, et il ne
dépend d'aucun paramètre. Le retirer laisse un estimateur de quasi-vraisemblance
de Poisson, dont les estimations de la moyenne restent consistantes — c'est
l'estimateur standard des modèles de comptage sur données non entières.

**Rho reste ajusté sur les buts réels.** La correction de Dixon-Coles porte sur
les quatre scores serrés — 0-0, 1-0, 0-1, 1-1 — et n'a aucun sens sur une
grandeur continue : il n'existe pas de match à 0,00 xG. Elle est donc estimée
dans un second temps, à lambdas figés, sur les scores effectivement observés.
La matrice de scores produite en aval reste ainsi celle d'un vrai Dixon-Coles,
et le modèle est directement interchangeable avec celui ajusté sur les buts.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from scipy.optimize import minimize, minimize_scalar

from models.dixon_coles import (
    PENALITE,
    RHO_MAX,
    RHO_MIN,
    XI_DEFAUT,
    DixonColesModel,
    poids_temporels,
    tau,
)

# Colonnes de xG attendues dans le jeu d'entraînement.
COLONNES_XG = ("home_xg", "away_xg")


def _log_vraisemblance_xg(
    params: np.ndarray,
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    home_xg: np.ndarray,
    away_xg: np.ndarray,
    poids: np.ndarray,
    n_teams: int,
) -> float:
    """Quasi-log-vraisemblance de Poisson négative, pondérée et vectorisée.

    Même paramétrage que l'ajustement sur les buts — ``somme(attaque) = 0``
    pour lever l'indétermination entre attaque et défense — mais sans ``rho`` :
    la correction sur les scores serrés ne s'applique pas à une observation
    continue.
    """
    home_adv = params[0]
    attack_libre = params[1:n_teams]
    attack = np.append(attack_libre, -attack_libre.sum())
    defense = params[n_teams : 2 * n_teams]

    log_lam = home_adv + attack[home_idx] - defense[away_idx]
    log_mu = attack[away_idx] - defense[home_idx]
    lam = np.exp(log_lam)
    mu = np.exp(log_mu)

    if not np.all(np.isfinite(lam)) or not np.all(np.isfinite(mu)):
        return PENALITE

    # x·log(λ) − λ : le terme −log(x!) de Poisson est constant en les
    # paramètres, et c'est le seul qui exigerait un entier.
    ll = home_xg * log_lam - lam + away_xg * log_mu - mu
    total = float(np.sum(poids * ll))
    if not np.isfinite(total):
        return PENALITE
    return -total


def _ajuster_rho(
    lam: np.ndarray,
    mu: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    poids: np.ndarray,
) -> float:
    """Estimer rho sur les buts réels, lambdas figés.

    Renvoie ``0.0`` si aucun match noté n'est disponible : mieux vaut un
    Dixon-Coles sans correction qu'une correction devinée.
    """
    if len(home_goals) == 0:
        logger.warning("Aucun match noté : rho laissé à 0")
        return 0.0

    def objectif(rho: float) -> float:
        correction = tau(home_goals, away_goals, lam, mu, rho)
        if np.any(correction <= 0):
            return PENALITE
        return -float(np.sum(poids * np.log(correction)))

    resultat = minimize_scalar(objectif, bounds=(RHO_MIN, RHO_MAX), method="bounded")
    return float(resultat.x)


def fit_dixon_coles_xg(
    matches_df: pd.DataFrame,
    *,
    xi: float = XI_DEFAUT,
    reference_date: pd.Timestamp | None = None,
    competition_id: Any = None,
    max_iterations: int = 500,
) -> DixonColesModel:
    """Ajuster un Dixon-Coles dont les forces viennent des xG.

    Args:
        matches_df: matchs d'entraînement. Colonnes requises :
            ``home_team_id``, ``away_team_id``, ``home_xg``, ``away_xg``.
            ``home_goals`` et ``away_goals`` servent à l'estimation de rho ;
            ``match_date`` à la pondération temporelle.
        xi: décroissance temporelle par jour. ``0`` désactive la pondération.
        reference_date: date depuis laquelle mesurer l'ancienneté. Par défaut,
            le dernier match du jeu d'entraînement.
        competition_id: renseigné dans le modèle, à titre documentaire.
        max_iterations: plafond d'itérations de l'optimiseur.

    Returns:
        Le modèle ajusté, avec ``metadata["cible"] == "xg"``. Il s'utilise
        exactement comme celui ajusté sur les buts.

    Raises:
        ValueError: si les colonnes de xG manquent, si aucun match n'en porte,
            ou si moins de deux équipes sont couvertes.
    """
    requis = {"home_team_id", "away_team_id", *COLONNES_XG}
    manquantes = requis - set(matches_df.columns)
    if manquantes:
        raise ValueError(f"Colonnes absentes du jeu d'entraînement : {sorted(manquantes)}")

    couverts = matches_df.dropna(subset=list(COLONNES_XG)).copy()
    if couverts.empty:
        raise ValueError("Aucun match avec xG : ajustement impossible")

    equipes = sorted(set(couverts["home_team_id"]) | set(couverts["away_team_id"]))
    index = {team_id: i for i, team_id in enumerate(equipes)}
    n_teams = len(equipes)
    if n_teams < 2:
        raise ValueError("Au moins deux équipes sont nécessaires")

    home_idx = couverts["home_team_id"].map(index).to_numpy(dtype=int)
    away_idx = couverts["away_team_id"].map(index).to_numpy(dtype=int)
    home_xg = couverts["home_xg"].to_numpy(dtype=float)
    away_xg = couverts["away_xg"].to_numpy(dtype=float)

    if xi > 0 and "match_date" in couverts.columns:
        reference = reference_date or pd.to_datetime(couverts["match_date"]).max()
        poids = poids_temporels(couverts["match_date"], pd.Timestamp(reference), xi)
    else:
        poids = np.ones(len(couverts))

    moyenne_dom = max(home_xg.mean(), 1e-3)
    moyenne_ext = max(away_xg.mean(), 1e-3)
    depart = np.concatenate(
        [
            [np.log(moyenne_dom) - np.log(moyenne_ext)],
            np.zeros(n_teams - 1),
            np.full(n_teams, -np.log(moyenne_ext)),
        ]
    )
    bornes = [(-1.0, 1.0)] + [(-3.0, 3.0)] * (n_teams - 1) + [(-3.0, 3.0)] * n_teams

    logger.info(
        f"Ajustement Dixon-Coles sur xG : {len(couverts)} matchs, {n_teams} équipes, xi={xi}"
    )
    resultat = minimize(
        _log_vraisemblance_xg,
        depart,
        args=(home_idx, away_idx, home_xg, away_xg, poids, n_teams),
        method="L-BFGS-B",
        bounds=bornes,
        options={"maxiter": max_iterations},
    )
    if not resultat.success:
        logger.warning(f"Optimisation non convergée : {resultat.message}")

    params = resultat.x
    home_advantage = float(params[0])
    attack_libre = params[1:n_teams]
    attack = np.append(attack_libre, -attack_libre.sum())
    defense = params[n_teams : 2 * n_teams]

    # Rho sur les scores réels des mêmes matchs, lambdas figés.
    lam = np.exp(home_advantage + attack[home_idx] - defense[away_idx])
    mu = np.exp(attack[away_idx] - defense[home_idx])
    if {"home_goals", "away_goals"} <= set(couverts.columns):
        notes = couverts[["home_goals", "away_goals"]].notna().all(axis=1).to_numpy()
        buts_dom = couverts.loc[notes, "home_goals"].to_numpy(dtype=float)
        buts_ext = couverts.loc[notes, "away_goals"].to_numpy(dtype=float)
    else:
        notes = np.zeros(len(couverts), dtype=bool)
        buts_dom = buts_ext = np.array([], dtype=float)

    rho = _ajuster_rho(lam[notes], mu[notes], buts_dom, buts_ext, poids[notes])

    modele = DixonColesModel(
        attack={team_id: float(attack[i]) for team_id, i in index.items()},
        defense={team_id: float(defense[i]) for team_id, i in index.items()},
        home_advantage=home_advantage,
        rho=rho,
        n_matches=int(len(couverts)),
        xi=xi,
        converged=bool(resultat.success),
        log_likelihood=float(-resultat.fun),
        competition_id=competition_id,
        metadata={
            "cible": "xg",
            "rho_ajuste_sur": "buts",
            "n_matchs_rho": int(notes.sum()),
        },
    )
    logger.info(
        f"Ajusté sur xG : avantage terrain={modele.home_advantage:.3f}, "
        f"rho={modele.rho:.3f}, quasi-log-vraisemblance={modele.log_likelihood:.1f}"
    )
    return modele
