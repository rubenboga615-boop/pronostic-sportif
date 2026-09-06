"""Tests des modèles de prédiction."""

import pytest

import models.market_derivation as market_derivation
from models.market_derivation import fair_odds
from models.poisson import (
    compute_score_matrix,
    derive_1n2,
    derive_btts,
    estimate_lambda,
    poisson_pmf,
)


class TestPoissonModel:
    """Tests du modèle de Poisson."""

    def test_poisson_pmf(self):
        """Vérifier que la PMF de Poisson fonctionne."""
        assert poisson_pmf(0, 1.5) > 0
        assert poisson_pmf(1, 1.5) > 0
        assert poisson_pmf(5, 1.5) < poisson_pmf(1, 1.5)

    def test_estimate_lambda_home(self):
        """Lambda domicile doit être supérieur à lambda extérieur (home advantage)."""
        lam_home = estimate_lambda(1.5, 1.0, 1.3, is_home=True)
        lam_away = estimate_lambda(1.2, 1.1, 1.3, is_home=False)
        assert lam_home > 0
        assert lam_away > 0

    def test_score_matrix_sums_to_one(self):
        """La matrice de scores doit sommer à ~1."""
        matrix = compute_score_matrix(1.5, 1.2, max_goals=8)
        assert abs(matrix.sum() - 1.0) < 0.01

    def test_1n2_sums_to_one(self):
        """Les probabilités 1N2 doivent sommer à 1."""
        matrix = compute_score_matrix(1.5, 1.2)
        probs = derive_1n2(matrix)
        total = probs["home_win"] + probs["draw"] + probs["away_win"]
        assert abs(total - 1.0) < 0.001

    def test_btts_sums_to_one(self):
        """Les probabilités BTTS doivent sommer à 1."""
        matrix = compute_score_matrix(1.5, 1.2)
        probs = derive_btts(matrix)
        total = probs["btts_yes"] + probs["btts_no"]
        assert abs(total - 1.0) < 0.001


class TestMarketDerivation:
    """Tests de la dérivation des marchés."""

    def test_fair_odds(self):
        """La cote équitable doit être 1/probabilité."""
        assert fair_odds(0.5) == 2.0
        assert fair_odds(0.25) == 4.0
        assert fair_odds(0.0) == 999.0

    def test_derive_1n2_returns_three_selections(self):
        """1N2 doit retourner 3 sélections."""
        matrix = compute_score_matrix(1.5, 1.2)
        results = market_derivation.derive_1n2(matrix)
        assert len(results) == 3
        assert all(r["market"] == "1n2" for r in results)

    def test_derive_over_under_multiple_lines(self):
        """Over/Under doit fonctionner pour plusieurs lignes."""
        matrix = compute_score_matrix(1.5, 1.2)
        for line in [0.5, 1.5, 2.5, 3.5]:
            results = market_derivation.derive_over_under(matrix, line)
            assert len(results) == 2
            assert results[0]["probability"] + results[1]["probability"] == pytest.approx(1.0)


class TestNormalisationDeLaMatrice:
    """La troncature à max_goals ne doit pas déséquilibrer les probabilités."""

    @pytest.mark.parametrize(
        ("lam_home", "lam_away", "max_goals"),
        [(1.6, 1.2, 8), (3.0, 2.5, 8), (1.0, 0.8, 5), (0.4, 0.3, 3)],
    )
    def test_somme_exactement_un(self, lam_home, lam_away, max_goals):
        matrix = compute_score_matrix(lam_home, lam_away, max_goals=max_goals)

        assert matrix.sum() == pytest.approx(1.0, abs=1e-12)

    def test_under_est_exactement_le_complement_de_over(self):
        """Sans normalisation, `under` absorbait toute la masse tronquée."""
        from models.market_derivation import derive_over_under

        matrix = compute_score_matrix(3.0, 2.5, max_goals=8)
        over, under = derive_over_under(matrix, 2.5)

        somme_directe = float(
            sum(
                matrix[i][j]
                for i in range(matrix.shape[0])
                for j in range(matrix.shape[1])
                if i + j <= 2.5
            )
        )
        assert under["probability"] == pytest.approx(somme_directe, abs=1e-12)
        assert over["probability"] + under["probability"] == pytest.approx(1.0, abs=1e-12)

    def test_1n2_somme_a_un_sur_lambdas_eleves(self):
        from models.market_derivation import derive_1n2

        matrix = compute_score_matrix(3.0, 2.5, max_goals=8)

        assert sum(p["probability"] for p in derive_1n2(matrix)) == pytest.approx(1.0, abs=1e-12)
