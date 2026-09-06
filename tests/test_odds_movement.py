"""Tests du mouvement de cote — et de son étanchéité à la fuite de données.

La règle testée ici est celle de `PROJECT_SPEC.md` : une cote de clôture n'entre
jamais dans une variable prédictive. Ces tests vérifient que le calcul refuse
tout relevé postérieur à la date de coupure, tout relevé de clôture, et tout
relevé dont l'instant de capture est inconnu.
"""

import pandas as pd
import pytest

from features.odds_movement import calculate_odds_movement

COUP_D_ENVOI = pd.Timestamp("2024-03-10 15:00")


def _releves(rows) -> pd.DataFrame:
    """Construire une table de relevés à partir de tuples lisibles."""
    return pd.DataFrame(
        rows,
        columns=[
            "match_id",
            "market",
            "selection",
            "bookmaker",
            "odds",
            "captured_at",
            "is_closing",
        ],
    )


def _pre_match(odds, jours_avant, bookmaker="B365", selection="home", market="1N2"):
    return (
        1,
        market,
        selection,
        bookmaker,
        odds,
        COUP_D_ENVOI - pd.Timedelta(days=jours_avant),
        0,
    )


def _cloture(odds, selection="home", market="1N2"):
    return (1, market, selection, "B365_close", odds, COUP_D_ENVOI, 1)


def _ouverture_non_datee(odds, selection="home", market="1N2"):
    """Cote d'ouverture telle que Football-Data la livre : sans horodatage."""
    return (1, market, selection, "B365", odds, None, 0)


class TestEtancheite:
    def test_la_cloture_n_est_jamais_utilisee(self):
        """Deux relevés dont un de clôture ne forment pas un mouvement."""
        frame = _releves([_pre_match(2.0, 5), _cloture(1.6)])

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        assert result["odds_movement"] is None

    def test_un_releve_non_date_est_inutilisable(self):
        """Un instant de capture inconnu n'est jamais supposé antérieur."""
        frame = _releves([_ouverture_non_datee(2.0), _pre_match(1.9, 2)])

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        assert result["odds_movement"] is None

    def test_un_releve_posterieur_a_la_coupure_est_ecarte(self):
        """Une cote capturée après la coupure ne peut pas être connue."""
        frame = _releves(
            [
                _pre_match(2.0, 5),
                _pre_match(1.9, 3),
                (1, "1N2", "home", "B365", 1.5, COUP_D_ENVOI + pd.Timedelta(hours=1), 0),
            ]
        )

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        # Le mouvement s'arrête au dernier relevé pré-coupure : 2.0 -> 1.9.
        assert result["odds_movement"] == pytest.approx((1.9 - 2.0) / 2.0)

    def test_un_releve_a_la_coupure_exacte_est_ecarte(self):
        """La comparaison est stricte : à la seconde du coup d'envoi, c'est trop tard."""
        frame = _releves([_pre_match(2.0, 5), (1, "1N2", "home", "B365", 1.7, COUP_D_ENVOI, 0)])

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        assert result["odds_movement"] is None

    def test_donnees_football_data_ne_produisent_aucun_mouvement(self):
        """Ouverture non datée + clôture : la seule forme livrée par la source."""
        frame = _releves([_ouverture_non_datee(2.0), _cloture(1.6)])

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        assert result["odds_movement"] is None

    def test_coupure_obligatoire(self):
        """Sans date de coupure, le calcul refuse de s'exécuter."""
        with pytest.raises(ValueError, match="cutoff est obligatoire"):
            calculate_odds_movement(_releves([_pre_match(2.0, 5)]), match_id=1, cutoff=None)

        with pytest.raises(TypeError):
            calculate_odds_movement(_releves([_pre_match(2.0, 5)]), match_id=1)


