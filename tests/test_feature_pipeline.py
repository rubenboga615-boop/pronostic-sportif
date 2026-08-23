"""Tests du calcul en mémoire des features par match."""

import pandas as pd
import pytest

from pipelines.feature_pipeline import compute_match_features


def _prior_df() -> pd.DataFrame:
    """Cinq matchs antérieurs (avant 2024-03-01), trois équipes."""
    return pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "competition_id": [1, 1, 1, 1, 1],
        "match_date": pd.to_datetime([
            "2024-01-10", "2024-01-12", "2024-02-10", "2024-02-15", "2024-02-20",
        ]),
        "home_team_id": [1, 2, 3, 2, 3],
        "away_team_id": [3, 3, 1, 1, 2],
        "home_goals": [2, 1, 0, 1, 0],
        "away_goals": [0, 1, 3, 2, 1],
        "home_shots": [15, 10, 8, 9, 7],
        "away_shots": [5, 10, 14, 12, 11],
        "home_shots_on_target": [6, 4, 3, 4, 2],
        "away_shots_on_target": [2, 4, 7, 6, 5],
    })


def _target_match() -> pd.Series:
    """Match cible : équipe 1 (domicile) vs équipe 2 (extérieur)."""
    return pd.Series({
        "id": 100,
        "competition_id": 1,
        "season_id": 1,
        "match_date": pd.Timestamp("2024-03-01"),
        "home_team_id": 1,
        "away_team_id": 2,
        "home_goals": None,
        "away_goals": None,
    })


def _odds_df() -> pd.DataFrame:
    """Deux captures de cotes pour le match cible (2.0 -> 1.8)."""
    return pd.DataFrame({
        "match_id": [100, 100],
        "market": ["1N2", "1N2"],
        "selection": ["home", "home"],
        "odds": [2.0, 1.8],
        "captured_at": pd.to_datetime(["2024-02-01", "2024-02-28"]),
    })


class TestComputeMatchFeatures:
    def test_returns_exactly_home_and_away(self):
        result = compute_match_features(_target_match(), _prior_df(), _odds_df())
        assert set(result.keys()) == {"home", "away"}

    def test_no_future_leak(self):
        prior = _prior_df()
        # Match daté à la date cible (2024-03-01) avec des valeurs très différentes
        # (victoire 9-0 de l'équipe 1) : toute fuite modifierait visiblement
        # rest_days, elo_rating et goal_difference.
        future = pd.DataFrame({
            "id": [999],
            "competition_id": [1],
            "match_date": pd.to_datetime(["2024-03-01"]),
            "home_team_id": [1],
            "away_team_id": [2],
            "home_goals": [9],
            "away_goals": [0],
            "home_shots": [20],
            "away_shots": [0],
            "home_shots_on_target": [10],
            "away_shots_on_target": [0],
        })
        with_future = pd.concat([prior, future], ignore_index=True)

        baseline = compute_match_features(_target_match(), prior, _odds_df())
        result = compute_match_features(_target_match(), with_future, _odds_df())

        for side in ("home", "away"):
            assert result[side]["rest_days"] == baseline[side]["rest_days"]
            assert result[side]["elo_rating"] == baseline[side]["elo_rating"]
            assert result[side]["goal_difference"] == baseline[side]["goal_difference"]

    def test_rest_days_side_selection(self):
        result = compute_match_features(_target_match(), _prior_df(), _odds_df())
        # Équipe 1 : dernier match 2024-02-15 -> 15 jours.
        # Équipe 2 : dernier match 2024-02-20 -> 10 jours.
        assert result["home"]["rest_days"] == 15
        assert result["away"]["rest_days"] == 10

    def test_odds_movement_duplicated(self):
        result = compute_match_features(_target_match(), _prior_df(), _odds_df())
        assert result["home"]["odds_movement"] == pytest.approx(-0.1)
        assert result["away"]["odds_movement"] == pytest.approx(-0.1)

    def test_goal_difference_available(self):
        result = compute_match_features(_target_match(), _prior_df(), _odds_df())
        # Équipe 1 : gf=7, ga=1 -> +6 ; équipe 2 : gf=3, ga=3 -> 0.
        assert result["home"]["goal_difference"] == 6
        assert result["away"]["goal_difference"] == 0
        # La valeur est un entier (colonne Feature.goal_difference = Integer).
        assert isinstance(result["home"]["goal_difference"], int)
        assert isinstance(result["away"]["goal_difference"], int)

    def test_goal_difference_none_when_no_history(self):
        empty = _prior_df().iloc[0:0]
        result = compute_match_features(_target_match(), empty, _odds_df())
        assert result["home"]["goal_difference"] is None
        assert result["away"]["goal_difference"] is None

    def test_elo_rating_side_selection(self):
        # Un seul match antérieur : équipe 1 bat équipe 2 (2-0).
        prior = pd.DataFrame({
            "id": [1],
            "competition_id": [1],
            "match_date": pd.to_datetime(["2024-02-15"]),
            "home_team_id": [1],
            "away_team_id": [2],
            "home_goals": [2],
            "away_goals": [0],
            "home_shots": [10],
            "away_shots": [5],
            "home_shots_on_target": [5],
            "away_shots_on_target": [2],
        })
        result = compute_match_features(_target_match(), prior, _odds_df())
        # Vainqueur : 1500 + 32*(1 - 0.5) = 1516 ; perdant : 1500 + 32*(0 - 0.5) = 1484.
        assert result["home"]["elo_rating"] == pytest.approx(1516.0)
        assert result["away"]["elo_rating"] == pytest.approx(1484.0)

    def test_unavailable_columns_are_none(self):
        result = compute_match_features(_target_match(), _prior_df(), _odds_df())
        for side in ("home", "away"):
            assert result[side]["opponent_strength"] is None
            assert result[side]["xg_avg_5"] is None
            assert result[side]["xga_avg_5"] is None
            assert result[side]["npxg_avg_5"] is None
            assert result[side]["injury_impact"] is None
