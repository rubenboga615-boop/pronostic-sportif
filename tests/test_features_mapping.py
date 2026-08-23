"""Tests du mapping des features vers le modèle Feature, et du marché 1N2."""

import pandas as pd
import pytest

from features.mapping import map_features_to_columns
from features.odds_movement import calculate_odds_movement


def _odds_frame(market: str) -> pd.DataFrame:
    """Deux captures de cotes pour un même match/marché."""
    return pd.DataFrame({
        "match_id": [1, 1],
        "market": [market, market],
        "selection": ["home", "home"],
        "odds": [2.0, 1.8],
        "captured_at": pd.to_datetime(["2024-01-01", "2024-01-02"]),
    })


class TestOddsMovementMarket:
    def test_default_market_is_canonical_1N2(self):
        """Le défaut doit correspondre au marché stocké en base : '1N2'."""
        result = calculate_odds_movement(_odds_frame("1N2"), match_id=1)
        assert result["odds_movement"] is not None
        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)

    def test_lowercase_1n2_does_not_match_stored_data(self):
        """Un marché en minuscules ne doit pas matcher la donnée '1N2'."""
        result = calculate_odds_movement(_odds_frame("1N2"), match_id=1, market="1n2")
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
        """Une colonne sans source ne doit pas être remplacée par une valeur valide."""
        mapped = map_features_to_columns({})
        assert mapped["data_completeness"] is None
        assert mapped["opponent_strength"] is None

    def test_unmapped_keys_are_not_persisted(self):
        """Les sorties sans colonne dédiée ne doivent pas fuiter dans le mapping."""
        raw = {
            "form_wins_5": 2,
            "clean_sheets_5": 1,
            "home_rest_days": 8,
            "comparable_teams": [11, 1, 3],
        }
        mapped = map_features_to_columns(raw)
        assert "form_wins_5" not in mapped
        assert "clean_sheets_5" not in mapped
        assert "home_rest_days" not in mapped
        assert "comparable_teams" not in mapped
