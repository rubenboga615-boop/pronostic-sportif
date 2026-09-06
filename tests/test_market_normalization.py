"""Tests de la normalisation des identifiants de marchés (contrat public)."""

from models.market_assembly import (
    MARKET_TO_PUBLIC,
    PUBLIC_MARKETS,
    PUBLIC_SELECTIONS,
    PUBLIC_TO_MARKET,
    PUBLIC_TO_SELECTION,
    SELECTION_TO_PUBLIC,
    build_match_markets,
    normalize_prediction,
)

HOME = {"goals_for_avg_5": 1.8, "goals_against_avg_5": 0.9}
AWAY = {"goals_for_avg_5": 1.2, "goals_against_avg_5": 1.5}
AVG = 1.4

# Sorties internes représentatives de market_derivation.
INTERNAL = [
    {"market": "1n2", "selection": "home_win", "probability": 0.5, "fair_odds": 2.0},
    {"market": "1n2", "selection": "draw", "probability": 0.25, "fair_odds": 4.0},
    {"market": "1n2", "selection": "away_win", "probability": 0.25, "fair_odds": 4.0},
    {
        "market": "double_chance",
        "selection": "home_or_draw",
        "probability": 0.75,
        "fair_odds": 1.3333,
    },
    {"market": "over_under", "selection": "over_0.5", "probability": 0.9, "fair_odds": 1.1111},
    {"market": "over_under", "selection": "under_2.5", "probability": 0.6, "fair_odds": 1.6667},
    {"market": "btts", "selection": "yes", "probability": 0.55, "fair_odds": 1.8182},
]


class TestNormalizePrediction:
    def test_internal_maps_to_valid_public(self):
        for p in INTERNAL:
            out = normalize_prediction(p)
            assert out["market"] in PUBLIC_MARKETS
            assert out["selection"] in PUBLIC_SELECTIONS[out["market"]]

    def test_no_unknown_market_or_selection(self):
        markets = build_match_markets(HOME, AWAY, AVG)
        assert len(markets) == 16
        for p in markets:
            assert p["market"] in PUBLIC_MARKETS
            assert p["selection"] in PUBLIC_SELECTIONS[p["market"]]

    def test_probability_preserved(self):
        for p in INTERNAL:
            assert normalize_prediction(p)["probability"] == p["probability"]

    def test_fair_odds_preserved(self):
        for p in INTERNAL:
            assert normalize_prediction(p)["fair_odds"] == p["fair_odds"]

    def test_16_predictions(self):
        assert len(build_match_markets(HOME, AWAY, AVG)) == 16

    def test_1n2_uses_home_draw_away(self):
        markets = build_match_markets(HOME, AWAY, AVG)
        assert {p["selection"] for p in markets if p["market"] == "1N2"} == {
            "home",
            "draw",
            "away",
        }

    def test_double_chance_three_combinations(self):
        markets = build_match_markets(HOME, AWAY, AVG)
        assert {p["selection"] for p in markets if p["market"] == "double_chance"} == {
            "home_or_draw",
            "home_or_away",
            "draw_or_away",
        }

    def test_over_under_four_lines(self):
        markets = build_match_markets(HOME, AWAY, AVG)
        ou = {p["selection"] for p in markets if p["market"] == "over_under"}
        assert ou == {
            "over_0.5",
            "under_0.5",
            "over_1.5",
            "under_1.5",
            "over_2.5",
            "under_2.5",
            "over_3.5",
            "under_3.5",
        }

    def test_btts_yes_no(self):
        markets = build_match_markets(HOME, AWAY, AVG)
        assert {p["selection"] for p in markets if p["market"] == "BTTS"} == {
            "yes",
            "no",
        }

    def test_mapping_order_independent(self):
        # Les noms (market, selection) produits sont fixes, indépendants des
        # valeurs d'entrée : deux jeux de features différents produisent les
        # mêmes 16 couples.
        r1 = build_match_markets({"goals_for_avg_5": 2.0}, {"goals_against_avg_5": 0.5}, AVG)
        r2 = build_match_markets({"goals_for_avg_5": 0.5}, {"goals_against_avg_5": 2.0}, AVG)
        keys1 = sorted((p["market"], p["selection"]) for p in r1)
        keys2 = sorted((p["market"], p["selection"]) for p in r2)
        assert keys1 == keys2
        assert len(keys1) == 16

    def test_mapping_reversible(self):
        for internal_market, public_market in MARKET_TO_PUBLIC.items():
            assert PUBLIC_TO_MARKET[public_market] == internal_market
        for internal_sel, public_sel in SELECTION_TO_PUBLIC.items():
            assert PUBLIC_TO_SELECTION[public_sel] == internal_sel
