"""Tests du mapping des features vers le modèle Feature, et du marché 1N2."""

import pandas as pd
import pytest

from features.mapping import map_features_to_columns
from features.odds_movement import calculate_odds_movement

COUP_D_ENVOI = pd.Timestamp("2024-01-10")


def _odds_frame(market: str, selection: str = "home") -> pd.DataFrame:
    """Deux relevés pré-match horodatés (B365), seule forme exploitable."""
    return pd.DataFrame(
        {
            "match_id": [1, 1],
            "market": [market, market],
            "selection": [selection, selection],
            "bookmaker": ["B365", "B365"],
            "is_closing": [0, 0],
            "odds": [2.0, 1.8],
            "captured_at": pd.to_datetime(["2024-01-01", "2024-01-05"]),
        }
    )


class TestOddsMovementMarket:
    def test_default_market_is_canonical_1N2(self):  # noqa: N802 — « 1N2 » est un identifiant de marché
        """Le défaut doit correspondre au marché stocké en base : '1N2'."""
        result = calculate_odds_movement(_odds_frame("1N2"), match_id=1, cutoff=COUP_D_ENVOI)
        assert result["odds_movement"] is not None
        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)

    def test_lowercase_1n2_does_not_match_stored_data(self):
        """Un marché en minuscules ne doit pas matcher la donnée '1N2'."""
        result = calculate_odds_movement(
            _odds_frame("1N2"), match_id=1, market="1n2", cutoff=COUP_D_ENVOI
        )
        assert result["odds_movement"] is None


