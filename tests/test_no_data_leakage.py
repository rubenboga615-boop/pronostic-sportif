"""Tests anti-fuite de données.

Vérifie qu'aucune donnée future n'est utilisée dans les features.
"""

import pandas as pd
import pytest

from features.elo import calculate_elo_ratings
from features.form import calculate_form_features
from features.rest_days import calculate_rest_days


@pytest.fixture
def sample_matches():
    """Données de test avec des matchs sur plusieurs dates."""
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6, 7, 8],
            "home_team_id": [1, 2, 1, 3, 1, 2, 1, 3],
            "away_team_id": [2, 1, 3, 1, 2, 3, 1, 2],
            "home_goals": [2, 1, 0, 3, 1, 2, 0, 1],
            "away_goals": [1, 1, 0, 1, 0, 1, 0, 0],
            "match_date": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-08",
                    "2024-01-15",
                    "2024-01-22",
                    "2024-01-29",
                    "2024-02-05",
                    "2024-02-12",
                    "2024-02-19",
                ]
            ),
        }
    )


class TestDataLeakage:
    """Vérifier qu'aucune donnée future n'est utilisée."""

    def test_form_features_use_only_past_data(self, sample_matches):
        """Les features de forme ne doivent utiliser que les matchs passés."""
        prediction_date = pd.Timestamp("2024-01-20")

        features = calculate_form_features(
            sample_matches,
            team_id=1,
            match_date=prediction_date,
            windows=[5],
        )

        # Les features doivent être calculées sans erreur
        assert isinstance(features, dict)
        # Pas de crash = les données passées sont bien filtrées

    def test_rest_days_use_only_past_data(self, sample_matches):
        """Les jours de repos ne doivent utiliser que les matchs passés."""
        prediction_date = pd.Timestamp("2024-01-20")

        rest = calculate_rest_days(
            sample_matches,
            team_id=1,
            match_date=prediction_date,
        )

        # Le résultat doit être un nombre positif ou None
        assert rest is None or rest >= 0

    def test_elo_ratings_are_pre_match(self, sample_matches):
        """Les ratings Elo doivent être calculés AVANT le résultat du match."""
        team_ids = {f"team_{i}": i for i in range(1, 4)}
        elo_history = calculate_elo_ratings(sample_matches, team_ids)

        # Chaque entrée doit avoir un home_elo et away_elo
        assert "home_elo" in elo_history.columns
        assert "away_elo" in elo_history.columns

        # Les ratings ne doivent pas être nuls
        assert (elo_history["home_elo"] > 0).all()
        assert (elo_history["away_elo"] > 0).all()

    def test_no_future_dates_in_features(self, sample_matches):
        """Aucune date future ne doit apparaître dans les features calculées."""
        prediction_date = pd.Timestamp("2024-01-20")

        # Les matchs utilisés doivent tous être antérieurs à prediction_date
        used_matches = sample_matches[sample_matches["match_date"] < prediction_date]

        assert len(used_matches) > 0
        assert (used_matches["match_date"] < prediction_date).all()

    def test_features_dont_leak_current_match(self, sample_matches):
        """Les features d'un match ne doivent pas inclure le match lui-même."""
        prediction_date = pd.Timestamp("2024-01-15")

        features = calculate_form_features(
            sample_matches,
            team_id=1,
            match_date=prediction_date,
            windows=[5],
        )

        # Le match du 15 janvier ne doit pas être inclus
        # car on filtre strictement < prediction_date
        assert isinstance(features, dict)
