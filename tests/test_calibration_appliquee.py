"""Tests de l'application d'une calibration à des prédictions structurées.

Le piège de cette étape est discret : la calibration déforme chaque probabilité
indépendamment, si bien que les trois sélections d'un 1N2 cessent de sommer à 1.
Une probabilité qui ne somme pas fausse l'edge, la cote équitable, et toute
probabilité jointe calculée ensuite — sans qu'aucune erreur ne soit levée.
"""

from __future__ import annotations

import numpy as np
import pytest

# Importé ici, et non dans les tests : le conftest crée les tables depuis
# `Base.metadata`, qui doit connaître tous les modèles avant son premier
# `create_all`. Un import tardif ferait échouer le nettoyage de fin de test.
import pipelines.prediction_pipeline as pipeline
from models.calibration import Calibrateur
from models.calibration_appliquee import appliquer_calibration


def _identite() -> Calibrateur:
    """Calibrateur Platt neutre : a=1, b=0 laisse le logit inchangé."""
    return Calibrateur(methode="platt", parametres={"a": 1.0, "b": 0.0}, n_ajustement=100)


def _ecrasant() -> Calibrateur:
    """Calibrateur qui tasse les probabilités vers le centre."""
    return Calibrateur(methode="platt", parametres={"a": 0.5, "b": 0.0}, n_ajustement=100)


def _1n2(p_home: float, p_draw: float, p_away: float) -> list[dict]:
    return [
        {"market": "1N2", "selection": "home", "probability": p_home, "fair_odds": 1 / p_home},
        {"market": "1N2", "selection": "draw", "probability": p_draw, "fair_odds": 1 / p_draw},
        {"market": "1N2", "selection": "away", "probability": p_away, "fair_odds": 1 / p_away},
    ]


class TestRenormalisation:
    def test_un_groupe_exclusif_somme_a_un_apres_calibration(self):
        """Le cœur du module : sans cela, l'edge et la cote équitable mentent."""
        sortie = appliquer_calibration(_1n2(0.5, 0.3, 0.2), {"1N2": _ecrasant()})

        assert sum(p["probability"] for p in sortie) == pytest.approx(1.0)

    def test_l_ordre_des_probabilites_est_conserve(self):
        """Une calibration monotone ne doit pas réordonner les sélections."""
        sortie = appliquer_calibration(_1n2(0.5, 0.3, 0.2), {"1N2": _ecrasant()})

        probabilites = [p["probability"] for p in sortie]
        assert probabilites == sorted(probabilites, reverse=True)

    def test_la_renormalisation_peut_etre_desactivee(self):
        sortie = appliquer_calibration(
            _1n2(0.5, 0.3, 0.2), {"1N2": _ecrasant()}, renormaliser=False
        )

        assert sum(p["probability"] for p in sortie) != pytest.approx(1.0)

    def test_un_groupe_incomplet_n_est_pas_renormalise(self):
        """Renormaliser sur une partie du groupe fausserait au lieu de corriger."""
        partiel = [
            {"market": "1N2", "selection": "home", "probability": 0.5, "fair_odds": 2.0},
            {"market": "1N2", "selection": "draw", "probability": 0.3, "fair_odds": 3.3},
        ]

        sortie = appliquer_calibration(partiel, {"1N2": _identite()})

        assert sum(p["probability"] for p in sortie) == pytest.approx(0.8, abs=1e-6)

    def test_la_double_chance_n_est_pas_renormalisee(self):
        """Deux sélections sur trois gagnent à chaque match : aucune partition,
        donc rien à normaliser."""
        entree = [
            {"market": "double_chance", "selection": "1X", "probability": 0.7, "fair_odds": 1.4},
            {"market": "double_chance", "selection": "12", "probability": 0.8, "fair_odds": 1.25},
            {"market": "double_chance", "selection": "X2", "probability": 0.5, "fair_odds": 2.0},
        ]

        sortie = appliquer_calibration(entree, {"double_chance": _identite()})

        assert sum(p["probability"] for p in sortie) == pytest.approx(2.0, abs=1e-6)