class TestMapping:
    def test_direct_columns_are_mapped(self):
        raw = {
            "form_points_5": 7,
            "goals_for_avg_5": 1.2,
            "shots_avg_5": 11.2,
            "shots_on_target_avg_5": 3.6,
            "odds_movement": -0.02,
            "league_position": 12,
        }
        mapped = map_features_to_columns(raw)
        assert mapped["form_points_5"] == 7
        assert mapped["goals_for_avg_5"] == 1.2
        assert mapped["shots_avg_5"] == 11.2
        assert mapped["league_position"] == 12

    def test_unavailable_xg_and_injury_stay_none(self):
        """xG et blessures indisponibles restent None (jamais 0.0)."""
        mapped = map_features_to_columns({})
        assert mapped["xg_avg_5"] is None
        assert mapped["xga_avg_5"] is None
        assert mapped["npxg_avg_5"] is None
        assert mapped["injury_impact"] is None

    def test_no_silent_valid_substitution(self):
        """Une variable sans source ne doit pas être remplacée par une valeur valide."""
        mapped = map_features_to_columns({})

        for colonne in (
            "opponent_strength",
            "xg_avg_5",
            "injury_impact",
            "ht_draw_rate",
            "ht_over_25_rate",
            "clean_sheets_5",
            "rest_days_diff",
        ):
            assert mapped[colonne] is None, colonne

    def test_data_completeness_est_une_mesure_pas_une_substitution(self):
        """Seule exception à la règle : elle décrit la ligne, pas l'équipe.

        `data_completeness` ne dit rien du football. Elle dit quelle part des
        colonnes a pu être renseignée — 0 sur une ligne vide est une information
        vraie, et c'est ce qui permettra de distinguer une prédiction bien
        fondée d'une prédiction faite à l'aveugle.
        """
        assert map_features_to_columns({})["data_completeness"] == pytest.approx(0.0)

        garnie = map_features_to_columns(
            {"form_points_5": 9, "goals_for_avg_5": 1.6, "home_elo": 1510.0}
        )
        assert 0.0 < garnie["data_completeness"] < 1.0

    def test_unmapped_keys_are_not_persisted(self):
        """Les sorties sans colonne dédiée ne doivent pas fuiter dans le mapping."""
        raw = {
            "form_wins_5": 2,
            "goals_for_avg_10": 1.4,
            "rest_days_difference": 2,
            "home_elo": 1510.0,
            "comparable_teams": [11, 1, 3],
        }
        mapped = map_features_to_columns(raw)

        # Ces clés n'ont pas de colonne : elles sont ignorées, pas persistées.
        assert "form_wins_5" not in mapped
        assert "goals_for_avg_10" not in mapped
        assert "comparable_teams" not in mapped
        # Les clés brutes ne fuitent pas non plus quand la colonne porte un
        # autre nom : rest_days_difference alimente rest_days_diff.
        assert "rest_days_difference" not in mapped
        assert "home_elo" not in mapped

    def test_les_quatre_colonnes_autrefois_orphelines_sont_alimentees(self):
        """Aucune colonne du schéma ne doit rester sans écrivain.

        `home_away_goals_*`, `opponent_strength` et `data_completeness` étaient
        déclarées au modèle et qu'aucun code n'écrivait : elles restaient nulles
        sur toute la base, en laissant croire à une donnée existante.
        """
        raw = {
            "home_goals_for_avg": 2.1,
            "home_goals_against_avg": 0.8,
            "away_goals_for_avg": 0.9,
            "away_goals_against_avg": 1.7,
            "opponent_elo_avg_5": 1520.0,
        }

        domicile = map_features_to_columns(raw, side="home")
        exterieur = map_features_to_columns(raw, side="away")

        # Chaque ligne retient la moyenne du lieu où SON équipe joue ce match.
        assert domicile["home_away_goals_for_avg"] == pytest.approx(2.1)
        assert domicile["home_away_goals_against_avg"] == pytest.approx(0.8)
        assert exterieur["home_away_goals_for_avg"] == pytest.approx(0.9)
        assert exterieur["home_away_goals_against_avg"] == pytest.approx(1.7)

        assert domicile["opponent_strength"] == pytest.approx(1520.0)
        assert domicile["data_completeness"] > 0

    def test_l_ecart_de_repos_s_inverse_pour_l_equipe_exterieure(self):
        """Chaque ligne décrit son équipe : un écart positif veut toujours dire
        « mieux reposée que l'adversaire »."""
        raw = {"rest_days_difference": 3}

        assert map_features_to_columns(raw, side="home")["rest_days_diff"] == 3
        assert map_features_to_columns(raw, side="away")["rest_days_diff"] == -3

    def test_les_dix_variables_de_mi_temps_sont_mappees(self):
        raw = {
            "ht_home_win_rate": 0.6,
            "ht_away_win_rate": 0.2,
            "ht_draw_rate": 0.3,
            "ht_home_goals_avg": 0.9,
            "ht_away_goals_avg": 0.4,
            "ht_total_goals_avg": 1.2,
            "ht_over_05_rate": 0.7,
            "ht_over_15_rate": 0.4,
            "ht_over_25_rate": 0.1,
            "ht_over_35_rate": 0.0,
        }

        mapped = map_features_to_columns(raw)

        for cle, valeur in raw.items():
            assert mapped[cle] == pytest.approx(valeur), cle

    def test_rest_days_side_selection(self):
        raw = {"home_rest_days": 8, "away_rest_days": 5}
        assert map_features_to_columns(raw, side="home")["rest_days"] == 8
        assert map_features_to_columns(raw, side="away")["rest_days"] == 5

    def test_elo_rating_side_selection(self):
        raw = {"home_elo": 1510.0, "away_elo": 1490.0}
        assert map_features_to_columns(raw, side="home")["elo_rating"] == 1510.0
        assert map_features_to_columns(raw, side="away")["elo_rating"] == 1490.0

    def test_odds_movement_duplicated(self):
        raw = {"odds_movement": -0.02}
        assert map_features_to_columns(raw, side="home")["odds_movement"] == -0.02
        assert map_features_to_columns(raw, side="away")["odds_movement"] == -0.02

    def test_goal_difference_mapped_or_none(self):
        assert map_features_to_columns({"goal_difference": 7})["goal_difference"] == 7
        assert map_features_to_columns({})["goal_difference"] is None

    def test_opponent_strength_stays_none(self):
        assert map_features_to_columns({})["opponent_strength"] is None

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            map_features_to_columns({}, side="invalid")
