"""Tests des features."""

import pandas as pd
import pytest

from features.elo import calculate_elo_ratings, expected_score
from features.form import calculate_form_features
from features.home_away import calculate_home_away_features
from features.rest_days import calculate_rest_days, calculate_rest_features


@pytest.fixture
def sample_matches():
    """Données de test."""
    return pd.DataFrame(
        {
            "id": range(1, 11),
            "home_team_id": [1, 2, 1, 3, 1, 2, 1, 3, 1, 2],
            "away_team_id": [2, 1, 3, 1, 2, 3, 1, 2, 3, 1],
            "home_goals": [2, 1, 0, 3, 1, 2, 0, 1, 2, 0],
            "away_goals": [1, 1, 0, 1, 0, 1, 0, 0, 1, 0],
            "match_date": pd.date_range("2024-01-01", periods=10, freq="7D"),
        }
    )


class TestFormFeatures:
    def test_form_points(self, sample_matches):
        features = calculate_form_features(sample_matches, 1, pd.Timestamp("2024-03-01"), [5])
        assert "form_points_5" in features
        assert features["form_points_5"] >= 0

    def test_form_empty_history(self, sample_matches):
        features = calculate_form_features(sample_matches, 99, pd.Timestamp("2024-01-01"), [5])
        assert features == {}


class TestRestDays:
    def test_rest_days(self, sample_matches):
        rest = calculate_rest_days(sample_matches, 1, pd.Timestamp("2024-02-19"))
        assert rest is not None
        assert rest >= 0

    def test_rest_features(self, sample_matches):
        features = calculate_rest_features(sample_matches, 1, 2, pd.Timestamp("2024-02-19"))
        assert "home_rest_days" in features
        assert "away_rest_days" in features


class TestHomeAway:
    def test_home_away_features(self, sample_matches):
        features = calculate_home_away_features(sample_matches, 1, pd.Timestamp("2024-03-01"))
        assert "home_goals_for_avg" in features or "away_goals_for_avg" in features


class TestElo:
    def test_expected_score(self):
        assert expected_score(1500, 1500) == pytest.approx(0.5)
        assert expected_score(1600, 1400) > 0.5

    def test_elo_ratings(self, sample_matches):
        team_ids = {f"team_{i}": i for i in range(1, 4)}
        elo = calculate_elo_ratings(sample_matches, team_ids)
        assert len(elo) == len(sample_matches)
        assert "home_elo" in elo.columns
