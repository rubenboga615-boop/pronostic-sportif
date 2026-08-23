"""Tests de l'assemblage en mémoire des marchés de match entier."""

import pytest

from models.market_assembly import (
    OVER_UNDER_LINES,
    build_match_markets,
    estimate_match_lambdas,
)

HOME = {"goals_for_avg_5": 1.8, "goals_against_avg_5": 0.9}
AWAY = {"goals_for_avg_5": 1.2, "goals_against_avg_5": 1.5}
AVG = 1.4


@pytest.fixture
def markets():
    return build_match_markets(HOME, AWAY, AVG)


class TestBuildMatchMarkets:
    def test_16_predictions(self, markets):
        assert len(markets) == 16

    def test_probability_in_0_1(self, markets):
        for p in markets:
            assert 0.0 <= p["probability"] <= 1.0

    def test_fair_odds_coherent(self, markets):
        for p in markets:
            if p["probability"] > 0:
                assert p["fair_odds"] == pytest.approx(1.0 / p["probability"], abs=1e-3)
            else:
                assert p["fair_odds"] == 999.0

    def test_1n2_sum(self, markets):
        s = sum(p["probability"] for p in markets if p["market"] == "1n2")
        assert s == pytest.approx(1.0, abs=1e-3)

    @pytest.mark.parametrize("line", [0.5, 1.5, 2.5, 3.5])
    def test_over_under_sum(self, markets, line):
        s = sum(
            p["probability"]
            for p in markets
            if p["market"] == "over_under" and p["selection"] in (f"over_{line}", f"under_{line}")
        )
        assert s == pytest.approx(1.0, abs=1e-3)

    def test_btts_sum(self, markets):
        s = sum(p["probability"] for p in markets if p["market"] == "btts")
        assert s == pytest.approx(1.0, abs=1e-3)

    def test_fallback_null_features(self):
        result = build_match_markets(
            {"goals_for_avg_5": None}, {"goals_against_avg_5": None}, AVG
        )
        assert len(result) == 16
        lh, la = estimate_match_lambdas(
            {"goals_for_avg_5": None}, {"goals_against_avg_5": None}, AVG
        )
        # Fallback neutre : lambda_home = AVG * (1 + 0.25), lambda_away = AVG.
        assert lh == pytest.approx(AVG * 1.25)
        assert la == pytest.approx(AVG)

    def test_reject_non_positive_avg(self):
        with pytest.raises(ValueError):
            build_match_markets(HOME, AWAY, 0)
        with pytest.raises(ValueError):
            build_match_markets(HOME, AWAY, -1.0)

    def test_lambdas_positive(self):
        lh, la = estimate_match_lambdas(HOME, AWAY, AVG)
        assert lh > 0
        assert la > 0

    def test_target_score_not_used(self):
        # Le helper ne lit pas home_goals/away_goals du match cible.
        base = build_match_markets(HOME, AWAY, AVG)
        with_score = build_match_markets(
            {**HOME, "home_goals": 5, "away_goals": 0},
            {**AWAY, "home_goals": 0, "away_goals": 5},
            AVG,
        )
        assert base == with_score

    def test_market_and_selection_names(self, markets):
        assert {p["market"] for p in markets} == {
            "1n2",
            "double_chance",
            "over_under",
            "btts",
        }
        assert {p["selection"] for p in markets if p["market"] == "1n2"} == {
            "home_win",
            "draw",
            "away_win",
        }
        assert {p["selection"] for p in markets if p["market"] == "double_chance"} == {
            "home_or_draw",
            "home_or_away",
            "draw_or_away",
        }
        assert {p["selection"] for p in markets if p["market"] == "btts"} == {"yes", "no"}
        ou = {p["selection"] for p in markets if p["market"] == "over_under"}
        expected_ou = {f"over_{l}" for l in OVER_UNDER_LINES} | {
            f"under_{l}" for l in OVER_UNDER_LINES
        }
        assert ou == expected_ou

    def test_home_advantage(self):
        lh_low, _ = estimate_match_lambdas(HOME, AWAY, AVG, home_advantage=0.25)
        lh_high, _ = estimate_match_lambdas(HOME, AWAY, AVG, home_advantage=0.5)
        assert lh_high > lh_low
