"""Tests des variables de première mi-temps.

Quinze des trente et une sélections d'un match portent sur la première période,
et rien ne la décrivait. Ces tests vérifient que le calcul est juste, qu'il ne
regarde jamais l'avenir, et qu'il refuse de produire un chiffre plausible quand
il n'a pas de quoi le fonder.
"""

from datetime import datetime

import pandas as pd
import pytest

from features.half_time import (
    MINIMUM_OBSERVATIONS,
    calculate_half_time_features,
)

CIBLE = pd.Timestamp(datetime(2024, 3, 1))


def _match(mid, jour, home, away, hg_ht, ag_ht, saison=1):
    return {
        "id": mid,
        "season_id": saison,
        "match_date": pd.Timestamp(datetime(2024, 1, jour)),
        "home_team_id": home,
        "away_team_id": away,
        "home_ht_goals": hg_ht,
        "away_ht_goals": ag_ht,
    }


class TestCalculs:
    @pytest.fixture
    def historique(self):
        """L'équipe 1 : quatre matchs à domicile, trois à l'extérieur.

        À domicile elle mène 3 fois sur 4 (1-0, 2-0, 0-0, 1-0).
        À l'extérieur elle ne mène jamais (0-1, 1-1, 0-2).
        """
        return pd.DataFrame(
            [
                _match(1, 2, 1, 9, 1, 0),
                _match(2, 4, 1, 8, 2, 0),
                _match(3, 6, 1, 7, 0, 0),
                _match(4, 8, 1, 6, 1, 0),
                _match(5, 10, 5, 1, 1, 0),
                _match(6, 12, 4, 1, 1, 1),
                _match(7, 14, 3, 1, 2, 0),
            ]
        )

    def test_taux_de_tete_separes_par_lieu(self, historique):
        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert f["ht_home_win_rate"] == pytest.approx(3 / 4)
        assert f["ht_away_win_rate"] == pytest.approx(0.0)

    def test_taux_de_nul_sur_l_ensemble(self, historique):
        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        # 0-0 à domicile, 1-1 à l'extérieur : deux nuls sur sept.
        assert f["ht_draw_rate"] == pytest.approx(2 / 7)

    def test_moyennes_de_buts_marques(self, historique):
        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert f["ht_home_goals_avg"] == pytest.approx((1 + 2 + 0 + 1) / 4)
        assert f["ht_away_goals_avg"] == pytest.approx((0 + 1 + 0) / 3)

    def test_total_et_lignes_over(self, historique):
        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        totaux = [1, 2, 0, 1, 1, 2, 2]
        assert f["ht_total_goals_avg"] == pytest.approx(sum(totaux) / 7)
        assert f["ht_over_05_rate"] == pytest.approx(6 / 7)
        assert f["ht_over_15_rate"] == pytest.approx(3 / 7)
        assert f["ht_over_25_rate"] == pytest.approx(0.0)
        assert f["ht_over_35_rate"] == pytest.approx(0.0)

    def test_le_point_de_vue_est_celui_de_l_equipe(self, historique):
        """L'équipe 3 a mené 2-0 à la pause chez elle, contre l'équipe 1."""
        f = calculate_half_time_features(historique, team_id=3, match_date=CIBLE)

        # Un seul match : sous le minimum, donc rien n'est affirmé.
        assert f["ht_home_win_rate"] is None


