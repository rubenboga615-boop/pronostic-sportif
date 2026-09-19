"""Modèle Dixon-Coles : estimation par maximum de vraisemblance.

Le modèle attribue à chaque équipe une force d'attaque et une force de défense,
ajoute un avantage du terrain commun, et corrige la dépendance entre les deux
scores sur les résultats serrés — 0-0, 1-0, 0-1, 1-1 — que le Poisson
indépendant sous-estime systématiquement.

.. math::

    \\lambda = \\exp(\\gamma + \\alpha_{dom} - \\beta_{ext})
    \\qquad
    \\mu = \\exp(\\alpha_{ext} - \\beta_{dom})

    P(X=x, Y=y) = \\tau(x, y) \\cdot \\mathrm{Poisson}(x; \\lambda)
                  \\cdot \\mathrm{Poisson}(y; \\mu)

Les paramètres sont estimés par maximisation de la log-vraisemblance, avec une
pondération temporelle décroissante : un match d'il y a trois ans en dit moins
sur l'équipe d'aujourd'hui qu'un match du mois dernier.

Deux précautions structurent l'implémentation :

- **l'ajustement se fait par compétition.** Une force d'attaque n'a de sens que
  relativement aux adversaires rencontrés ; mélanger cinq championnats sans
  matchs entre eux produirait des échelles incomparables ;
- **la vraisemblance est vectorisée.** La version précédente bouclait en Python
  sur chaque match ; l'optimiseur, qui évalue la fonction des centaines de
  fois, n'aurait jamais convergé en un temps utile.

Le modèle précédent n'entraînait rien : il retournait la moyenne de buts à
domicile et à l'extérieur de tout le jeu de données, identiques pour toutes les
équipes. Sa log-vraisemblance et son import de ``scipy.optimize`` étaient
présents mais jamais appelés.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from scipy.optimize import minimize
from scipy.stats import poisson

# Décroissance temporelle par jour. 0,0018 correspond à une demi-vie d'environ
# un an : un match d'il y a douze mois pèse moitié moins qu'un match du jour.
XI_DEFAUT = 0.0018

# Bornes de rho. Au-delà, la correction peut rendre négative la probabilité
# d'un score serré, ce qui n'a pas de sens.
RHO_MIN, RHO_MAX = -0.4, 0.4

# Pénalité renvoyée à l'optimiseur lorsqu'un jeu de paramètres est invalide.
PENALITE = 1e10

# Écart-type du prior gaussien placé sur les forces d'attaque et de défense.
#
# Sans lui, une équipe qui n'a pas marqué voit sa force d'attaque partir vers
# moins l'infini : c'est la séparation complète du maximum de vraisemblance.
# Mesuré le 19/09/2026 sur Coventry, promu n'ayant pas marqué en quatre matchs
# — force estimée à -8,07 quand toutes les autres tiennent dans [-0,45 ; +0,79],
# soit 0,0003 but attendu et un « BTTS non » annoncé à 100 %. Une probabilité
# de 100 % n'existe pas ; celle-ci était un artefact d'optimisation.
#
# Le défaut restait invisible tant que l'entraînement portait sur huit saisons
# complètes, où chaque équipe finit par marquer. Il apparaît dès qu'on entraîne
# jusqu'au jour même, avec des promus à quatre matchs.
#
# 0,5 est choisi sur la dispersion réellement observée des forces, qui tiennent
# dans [-0,5 ; +0,9] sur les cinq championnats. Le prior est donc large pour une
# équipe documentée — la vraisemblance de trois cents matchs l'écrase sans
# peine — et contraignant pour une équipe qui en compte quatre. C'est
# exactement le comportement voulu : le retrait vers la moyenne est
# proportionnel à ce qu'on ignore.
SIGMA_FORCES = 0.5

# Bornes des forces individuelles. Elles ne suffisent pas à elles seules : la
# contrainte d'identifiabilité `somme(attaques) = 0` fait de la dernière équipe
# l'opposé de la somme des autres, et celle-là échappe aux bornes de
# l'optimiseur. C'est par là que Coventry est descendu à -8,07.
BORNE_FORCE = 3.0


@dataclass
class DixonColesModel:
    """Paramètres ajustés d'un modèle Dixon-Coles."""

    attack: dict[int, float]
    defense: dict[int, float]
    home_advantage: float
    rho: float
    n_matches: int
    xi: float = XI_DEFAUT
    converged: bool = True
    log_likelihood: float = 0.0
    competition_id: Any = None
    # Nombre de matchs d'entraînement par équipe. C'est ce qui dit si une force
    # est croyable : quatre matchs ne valent pas trois cents, et rien dans les
    # paramètres eux-mêmes ne permet de faire la différence.
    matchs_par_equipe: dict[int, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def teams(self) -> set[int]:
        return set(self.attack)

    def lambdas(self, home_team_id: int, away_team_id: int) -> tuple[float, float]:
        """Buts attendus des deux équipes.

        Une équipe absente de l'entraînement — promue, ou première saison
        importée — est traitée comme moyenne : attaque et défense nulles. C'est
        une hypothèse prudente, à préférer au refus de prédire, mais elle doit
        se lire dans ``data_quality`` plutôt que passer inaperçue.
        """
        a_dom = self.attack.get(home_team_id, 0.0)
        d_dom = self.defense.get(home_team_id, 0.0)
        a_ext = self.attack.get(away_team_id, 0.0)
        d_ext = self.defense.get(away_team_id, 0.0)

        lam = float(np.exp(self.home_advantage + a_dom - d_ext))
        mu = float(np.exp(a_ext - d_dom))
        return max(lam, 1e-6), max(mu, 1e-6)

    def matchs_connus(self, *team_ids: int) -> int:
        """Le plus petit nombre de matchs d'entraînement parmi ces équipes.

        Sert à qualifier une prédiction plutôt qu'à la refuser : une rencontre
        où l'une des deux équipes compte quatre matchs ne vaut pas celle où
        toutes deux en comptent trois cents, et rien dans les probabilités
        produites ne laisse voir la différence.
        """
        if not self.matchs_par_equipe:
            return 0
        return min(self.matchs_par_equipe.get(int(t), 0) for t in team_ids)

    def score_matrix(
        self,
        home_team_id: int,
        away_team_id: int,
        max_goals: int = 8,
    ) -> np.ndarray:
        """Matrice des scores, corrigée par tau et normalisée à 1."""
        lam, mu = self.lambdas(home_team_id, away_team_id)
        return score_matrix_from_lambdas(lam, mu, self.rho, max_goals=max_goals)

    def to_dict(self) -> dict[str, Any]:
        """Représentation sérialisable, pour le registre des modèles."""
        return {
            "attack": {str(k): v for k, v in self.attack.items()},
            "defense": {str(k): v for k, v in self.defense.items()},
            "home_advantage": self.home_advantage,
            "rho": self.rho,
            "xi": self.xi,
            "n_matches": self.n_matches,
            "converged": self.converged,
            "log_likelihood": self.log_likelihood,
            "competition_id": self.competition_id,
            "matchs_par_equipe": {str(k): v for k, v in self.matchs_par_equipe.items()},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, donnees: dict[str, Any]) -> DixonColesModel:
        return cls(
            attack={int(k): float(v) for k, v in donnees["attack"].items()},
            defense={int(k): float(v) for k, v in donnees["defense"].items()},
            home_advantage=float(donnees["home_advantage"]),
            rho=float(donnees["rho"]),
            xi=float(donnees.get("xi", XI_DEFAUT)),
            n_matches=int(donnees.get("n_matches", 0)),
            converged=bool(donnees.get("converged", True)),
            log_likelihood=float(donnees.get("log_likelihood", 0.0)),
            competition_id=donnees.get("competition_id"),
            matchs_par_equipe={
                int(k): int(v) for k, v in (donnees.get("matchs_par_equipe") or {}).items()
            },
            metadata=donnees.get("metadata", {}),
        )


def tau(x, y, lambda_, mu, rho):
    """Correction de dépendance sur les scores serrés (Dixon-Coles, 1997).

    Accepte des scalaires ou des tableaux numpy, de façon à servir aussi bien
    la vraisemblance vectorisée que la construction d'une matrice de scores.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    lambda_ = np.asarray(lambda_)
    mu = np.asarray(mu)

    correction = np.ones(np.broadcast(x, y, lambda_, mu).shape, dtype=float)
    correction = np.where((x == 0) & (y == 0), 1.0 - lambda_ * mu * rho, correction)
    correction = np.where((x == 0) & (y == 1), 1.0 + lambda_ * rho, correction)
    correction = np.where((x == 1) & (y == 0), 1.0 + mu * rho, correction)
    correction = np.where((x == 1) & (y == 1), 1.0 - rho, correction)
    return correction


def score_matrix_from_lambdas(
    lambda_home: float,
    lambda_away: float,
    rho: float,
    max_goals: int = 8,
) -> np.ndarray:
    """Matrice des scores Dixon-Coles, normalisée à 1.

    La normalisation compense à la fois la troncature à ``max_goals`` et le fait
    que la correction tau ne conserve pas exactement la masse totale.
    """
    buts = np.arange(max_goals + 1)
    p_home = poisson.pmf(buts, lambda_home)
    p_away = poisson.pmf(buts, lambda_away)

    matrice = np.outer(p_home, p_away)
    x = buts[:, None]
    y = buts[None, :]
    matrice = matrice * tau(x, y, lambda_home, lambda_away, rho)

    matrice = np.clip(matrice, 0.0, None)
    total = matrice.sum()
    if total > 0:
        matrice = matrice / total
    return matrice


def _log_vraisemblance(
    params: np.ndarray,
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    poids: np.ndarray,
    n_teams: int,
    sigma_forces: float = SIGMA_FORCES,
) -> float:
    """Log-vraisemblance négative pénalisée et pondérée, vectorisée.

    Le paramétrage impose ``somme(attaque) = 0`` : sans cette contrainte, une
    constante ajoutée à toutes les attaques et retranchée à toutes les défenses
    laisse la vraisemblance inchangée, et les forces individuelles n'ont plus
    de valeur interprétable.

    S'y ajoute un prior gaussien centré sur zéro (voir :data:`SIGMA_FORCES`).
    Sa pénalité vaut ``somme(force²) / (2σ²)`` : négligeable devant la
    vraisemblance d'une équipe bien documentée, décisive pour une équipe qui
    n'a que quelques matchs et dont le maximum de vraisemblance divergerait.
    """
    rho = params[0]
    home_adv = params[1]
    attack_libre = params[2 : 1 + n_teams]
    attack = np.append(attack_libre, -attack_libre.sum())
    defense = params[1 + n_teams : 1 + 2 * n_teams]

    lam = np.exp(home_adv + attack[home_idx] - defense[away_idx])
    mu = np.exp(attack[away_idx] - defense[home_idx])

    if not np.all(np.isfinite(lam)) or not np.all(np.isfinite(mu)):
        return PENALITE

    correction = tau(home_goals, away_goals, lam, mu, rho)
    if np.any(correction <= 0):
        return PENALITE

    ll = np.log(correction) + poisson.logpmf(home_goals, lam) + poisson.logpmf(away_goals, mu)
    total = float(np.sum(poids * ll))
    if not np.isfinite(total):
        return PENALITE

    if sigma_forces > 0:
        penalite = (float(np.sum(attack**2)) + float(np.sum(defense**2))) / (
            2.0 * sigma_forces**2
        )
        return -total + penalite
    return -total


def poids_temporels(dates: pd.Series, reference: pd.Timestamp, xi: float) -> np.ndarray:
    """Poids décroissant exponentiellement avec l'ancienneté du match."""
    if xi <= 0:
        return np.ones(len(dates))
    anciennete = (reference - pd.to_datetime(dates)).dt.total_seconds() / 86400.0
    anciennete = np.clip(anciennete.to_numpy(dtype=float), 0.0, None)
    return np.exp(-xi * anciennete)


def fit_dixon_coles(
    matches_df: pd.DataFrame,
    *,
    xi: float = XI_DEFAUT,
    reference_date: pd.Timestamp | None = None,
    competition_id: Any = None,
    max_iterations: int = 500,
    sigma_forces: float = SIGMA_FORCES,
) -> DixonColesModel:
    """Ajuster un modèle Dixon-Coles par maximum de vraisemblance.

    Args:
        matches_df: matchs d'entraînement. Colonnes requises :
            ``home_team_id``, ``away_team_id``, ``home_goals``, ``away_goals``,
            et ``match_date`` si une pondération temporelle est demandée.
        xi: décroissance temporelle par jour. ``0`` désactive la pondération.
        reference_date: date depuis laquelle mesurer l'ancienneté. Par défaut,
            le dernier match du jeu d'entraînement — jamais ``datetime.now()``,
            pour que l'ajustement reste reproductible.
        competition_id: renseigné dans le modèle, à titre documentaire.
        max_iterations: plafond d'itérations de l'optimiseur.
        sigma_forces: écart-type du prior gaussien sur les forces. ``0``
            désactive la régularisation et restaure le maximum de
            vraisemblance pur — qui diverge sur une équipe n'ayant pas marqué,
            voir :data:`SIGMA_FORCES`.

    Returns:
        Le modèle ajusté.

    Raises:
        ValueError: si le jeu d'entraînement est vide ou sans match noté.
    """
    requis = {"home_team_id", "away_team_id", "home_goals", "away_goals"}
    manquantes = requis - set(matches_df.columns)
    if manquantes:
        raise ValueError(f"Colonnes absentes du jeu d'entraînement : {sorted(manquantes)}")

    notes = matches_df.dropna(subset=["home_goals", "away_goals"]).copy()
    if notes.empty:
        raise ValueError("Aucun match avec score : ajustement impossible")

    equipes = sorted(set(notes["home_team_id"]) | set(notes["away_team_id"]))
    index = {team_id: i for i, team_id in enumerate(equipes)}
    n_teams = len(equipes)
    if n_teams < 2:
        raise ValueError("Au moins deux équipes sont nécessaires")

    home_idx = notes["home_team_id"].map(index).to_numpy(dtype=int)
    away_idx = notes["away_team_id"].map(index).to_numpy(dtype=int)
    home_goals = notes["home_goals"].to_numpy(dtype=float)
    away_goals = notes["away_goals"].to_numpy(dtype=float)

    if xi > 0 and "match_date" in notes.columns:
        reference = reference_date or pd.to_datetime(notes["match_date"]).max()
        poids = poids_temporels(notes["match_date"], pd.Timestamp(reference), xi)
    else:
        poids = np.ones(len(notes))

    # Départ raisonnable : avantage du terrain égal à l'écart observé entre
    # buts à domicile et à l'extérieur, forces nulles, rho légèrement négatif
    # — signe attendu de la correction sur les scores serrés.
    moyenne_dom = max(home_goals.mean(), 1e-3)
    moyenne_ext = max(away_goals.mean(), 1e-3)
    depart = np.concatenate(
        [
            [-0.05],
            [np.log(moyenne_dom) - np.log(moyenne_ext)],
            np.zeros(n_teams - 1),
            np.full(n_teams, -np.log(moyenne_ext)),
        ]
    )

    bornes = (
        [(RHO_MIN, RHO_MAX), (-1.0, 1.0)]
        + [(-BORNE_FORCE, BORNE_FORCE)] * (n_teams - 1)
        + [(-BORNE_FORCE, BORNE_FORCE)] * n_teams
    )

    logger.info(
        f"Ajustement Dixon-Coles : {len(notes)} matchs, {n_teams} équipes, "
        f"xi={xi}, sigma={sigma_forces}"
    )
    resultat = minimize(
        _log_vraisemblance,
        depart,
        args=(home_idx, away_idx, home_goals, away_goals, poids, n_teams, sigma_forces),
        method="L-BFGS-B",
        bounds=bornes,
        options={"maxiter": max_iterations},
    )

    params = resultat.x
    matchs_par_equipe = (
        notes["home_team_id"].value_counts().add(
            notes["away_team_id"].value_counts(), fill_value=0
        )
    ).astype(int)
    attack_libre = params[2 : 1 + n_teams]
    attack = np.append(attack_libre, -attack_libre.sum())
    defense = params[1 + n_teams : 1 + 2 * n_teams]

    if not resultat.success:
        logger.warning(f"Optimisation non convergée : {resultat.message}")

    modele = DixonColesModel(
        attack={team_id: float(attack[i]) for team_id, i in index.items()},
        defense={team_id: float(defense[i]) for team_id, i in index.items()},
        home_advantage=float(params[1]),
        rho=float(params[0]),
        n_matches=int(len(notes)),
        xi=xi,
        converged=bool(resultat.success),
        log_likelihood=float(-resultat.fun),
        competition_id=competition_id,
        matchs_par_equipe={
            int(team_id): int(matchs_par_equipe.get(team_id, 0)) for team_id in index
        },
    )
    logger.info(
        f"Ajusté : avantage terrain={modele.home_advantage:.3f}, "
        f"rho={modele.rho:.3f}, log-vraisemblance={modele.log_likelihood:.1f}"
    )
    return modele


def fit_par_competition(
    matches_df: pd.DataFrame,
    **kwargs: Any,
) -> dict[Any, DixonColesModel]:
    """Ajuster un modèle par compétition.

    Les forces d'attaque ne sont comparables qu'entre équipes qui se
    rencontrent. Sans matchs entre championnats, un ajustement commun placerait
    les cinq échelles arbitrairement les unes par rapport aux autres.
    """
    if "competition_id" not in matches_df.columns:
        return {None: fit_dixon_coles(matches_df, **kwargs)}

    modeles: dict[Any, DixonColesModel] = {}
    for competition_id, groupe in matches_df.groupby("competition_id"):
        try:
            modeles[competition_id] = fit_dixon_coles(
                groupe, competition_id=competition_id, **kwargs
            )
        except ValueError as erreur:
            logger.warning(f"Compétition {competition_id} non ajustée : {erreur}")
    return modeles