class TestCalcul:
    def test_mouvement_entre_deux_releves_pre_match(self):
        frame = _releves([_pre_match(2.0, 5), _pre_match(1.8, 1)])

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)

    def test_premier_et_dernier_releve_seulement(self):
        """Les relevés intermédiaires ne changent pas les bornes du mouvement."""
        frame = _releves(
            [_pre_match(2.0, 9), _pre_match(2.4, 6), _pre_match(2.2, 4), _pre_match(1.8, 1)]
        )

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)

    def test_un_seul_releve_ne_fait_pas_un_mouvement(self):
        frame = _releves([_pre_match(2.0, 5)])

        assert (
            calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)["odds_movement"] is None
        )

    def test_deux_bookmakers_ne_forment_pas_une_paire(self):
        """Comparer deux bookmakers mesurerait leurs marges, pas un mouvement."""
        frame = _releves([_pre_match(2.0, 5, bookmaker="B365"), _pre_match(1.8, 1, bookmaker="BW")])

        assert (
            calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)["odds_movement"] is None
        )

    def test_bookmaker_le_mieux_fourni_retenu(self):
        """Le bookmaker offrant le plus de relevés est suivi par défaut."""
        frame = _releves(
            [
                _pre_match(2.0, 5, bookmaker="B365"),
                _pre_match(1.8, 1, bookmaker="B365"),
                _pre_match(9.0, 3, bookmaker="BW"),
            ]
        )

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)

        assert result["odds_movement"] == pytest.approx((1.8 - 2.0) / 2.0)

    def test_bookmaker_explicite_respecte(self):
        frame = _releves(
            [
                _pre_match(2.0, 5, bookmaker="B365"),
                _pre_match(1.8, 1, bookmaker="B365"),
                _pre_match(3.0, 5, bookmaker="PS"),
                _pre_match(2.4, 1, bookmaker="PS"),
            ]
        )

        result = calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI, bookmaker="PS")

        assert result["odds_movement"] == pytest.approx((2.4 - 3.0) / 3.0)

    def test_selections_independantes(self):
        frame = _releves(
            [
                _pre_match(2.0, 5, selection="home"),
                _pre_match(1.8, 1, selection="home"),
                _pre_match(10.0, 5, selection="away"),
                _pre_match(5.0, 1, selection="away"),
            ]
        )

        assert calculate_odds_movement(frame, match_id=1, selection="home", cutoff=COUP_D_ENVOI)[
            "odds_movement"
        ] == pytest.approx((1.8 - 2.0) / 2.0)
        assert calculate_odds_movement(frame, match_id=1, selection="away", cutoff=COUP_D_ENVOI)[
            "odds_movement"
        ] == pytest.approx((5.0 - 10.0) / 10.0)

    def test_marche_stocke_en_base_est_le_defaut(self):
        """Le défaut est « 1N2 », tel qu'écrit par l'import ; « 1n2 » ne matche pas."""
        frame = _releves([_pre_match(2.0, 5), _pre_match(1.8, 1)])

        assert (
            calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)["odds_movement"]
            is not None
        )
        assert (
            calculate_odds_movement(frame, match_id=1, market="1n2", cutoff=COUP_D_ENVOI)[
                "odds_movement"
            ]
            is None
        )

    def test_autre_match_ignore(self):
        frame = _releves([_pre_match(2.0, 5), _pre_match(1.8, 1)])

        assert (
            calculate_odds_movement(frame, match_id=42, cutoff=COUP_D_ENVOI)["odds_movement"]
            is None
        )

    def test_cote_nulle_ou_negative_ecartee(self):
        frame = _releves([_pre_match(0.0, 5), _pre_match(1.8, 1)])

        # Le relevé à 0 est écarté : il ne reste qu'un relevé exploitable.
        assert (
            calculate_odds_movement(frame, match_id=1, cutoff=COUP_D_ENVOI)["odds_movement"] is None
        )

    def test_table_vide(self):
        vide = _releves([]).iloc[0:0]

        assert (
            calculate_odds_movement(vide, match_id=1, cutoff=COUP_D_ENVOI)["odds_movement"] is None
        )
