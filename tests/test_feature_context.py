"""Tests du contexte incrémental de features.

Le pipeline ne recalcule plus l'historique à chaque match : il fait avancer un
`FeatureContext` unique. Ce fichier vérifie les deux propriétés qui rendent ce
remplacement sûr :

1. **Équivalence avec les implémentations de référence.** Le classement et
   l'Elo maintenus incrémentalement doivent être, à chaque match, identiques à
   ceux que produisent `calculate_standings` et `_compute_elo_before` en
   rejouant tout l'historique.

2. **Équivalence entre les deux modes d'usage.** Faire avancer un contexte match
   après match doit donner exactement les mêmes features que le reconstruire
   depuis zéro pour chaque match.

Sans ces deux garanties, l'optimisation serait un pari.
"""

import pandas as pd
import pytest

from features.context import FeatureContext, build_context
from features.standings import calculate_standings
from pipelines.feature_pipeline import _compute_elo_before, compute_match_features

COLONNES = [
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


def _calendrier(n_equipes=8, n_saisons=2) -> pd.DataFrame:
    """Deux saisons de championnat, toutes équipes contre toutes, aller-retour.

    Les scores sont déterministes mais dissymétriques, de façon à produire un
    classement et des ratings Elo réellement différenciés — un jeu trop régulier
    laisserait passer des erreurs d'attribution.
    """
    lignes = []
    mid = 1
    for saison in range(1, n_saisons + 1):
        jour = pd.Timestamp(f"{2022 + saison}-08-06")
        for tour in range(2):
            for i in range(1, n_equipes + 1):
                for j in range(1, n_equipes + 1):
                    if i == j:
                        continue
                    home, away = (i, j) if tour == 0 else (j, i)
                    hg = (home * 3 + away + saison) % 4
                    ag = (away * 2 + home) % 3
                    lignes.append(
                        {
                            "id": mid,
                            "competition_id": 1,
                            "season_id": saison,
                            "match_date": jour,
                            "home_team_id": home,
                            "away_team_id": away,
                            "home_goals": hg,
                            "away_goals": ag,
                            "home_shots": 8 + hg * 2,
                            "away_shots": 7 + ag * 2,
                            "home_shots_on_target": 3 + hg,
                            "away_shots_on_target": 2 + ag,
                        }
                    )
                    mid += 1
                    if mid % 4 == 0:  # quatre matchs par journée
                        jour += pd.Timedelta(days=3)
    return pd.DataFrame(lignes, columns=COLONNES)


@pytest.fixture(scope="module")
def calendrier():
    return _calendrier()


def _cotes_vides() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "match_id",
            "market",
            "selection",
            "bookmaker",
            "odds",
            "captured_at",
            "is_closing",
        ]
    )


class TestEquivalenceAvecLesReferences:
    """Le contexte doit dire exactement la même chose que le calcul complet."""

    def test_classement_identique_a_chaque_journee(self, calendrier):
        contexte = FeatureContext()
        comparaisons = 0

        for date, journee in calendrier.groupby("match_date", sort=True):
            for saison in journee["season_id"].unique():
                attendu = calculate_standings(calendrier, date, competition_id=1, season_id=saison)
                obtenu = contexte.classement(1, saison)
                if attendu.empty:
                    assert obtenu.empty
                else:
                    pd.testing.assert_frame_equal(
                        obtenu.sort_index(), attendu.sort_index(), check_like=True
                    )
                comparaisons += 1
            for _, match in journee.iterrows():
                contexte.absorb(match)

        assert comparaisons > 50, "jeu de test trop petit pour être probant"

    def test_elo_identique_a_chaque_journee(self, calendrier):
        contexte = FeatureContext()

        for date, journee in calendrier.groupby("match_date", sort=True):
            anterieurs = calendrier[calendrier["match_date"] < date]
            for _, match in journee.iterrows():
                saison = match["season_id"]
                for team_id in (match["home_team_id"], match["away_team_id"]):
                    assert contexte.elo(team_id, saison) == pytest.approx(
                        _compute_elo_before(anterieurs, team_id, season_id=saison)
                    )
            for _, match in journee.iterrows():
                contexte.absorb(match)


class TestEquivalenceDesDeuxModes:
    """Avancer un contexte ou le reconstruire doit donner le même résultat."""

    def test_features_identiques_sur_tout_le_calendrier(self, calendrier):
        cotes = _cotes_vides()
        contexte = FeatureContext()
        ecarts = []

        for date, journee in calendrier.groupby("match_date", sort=True):
            anterieurs = calendrier[calendrier["match_date"] < date]
            for _, match in journee.iterrows():
                incremental = compute_match_features(match, None, cotes, context=contexte)
                reconstruit = compute_match_features(match, anterieurs, cotes)
                if incremental != reconstruit:
                    ecarts.append((int(match["id"]), incremental, reconstruit))
            for _, match in journee.iterrows():
                contexte.absorb(match)

        assert not ecarts, f"{len(ecarts)} matchs divergent, premier : {ecarts[:1]}"

    def test_build_context_borne_bien_l_historique(self, calendrier):
        """`build_context` n'intègre que les matchs strictement antérieurs."""
        coupure = calendrier["match_date"].iloc[len(calendrier) // 2]

        contexte = build_context(calendrier, coupure)
        attendu = calculate_standings(calendrier, coupure, competition_id=1, season_id=1)
        obtenu = contexte.classement(1, 1)

        pd.testing.assert_frame_equal(obtenu.sort_index(), attendu.sort_index(), check_like=True)


class TestCoutIndependantDeLHistorique:
    """Le coût par match ne doit plus croître avec la taille de la base."""

    def test_le_dernier_match_ne_coute_pas_plus_que_le_premier(self, calendrier):
        """Comparaison de travail effectué, mesurée en appels pandas.

        Un chronomètre serait instable en intégration continue. On mesure à la
        place la taille des données réellement manipulées : avec l'ancien
        calcul, l'historique passé aux modules de features grandissait à chaque
        match ; avec le contexte, il reste borné.
        """
        contexte = FeatureContext()
        tailles = []

        for _, journee in calendrier.groupby("match_date", sort=True):
            for _, match in journee.iterrows():
                tailles.append(len(contexte.historique_equipe(match["home_team_id"])))
            for _, match in journee.iterrows():
                contexte.absorb(match)

        # L'historique consulté est borné par les files du contexte, quelle que
        # soit la profondeur de la base.
        assert max(tailles) <= 30
        assert tailles[-1] <= 30
        assert len(calendrier) > 100, "jeu de test trop petit pour être probant"