class TestAntiFuite:
    def test_un_match_posterieur_est_ignore(self):
        """Le match du futur inverserait tous les taux s'il était compté."""
        historique = pd.DataFrame(
            [
                _match(1, 2, 1, 9, 1, 0),
                _match(2, 4, 1, 8, 1, 0),
                _match(3, 6, 1, 7, 1, 0),
                # Postérieur à la cible : 0-5, et il ne doit rien changer.
                {
                    "id": 4,
                    "season_id": 1,
                    "match_date": pd.Timestamp(datetime(2024, 6, 1)),
                    "home_team_id": 1,
                    "away_team_id": 6,
                    "home_ht_goals": 0,
                    "away_ht_goals": 5,
                },
            ]
        )

        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert f["ht_home_win_rate"] == pytest.approx(1.0)
        assert f["ht_over_35_rate"] == pytest.approx(0.0)

    def test_un_match_du_jour_meme_est_exclu(self):
        """La borne est stricte : deux matchs du même jour ne s'informent pas."""
        historique = pd.DataFrame(
            [
                _match(1, 2, 1, 9, 1, 0),
                _match(2, 4, 1, 8, 1, 0),
                _match(3, 6, 1, 7, 1, 0),
                {
                    "id": 4,
                    "season_id": 1,
                    "match_date": CIBLE,
                    "home_team_id": 1,
                    "away_team_id": 6,
                    "home_ht_goals": 0,
                    "away_ht_goals": 4,
                },
            ]
        )

        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert f["ht_home_win_rate"] == pytest.approx(1.0)

    def test_la_saison_borne_la_fenetre(self):
        """Un taux à cheval sur la trêve décrit un effectif qui n'existe plus."""
        historique = pd.DataFrame(
            [
                _match(1, 2, 1, 9, 3, 0, saison=1),
                _match(2, 4, 1, 8, 3, 0, saison=1),
                _match(3, 6, 1, 7, 3, 0, saison=1),
                _match(4, 8, 1, 6, 0, 0, saison=2),
                _match(5, 10, 1, 5, 0, 0, saison=2),
                _match(6, 12, 1, 4, 0, 0, saison=2),
            ]
        )

        saison_2 = calculate_half_time_features(
            historique, team_id=1, match_date=CIBLE, season_id=2
        )

        # Seuls les trois matchs de la saison 2 comptent : aucun but marqué.
        assert saison_2["ht_home_goals_avg"] == pytest.approx(0.0)
        assert saison_2["ht_over_05_rate"] == pytest.approx(0.0)


class TestDonneesManquantes:
    def test_sous_le_minimum_tout_reste_none(self):
        historique = pd.DataFrame(
            [_match(i, 2 * i + 2, 1, 9, 1, 0) for i in range(MINIMUM_OBSERVATIONS - 1)]
        )

        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert all(valeur is None for valeur in f.values())

    def test_un_match_sans_score_de_mi_temps_sort_du_denominateur(self):
        """Sinon il serait compté comme un 0-0 et écraserait les moyennes."""
        historique = pd.DataFrame(
            [
                _match(1, 2, 1, 9, 2, 0),
                _match(2, 4, 1, 8, 2, 0),
                _match(3, 6, 1, 7, 2, 0),
                _match(4, 8, 1, 6, None, None),
            ]
        )

        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert f["ht_home_goals_avg"] == pytest.approx(2.0)
        assert f["ht_over_15_rate"] == pytest.approx(1.0)

    def test_sans_colonnes_de_mi_temps_rien_n_est_invente(self):
        historique = pd.DataFrame(
            [
                {
                    "id": 1,
                    "season_id": 1,
                    "match_date": pd.Timestamp(datetime(2024, 1, 2)),
                    "home_team_id": 1,
                    "away_team_id": 9,
                }
            ]
        )

        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert all(valeur is None for valeur in f.values())

    def test_historique_vide(self):
        f = calculate_half_time_features(pd.DataFrame(), team_id=1, match_date=CIBLE)

        assert all(valeur is None for valeur in f.values())

    def test_un_seul_lieu_renseigne_ne_bloque_pas_le_reste(self):
        """Trois matchs à domicile, aucun dehors : les taux à l'extérieur sont
        None, les autres existent."""
        historique = pd.DataFrame([_match(i, 2 * i + 2, 1, 9 - i, 1, 0) for i in range(4)])

        f = calculate_half_time_features(historique, team_id=1, match_date=CIBLE)

        assert f["ht_home_win_rate"] == pytest.approx(1.0)
        assert f["ht_away_win_rate"] is None
        assert f["ht_away_goals_avg"] is None
        assert f["ht_total_goals_avg"] == pytest.approx(1.0)
