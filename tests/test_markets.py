"""Tests de dérivation des marchés."""

import pytest

from models.market_derivation import (
    derive_1n2,
    derive_btts,
    derive_double_chance,
    derive_over_under,
)
from models.poisson import compute_score_matrix


@pytest.fixture
def score_matrix():
    """Matrice de scores de test."""
    return compute_score_matrix(1.5, 1.2)


class Test1N2:
    def test_three_selections(self, score_matrix):
        results = derive_1n2(score_matrix)
        assert len(results) == 3

    def test_probabilities_sum_to_one(self, score_matrix):
        results = derive_1n2(score_matrix)
        total = sum(r["probability"] for r in results)
        assert total == pytest.approx(1.0, abs=0.001)

    def test_fair_odds_positive(self, score_matrix):
        results = derive_1n2(score_matrix)
        for r in results:
            assert r["fair_odds"] > 1.0


class TestDoubleChance:
    def test_three_selections(self, score_matrix):
        probs_1n2 = derive_1n2(score_matrix)
        results = derive_double_chance(probs_1n2)
        assert len(results) == 3

    def test_probabilities_sum_to_one(self, score_matrix):
        probs_1n2 = derive_1n2(score_matrix)
        results = derive_double_chance(probs_1n2)
        # Les double chances se recouvrent, leur somme > 1
        for r in results:
            assert 0 < r["probability"] <= 1.0


class TestOverUnder:
    def test_over_under_line(self, score_matrix):
        for line in [0.5, 1.5, 2.5, 3.5]:
            results = derive_over_under(score_matrix, line)
            assert len(results) == 2
            total = sum(r["probability"] for r in results)
            assert total == pytest.approx(1.0, abs=0.001)

    def test_over_05_is_high(self, score_matrix):
        """Over 0.5 devrait être élevé pour des lambdas > 1."""
        results = derive_over_under(score_matrix, 0.5)
        over_prob = next(r for r in results if "over" in r["selection"])["probability"]
        assert over_prob > 0.5


class TestBtts:
    def test_two_selections(self, score_matrix):
        results = derive_btts(score_matrix)
        assert len(results) == 2

    def test_probabilities_sum_to_one(self, score_matrix):
        results = derive_btts(score_matrix)
        total = sum(r["probability"] for r in results)
        assert total == pytest.approx(1.0, abs=0.001)
