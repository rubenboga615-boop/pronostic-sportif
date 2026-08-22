"""Tests des collecteurs de données."""

import pytest
from collectors.football_data.league_config import get_league_codes, get_league_name


class TestLeagueConfig:
    """Tests de la configuration des championnats."""

    def test_get_league_codes(self):
        codes = get_league_codes()
        assert "E0" in codes
        assert "SP1" in codes
        assert "I1" in codes
        assert "D1" in codes
        assert "F1" in codes

    def test_get_league_name(self):
        assert get_league_name("E0") == "Premier League"
        assert get_league_name("SP1") == "La Liga"
        assert get_league_name("I1") == "Serie A"
        assert get_league_name("D1") == "Bundesliga"
        assert get_league_name("F1") == "Ligue 1"

    def test_get_league_name_unknown(self):
        assert get_league_name("XX") == "XX"
