"""Vue indexée de l'historique, avançable match par match.

Le calcul des features consultait, pour chaque match, l'intégralité de
l'historique : filtrage du tableau complet par équipe, recalcul du classement
depuis la première journée, et surtout rejeu de toute la boucle Elo — deux fois
par match. Le coût par match croissait donc avec la taille de la base : mesuré à
21 ms sur 50 matchs, 31 ms sur 200. Extrapolé aux ~19 000 matchs des cinq
championnats, le pipeline dépassait la dizaine d'heures.

Ce module maintient à la place un **état courant** : classement par saison,
rating Elo, et historique par équipe. Chaque match est d'abord *observé* pour en
extraire les features (:meth:`FeatureContext.observe`), puis *intégré* à l'état
(:meth:`FeatureContext.absorb`). Le coût par match devient indépendant de la
taille de la base.

Anti-fuite : l'état ne contient jamais que des matchs déjà intégrés. C'est à
l'appelant d'intégrer un match seulement après avoir observé tous ceux de la
même date — deux matchs du même jour ne doivent pas s'informer l'un l'autre.
:func:`build_context` et le pipeline respectent cette règle.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pandas as pd

from features.elo import DEFAULT_ELO, regress_towards_mean, update_elo

# Profondeur d'historique conservée par équipe. La plus large fenêtre utilisée
# par les modules de features est de 10 matchs (forme, domicile/extérieur) ;
# les trois files ci-dessous couvrent donc tous les besoins actuels.
PROFONDEUR = 10

COLONNES_HISTORIQUE = [
    "id",
    "competition_id",
    "season_id",
    "match_date",
    "home_team_id",
    "away_team_id",
    "home_goals",
    "away_goals",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
]


class FeatureContext:
    """État courant de l'historique, alimenté chronologiquement."""

    def __init__(self) -> None:
        # Trois files par équipe : tous ses matchs, ses matchs à domicile, ses
        # matchs à l'extérieur. Les modules de features prennent la queue de
        # l'une ou l'autre selon la fenêtre demandée.
        self._tous: dict[int, deque[dict[str, Any]]] = {}
        self._domicile: dict[int, deque[dict[str, Any]]] = {}
        self._exterieur: dict[int, deque[dict[str, Any]]] = {}

        # Elo courant et dernière saison connue par équipe.
        self._elo: dict[int, float] = {}
        self._saison_elo: dict[int, Any] = {}

        # Classement par (compétition, saison) puis par équipe.
        self._classements: dict[tuple[Any, Any], dict[int, dict[str, int]]] = {}

        # Dernier match par (équipe, saison), pour les jours de repos.
        self._dernier_match: dict[tuple[int, Any], pd.Timestamp] = {}

    # ── Alimentation ─────────────────────────────────────────────────────

    def absorb(self, match: pd.Series | dict[str, Any]) -> None:
        """Intégrer un match à l'état courant.

        À n'appeler qu'après avoir observé tous les matchs de la même date.
        """
        ligne = _ligne(match)
        home = ligne["home_team_id"]
        away = ligne["away_team_id"]
        if home is None or away is None:
            return

        self._empiler(home, ligne, domicile=True)
        self._empiler(away, ligne, domicile=False)

        date = ligne["match_date"]
        saison = ligne["season_id"]
        if date is not None:
            self._dernier_match[(home, saison)] = date
            self._dernier_match[(away, saison)] = date

        hg, ag = ligne["home_goals"], ligne["away_goals"]
        if hg is None or ag is None:
            return  # un match sans score ne modifie ni classement ni Elo

        self._maj_elo(home, away, hg, ag, saison)
        self._maj_classement(ligne, hg, ag)

    def _empiler(self, team_id: int, ligne: dict[str, Any], *, domicile: bool) -> None:
        for file in (self._tous, self._domicile if domicile else self._exterieur):
            file.setdefault(team_id, deque(maxlen=PROFONDEUR)).append(ligne)

    def _maj_elo(self, home: int, away: int, hg: int, ag: int, saison: Any) -> None:
        for tid in (home, away):
            self._regresser_si_nouvelle_saison(tid, saison)
        he = self._elo.get(home, DEFAULT_ELO)
        ae = self._elo.get(away, DEFAULT_ELO)
        if hg > ag:
            nh, na = update_elo(he, ae)
        elif hg < ag:
            na, nh = update_elo(ae, he)
        else:
            nh, na = update_elo(he, ae, draw=True)
        self._elo[home], self._elo[away] = nh, na

    def _regresser_si_nouvelle_saison(self, team_id: int, saison: Any) -> None:
        if saison is None:
            return
        precedente = self._saison_elo.get(team_id)
        if precedente is not None and precedente != saison:
            self._elo[team_id] = regress_towards_mean(self._elo.get(team_id, DEFAULT_ELO))
        self._saison_elo[team_id] = saison

    def _maj_classement(self, ligne: dict[str, Any], hg: int, ag: int) -> None:
        cle = (ligne["competition_id"], ligne["season_id"])
        table = self._classements.setdefault(cle, {})
        home, away = ligne["home_team_id"], ligne["away_team_id"]
        for tid in (home, away):
            table.setdefault(
                tid,
                {"played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "points": 0},
            )

        table[home]["played"] += 1
        table[away]["played"] += 1
        table[home]["gf"] += hg
        table[home]["ga"] += ag
        table[away]["gf"] += ag
        table[away]["ga"] += hg

        if hg > ag:
            table[home]["won"] += 1
            table[home]["points"] += 3
            table[away]["lost"] += 1
        elif hg == ag:
            table[home]["drawn"] += 1
            table[home]["points"] += 1
            table[away]["drawn"] += 1
            table[away]["points"] += 1
        else:
            table[away]["won"] += 1
            table[away]["points"] += 3
            table[home]["lost"] += 1

    # ── Consultation ─────────────────────────────────────────────────────

    def historique_equipe(self, team_id: int) -> pd.DataFrame:
        """Matchs récents d'une équipe, suffisants pour toutes les fenêtres.

        Réunit ses dix derniers matchs, ses dix derniers à domicile et ses dix
        derniers à l'extérieur : les modules de features y retrouvent la queue
        exacte dont ils ont besoin.
        """
        lignes: dict[int, dict[str, Any]] = {}
        for file in (self._tous, self._domicile, self._exterieur):
            for ligne in file.get(team_id, ()):
                lignes[ligne["id"]] = ligne
        return _frame(sorted(lignes.values(), key=lambda r: (r["match_date"], r["id"])))

    def historique_equipes(self, *team_ids: int) -> pd.DataFrame:
        """Historique réuni de plusieurs équipes, trié chronologiquement."""
        lignes: dict[int, dict[str, Any]] = {}
        for team_id in team_ids:
            for file in (self._tous, self._domicile, self._exterieur):
                for ligne in file.get(team_id, ()):
                    lignes[ligne["id"]] = ligne
        return _frame(sorted(lignes.values(), key=lambda r: (r["match_date"], r["id"])))

    def elo(self, team_id: int, saison: Any = None) -> float:
        """Rating Elo pré-match, régressé si le match ouvre une saison neuve."""
        rating = self._elo.get(team_id, DEFAULT_ELO)
        if saison is None:
            return rating
        precedente = self._saison_elo.get(team_id)
        if precedente is not None and precedente != saison:
            return regress_towards_mean(rating)
        return rating

    def classement(self, competition_id: Any, saison: Any) -> pd.DataFrame:
        """Classement courant, au format de :func:`features.standings.calculate_standings`."""
        table = self._classements.get((competition_id, saison))
        if not table:
            return pd.DataFrame()

        df = pd.DataFrame.from_dict(table, orient="index")
        df.index.name = "team_id"
        df["goal_difference"] = df["gf"] - df["ga"]
        df = df.sort_values(["points", "goal_difference", "gf"], ascending=[False, False, False])
        df["position"] = range(1, len(df) + 1)
        return df

    def dernier_match(self, team_id: int, saison: Any) -> pd.Timestamp | None:
        """Date du dernier match de l'équipe dans la saison, ou None."""
        return self._dernier_match.get((team_id, saison))


def build_context(prior_matches: pd.DataFrame, before: pd.Timestamp) -> FeatureContext:
    """Construire un contexte à partir d'un historique, borné à ``before``.

    Seuls les matchs strictement antérieurs à ``before`` sont intégrés. C'est le
    chemin utilisé pour un calcul isolé ; le pipeline, lui, fait avancer un
    contexte unique et n'appelle pas cette fonction.
    """
    contexte = FeatureContext()
    if prior_matches is None or prior_matches.empty:
        return contexte

    retenus = prior_matches[prior_matches["match_date"] < before]
    for _, match in retenus.sort_values(["match_date", "id"]).iterrows():
        contexte.absorb(match)
    return contexte


def _ligne(match: pd.Series | dict[str, Any]) -> dict[str, Any]:
    """Normaliser un match en dictionnaire aux types Python natifs."""
    lu = match.get if hasattr(match, "get") else match.__getitem__
    ligne: dict[str, Any] = {}
    for colonne in COLONNES_HISTORIQUE:
        valeur = lu(colonne) if hasattr(match, "get") else match[colonne]
        ligne[colonne] = _valeur(colonne, valeur)
    return ligne


def _valeur(colonne: str, valeur: Any) -> Any:
    if valeur is None or (not isinstance(valeur, pd.Timestamp) and pd.isna(valeur)):
        return None
    if colonne == "match_date":
        return pd.Timestamp(valeur)
    if colonne in ("season_id", "competition_id"):
        return valeur
    return int(valeur)


def _frame(lignes: list[dict[str, Any]]) -> pd.DataFrame:
    """Construire un tableau au schéma attendu par les modules de features."""
    if not lignes:
        return pd.DataFrame(columns=COLONNES_HISTORIQUE)
    return pd.DataFrame(lignes, columns=COLONNES_HISTORIQUE)
