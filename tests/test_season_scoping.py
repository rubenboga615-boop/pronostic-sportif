"""Tests du périmètre saison des features.

Un classement, des jours de repos et un rating Elo n'ont de sens qu'en
référence à une saison. Sans cette borne, les features cumulent les
exercices : une équipe démarre une nouvelle saison avec les points de la
précédente, et la trêve estivale se compte comme du repos.
"""

import pandas as pd
import pytest

from features.elo import DEFAULT_ELO, SEASON_CARRY_OVER, regress_towards_mean
from features.rest_days import calculate_rest_days, calculate_rest_features
from features.standings import calculate_standings, get_team_position
from pipelines.feature_pipeline import _compute_elo_before


def _match(mid, season, date, home, away, hg, ag, competition=1):
    return {
        "id": mid,
        "competition_id": competition,
        "season_id": season,
        "match_date": pd.Timestamp(date),
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": hg,
        "away_goals": ag,
    }


@pytest.fixture
def deux_saisons():
    """Deux saisons complètes : équipe 1 domine la première, s'effondre ensuite."""
    rows = [
        # Saison 1 — l'équipe 1 gagne tout
        _match(1, 1, "2023-09-02", 1, 2, 3, 0),
        _match(2, 1, "2023-09-09", 1, 3, 4, 0),
        _match(3, 1, "2023-09-16", 2, 3, 1, 1),
        # Saison 2 — l'équipe 1 perd son premier match
        _match(4, 2, "2024-08-17", 2, 1, 2, 0),
        _match(5, 2, "2024-08-24", 3, 1, 1, 0),
    ]
    return pd.DataFrame(rows)


class TestClassementParSaison:
    def test_le_classement_repart_de_zero(self, deux_saisons):
        """Aucun point de la saison 1 ne subsiste au premier match de la saison 2."""
        classement = calculate_standings(
            deux_saisons, pd.Timestamp("2024-08-31"), competition_id=1, season_id=2
        )

        assert classement.loc[1, "played"] == 2
        assert classement.loc[1, "points"] == 0
        assert classement.loc[1, "gf"] == 0

    def test_sans_borne_les_saisons_se_cumulent(self, deux_saisons):
        """Comportement sans season_id : c'est précisément le défaut corrigé."""
        cumul = calculate_standings(deux_saisons, pd.Timestamp("2024-08-31"), competition_id=1)

        assert cumul.loc[1, "played"] == 4  # 2 saisons confondues
        assert cumul.loc[1, "points"] == 6  # les victoires de la saison 1

    def test_position_bornee_au_nombre_d_equipes_de_la_saison(self, deux_saisons):
        """Une position ne peut pas dépasser le nombre d'équipes engagées."""
        classement = calculate_standings(
            deux_saisons, pd.Timestamp("2024-08-31"), competition_id=1, season_id=2
        )

        assert classement["position"].max() <= len(classement)
        assert get_team_position(classement, 1) is not None

    def test_premiere_journee_sans_classement(self, deux_saisons):
        """Avant le premier match d'une saison, aucun classement n'existe."""
        classement = calculate_standings(
            deux_saisons, pd.Timestamp("2024-08-16"), competition_id=1, season_id=2
        )

        assert classement.empty
        assert get_team_position(classement, 1) is None

    def test_egalite_departagee_par_la_difference_de_buts(self):
        """À points égaux, la meilleure différence de buts passe devant."""
        rows = [
            _match(1, 1, "2023-09-02", 1, 3, 5, 0),  # équipe 1 : +5
            _match(2, 1, "2023-09-02", 2, 4, 1, 0),  # équipe 2 : +1
        ]
        classement = calculate_standings(
            pd.DataFrame(rows), pd.Timestamp("2023-09-10"), competition_id=1, season_id=1
        )

        assert classement.loc[1, "points"] == classement.loc[2, "points"] == 3
        assert get_team_position(classement, 1) == 1
        assert get_team_position(classement, 2) == 2


class TestJoursDeRepos:
    def test_la_treve_estivale_n_est_pas_du_repos(self, deux_saisons):
        """Le dernier match de la saison précédente ne fixe pas le repos."""
        repos = calculate_rest_days(
            deux_saisons, team_id=1, match_date=pd.Timestamp("2024-08-17"), season_id=2
        )

        assert repos is None

    def test_sans_borne_la_treve_est_comptee(self, deux_saisons):
        """Comportement sans season_id : c'est le défaut corrigé."""
        repos = calculate_rest_days(deux_saisons, team_id=1, match_date=pd.Timestamp("2024-08-17"))

        assert repos is not None
        assert repos > 300  # onze mois de « repos »

    def test_repos_normal_en_cours_de_saison(self, deux_saisons):
        """Dans la saison, l'écart au match précédent est bien mesuré."""
        repos = calculate_rest_days(
            deux_saisons, team_id=1, match_date=pd.Timestamp("2024-08-24"), season_id=2
        )

        assert repos == 7

    def test_difference_indisponible_si_un_cote_manque(self, deux_saisons):
        """Sans repos des deux côtés, la différence reste indisponible."""
        features = calculate_rest_features(
            deux_saisons, 1, 2, pd.Timestamp("2024-08-17"), season_id=2
        )

        assert features["home_rest_days"] is None
        assert features["rest_days_difference"] is None


class TestEloEntreSaisons:
    def test_le_rating_est_ramene_vers_la_moyenne(self, deux_saisons):
        """Un rating gagné en saison 1 n'est pas conservé intégralement."""
        saison_1 = deux_saisons[deux_saisons["season_id"] == 1]
        elo_fin_saison_1 = _compute_elo_before(saison_1, team_id=1, season_id=1)

        elo_debut_saison_2 = _compute_elo_before(saison_1, team_id=1, season_id=2)

        assert elo_fin_saison_1 > DEFAULT_ELO
        assert DEFAULT_ELO < elo_debut_saison_2 < elo_fin_saison_1
        assert elo_debut_saison_2 == pytest.approx(regress_towards_mean(elo_fin_saison_1))

    def test_continuite_a_l_interieur_d_une_saison(self, deux_saisons):
        """Aucune régression ne s'applique entre deux matchs de la même saison."""
        avant = deux_saisons[deux_saisons["match_date"] < pd.Timestamp("2023-09-16")]
        elo = _compute_elo_before(avant, team_id=1, season_id=1)

        assert elo > DEFAULT_ELO

    def test_regression_conserve_la_part_annoncee(self):
        """La formule conserve exactement la part déclarée de l'écart."""
        assert regress_towards_mean(1700) == pytest.approx(DEFAULT_ELO + SEASON_CARRY_OVER * 200)
        assert regress_towards_mean(DEFAULT_ELO) == DEFAULT_ELO

    def test_equipe_sans_historique(self):
        """Une équipe inconnue démarre à la valeur par défaut."""
        vide = pd.DataFrame(
            columns=[
                "id",
                "competition_id",
                "season_id",
                "match_date",
                "home_team_id",
                "away_team_id",
                "home_goals",
                "away_goals",
            ]
        )
        assert _compute_elo_before(vide, team_id=99, season_id=1) == DEFAULT_ELO
