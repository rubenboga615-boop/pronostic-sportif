"""Modèles de mi-temps : première et seconde période.

Les marchés de première mi-temps et « mi-temps la plus prolifique » demandent
de savoir combien de buts chaque période produit, et pas seulement le total.
Deux modèles distincts sont donc ajustés, avec exactement la même machinerie
que le modèle de match entier :

- l'un sur les buts de première mi-temps (``HTHG`` / ``HTAG``) ;
- l'autre sur les buts de seconde mi-temps, obtenus par différence.

L'alternative aurait été de répartir les buts attendus du match entier selon
une proportion fixe — de l'ordre de 45 % en première période. Cette proportion
est une moyenne de ligue : elle ignore que certaines équipes démarrent fort et
s'éteignent, et surtout elle fabriquerait une information dont la base ne
dispose pas. Les scores de mi-temps sont présents dans les données ; autant
les utiliser.

La version précédente multipliait la moyenne de buts d'une équipe par un
avantage du terrain arbitraire, sans jamais tenir compte de l'adversaire, et
ignorait le paramètre ``league_avg_ht_goals`` qu'elle déclarait.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from loguru import logger

from models.dixon_coles import DixonColesModel, fit_dixon_coles


@dataclass
class ModelesDeMiTemps:
    """Paire de modèles ajustés, une période chacun."""

    premiere: DixonColesModel
    seconde: DixonColesModel

    @property
    def teams(self) -> set[int]:
        """Équipes connues des deux modèles à la fois."""
        return self.premiere.teams & self.seconde.teams

    def connait(self, home_team_id: int, away_team_id: int) -> bool:
        connues = self.teams
        return home_team_id in connues and away_team_id in connues

    def matrices(
        self,
        home_team_id: int,
        away_team_id: int,
        max_goals: int = 6,
    ) -> tuple[Any, Any]:
        """Matrices de scores des deux périodes.

        ``max_goals`` est plus bas que pour un match entier : au-delà de six
        buts en une seule mi-temps, la masse de probabilité est négligeable et
        la matrice est de toute façon renormalisée.
        """
        return (
            self.premiere.score_matrix(home_team_id, away_team_id, max_goals=max_goals),
            self.seconde.score_matrix(home_team_id, away_team_id, max_goals=max_goals),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"premiere": self.premiere.to_dict(), "seconde": self.seconde.to_dict()}

    @classmethod
    def from_dict(cls, donnees: dict[str, Any]) -> ModelesDeMiTemps:
        return cls(
            premiere=DixonColesModel.from_dict(donnees["premiere"]),
            seconde=DixonColesModel.from_dict(donnees["seconde"]),
        )


def separer_les_periodes(matches_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construire les deux jeux de buts, par période.

    Un match n'est retenu que si ses quatre scores sont renseignés et cohérents
    — un score de mi-temps supérieur au score final signale une donnée fausse,
    et produirait des buts négatifs en seconde période.

    Returns:
        ``(premiere, seconde)``, deux tableaux au format attendu par
        :func:`fit_dixon_coles`.

    Raises:
        ValueError: si les colonnes de mi-temps sont absentes.
    """
    requis = {"home_goals", "away_goals", "home_ht_goals", "away_ht_goals"}
    manquantes = requis - set(matches_df.columns)
    if manquantes:
        raise ValueError(f"Colonnes de mi-temps absentes : {sorted(manquantes)}")

    complets = matches_df.dropna(subset=sorted(requis)).copy()
    coherents = complets[
        (complets["home_ht_goals"] <= complets["home_goals"])
        & (complets["away_ht_goals"] <= complets["away_goals"])
    ]
    ecartes = len(complets) - len(coherents)
    if ecartes:
        logger.warning(f"{ecartes} matchs écartés : score de mi-temps supérieur au score final")

    premiere = coherents.copy()
    premiere["home_goals"] = coherents["home_ht_goals"]
    premiere["away_goals"] = coherents["away_ht_goals"]

    seconde = coherents.copy()
    seconde["home_goals"] = coherents["home_goals"] - coherents["home_ht_goals"]
    seconde["away_goals"] = coherents["away_goals"] - coherents["away_ht_goals"]

    return premiere, seconde


def fit_half_models(matches_df: pd.DataFrame, **kwargs: Any) -> ModelesDeMiTemps:
    """Ajuster un modèle par période.

    Les arguments supplémentaires sont transmis à :func:`fit_dixon_coles`
    (``xi``, ``reference_date``, ``competition_id``…).
    """
    premiere, seconde = separer_les_periodes(matches_df)

    logger.info(f"Ajustement des mi-temps sur {len(premiere)} matchs")
    return ModelesDeMiTemps(
        premiere=fit_dixon_coles(premiere, **kwargs),
        seconde=fit_dixon_coles(seconde, **kwargs),
    )