class TestCoherence:
    def test_la_cote_equitable_suit_la_probabilite(self):
        """Publier un prix qui ne correspond plus à la probabilité affichée
        juste à côté serait incohérent."""
        sortie = appliquer_calibration(_1n2(0.5, 0.3, 0.2), {"1N2": _ecrasant()})

        for p in sortie:
            assert p["fair_odds"] == pytest.approx(1.0 / p["probability"])

    def test_les_predictions_recues_ne_sont_pas_modifiees(self):
        """Le `fair_odds` d'origine doit rester consultable pour comparer."""
        entree = _1n2(0.5, 0.3, 0.2)

        appliquer_calibration(entree, {"1N2": _ecrasant()})

        assert entree[0]["probability"] == 0.5

    def test_un_marche_sans_calibrateur_reste_brut(self):
        """Mieux vaut une probabilité brute qu'une correction apprise ailleurs."""
        entree = _1n2(0.5, 0.3, 0.2) + [
            {"market": "BTTS", "selection": "yes", "probability": 0.6, "fair_odds": 1.67},
            {"market": "BTTS", "selection": "no", "probability": 0.4, "fair_odds": 2.5},
        ]

        sortie = appliquer_calibration(entree, {"1N2": _ecrasant()})

        btts = [p for p in sortie if p["market"] == "BTTS"]
        assert [p["probability"] for p in btts] == [0.6, 0.4]

    def test_sans_calibrateur_le_lot_est_rendu_tel_quel(self):
        entree = _1n2(0.5, 0.3, 0.2)

        for vide in (None, {}):
            sortie = appliquer_calibration(entree, vide)
            assert [p["probability"] for p in sortie] == [0.5, 0.3, 0.2]

    def test_chaque_marche_recoit_son_propre_calibrateur(self):
        """1N2 et Over/Under n'ont ni la même distribution ni le même biais."""
        entree = _1n2(0.5, 0.3, 0.2) + [
            {
                "market": "over_under",
                "selection": "over_2.5",
                "probability": 0.5,
                "fair_odds": 2.0,
            },
            {
                "market": "over_under",
                "selection": "under_2.5",
                "probability": 0.5,
                "fair_odds": 2.0,
            },
        ]

        sortie = appliquer_calibration(entree, {"1N2": _ecrasant(), "over_under": _identite()})

        ou = [p for p in sortie if p["market"] == "over_under"]
        assert [p["probability"] for p in ou] == pytest.approx([0.5, 0.5])
        assert sum(p["probability"] for p in sortie if p["market"] == "1N2") == pytest.approx(1.0)


class TestChargement:
    def test_l_absence_de_calibrateur_ne_leve_pas(self, tmp_path):
        """Un modèle non calibré doit continuer sur ses probabilités brutes :
        c'est le comportement d'avant la calibration, pas une erreur."""
        from models.calibration_appliquee import charger_calibrateurs

        assert charger_calibrateurs("version-inexistante", registry_dir=str(tmp_path)) == {}


class TestIntegrationPipeline:
    def test_le_pipeline_applique_la_calibration_avant_de_persister(self):
        """D-10 interdit de retoucher une probabilité persistée : la
        calibration doit intervenir avant l'écriture."""
        import inspect

        source = inspect.getsource(pipeline.generate_match_predictions)
        assert "appliquer_calibration" in source
        assert source.index("appliquer_calibration") < source.index("persist_predictions(")

    def test_le_pipeline_valorise_apres_avoir_predit(self):
        """Une prédiction sans prix ne produit ni edge ni rendement."""
        import inspect

        source = inspect.getsource(pipeline.run_prediction_pipeline)
        assert "valoriser_toutes_les_predictions" in source


class TestTransformation:
    def test_un_calibrateur_ecrasant_reduit_l_ecart_au_centre(self):
        sortie = appliquer_calibration(
            _1n2(0.8, 0.15, 0.05), {"1N2": _ecrasant()}, renormaliser=False
        )

        assert sortie[0]["probability"] < 0.8
        assert sortie[2]["probability"] > 0.05

    def test_les_probabilites_restent_dans_zero_un(self):
        rng = np.random.default_rng(20260908)
        entree = [
            {"market": "BTTS", "selection": f"s{i}", "probability": float(p), "fair_odds": 1 / p}
            for i, p in enumerate(rng.uniform(0.01, 0.99, 50))
        ]

        sortie = appliquer_calibration(entree, {"BTTS": _ecrasant()}, renormaliser=False)

        assert all(0.0 <= p["probability"] <= 1.0 for p in sortie)
