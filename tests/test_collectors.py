"""Tests des collecteurs de données."""

import pytest
from collectors.football_data.league_config import get_league_codes, get_league_name, get_all_seasons
from collectors.football_data.team_normalizer import normalize_team_name, get_all_canonical_names


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

    def test_get_all_seasons(self):
        seasons = get_all_seasons()
        assert "1516" in seasons
        assert "2425" in seasons
        assert "2526" in seasons
        assert seasons == sorted(seasons)


class TestTeamNormalizer:
    """Tests du normalisateur de noms d'équipes."""

    def test_normalize_known_team_e0(self):
        assert normalize_team_name("Man City", "E0") == "Manchester City"
        assert normalize_team_name("Man Utd", "E0") == "Manchester Utd"
        assert normalize_team_name("Wolves", "E0") == "Wolverhampton"

    def test_normalize_known_team_sp1(self):
        assert normalize_team_name("Atletico Madrid", "SP1") == "Atletico Madrid"
        assert normalize_team_name("Atl Madrid", "SP1") == "Atletico Madrid"

    def test_normalize_known_team_i1(self):
        assert normalize_team_name("Inter", "I1") == "Inter Milan"
        assert normalize_team_name("AC Milan", "I1") == "AC Milan"

    def test_normalize_known_team_d1(self):
        assert normalize_team_name("Bayern Munich", "D1") == "Bayern Munich"
        assert normalize_team_name("FC Bayern", "D1") == "Bayern Munich"

    def test_normalize_known_team_f1(self):
        assert normalize_team_name("PSG", "F1") == "Paris Saint-Germain"
        assert normalize_team_name("Paris SG", "F1") == "Paris Saint-Germain"

    def test_normalize_unknown_team(self):
        # Nom inconnu → retourne tel quel
        result = normalize_team_name("Unknown FC", "E0")
        assert result == "Unknown FC"

    def test_normalize_none_returns_none(self):
        assert normalize_team_name(None, "E0") is None

    def test_normalize_empty_string(self):
        assert normalize_team_name("", "E0") == ""

    def test_normalize_whitespace(self):
        assert normalize_team_name("  Man City  ", "E0") == "Manchester City"

    def test_get_all_canonical_names(self):
        names = get_all_canonical_names()
        assert "E0" in names
        assert "Manchester City" in names["E0"]
        assert "Barcelona" in names["SP1"]

    def test_normalize_man_united(self):
        assert normalize_team_name("Man United", "E0") == "Manchester Utd"

    def test_normalize_man_united_aliases_converge(self):
        # Les trois variantes convergent vers le même nom canonique
        assert normalize_team_name("Man United", "E0") == normalize_team_name("Man Utd", "E0")
        assert normalize_team_name("Manchester United", "E0") == "Manchester Utd"

    def test_normalize_luton(self):
        assert normalize_team_name("Luton", "E0") == "Luton Town"
        assert normalize_team_name("Luton Town", "E0") == "Luton Town"

    def test_normalize_brentford(self):
        assert normalize_team_name("Brentford", "E0") == "Brentford"

    def test_man_united_not_confused_with_man_city(self):
        # Manchester United et Manchester City restent deux clubs distincts
        assert normalize_team_name("Man United", "E0") != normalize_team_name("Man City", "E0")
        assert normalize_team_name("Man United", "E0") == "Manchester Utd"
        assert normalize_team_name("Man City", "E0") == "Manchester City"

    def test_normalize_ipswich(self):
        assert normalize_team_name("Ipswich", "E0") == "Ipswich Town"

    def test_normalize_ipswich_town_identity(self):
        assert normalize_team_name("Ipswich Town", "E0") == "Ipswich Town"
