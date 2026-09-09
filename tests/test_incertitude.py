"""Tests des intervalles de confiance sur un rendement.

L'enjeu n'est pas la précision décimale du bootstrap mais ce qu'il autorise à
dire. Un intervalle qui contient zéro interdit de conclure sur le signe du
rendement — c'est exactement ce que le projet avait manqué en annonçant un
Over/Under « positif » à +3,97 % sur 262 paris.
"""

from __future__ import annotations

import numpy as np

from evaluation.incertitude import gains_unitaires, intervalle_de_confiance_roi


class TestGainsUnitaires:
    def test_un_pari_gagne_rapporte_la_cote_moins_la_mise(self):
        assert gains_unitaires(["won"], [2.5]).tolist() == [1.5]

    def test_un_pari_perdu_coute_la_mise(self):
        assert gains_unitaires(["lost"], [2.5]).tolist() == [-1.0]

    def test_un_pari_annule_est_neutre(self):
        """Une ligne remboursée ne doit ni gonfler ni pénaliser le rendement."""
        assert gains_unitaires(["void"], [2.5]).tolist() == [0.0]

    def test_les_index_desalignes_ne_decalent_pas_les_cotes(self):
        """Les lots viennent de filtres pandas : leurs index ont des trous."""
        import pandas as pd

        issues = pd.Series(["won", "lost"], index=[7, 42])
        cotes = pd.Series([3.0, 2.0], index=[7, 42])

        assert gains_unitaires(issues, cotes).tolist() == [2.0, -1.0]


class TestIntervalle:
    def test_un_lot_vide_ne_leve_pas(self):
        resultat = intervalle_de_confiance_roi([], [])
        assert resultat["paris"] == 0
        assert resultat["roi_pct"] is None
        assert resultat["significatif"] is False

    def test_le_roi_ponctuel_est_la_moyenne_des_gains(self):
        # deux gagnants à 2,0 et deux perdants : mise 4, retour 4, ROI nul.
        resultat = intervalle_de_confiance_roi(["won", "won", "lost", "lost"], [2.0, 2.0, 2.0, 2.0])
        assert resultat["roi_pct"] == 0.0

    def test_l_intervalle_encadre_le_point(self):
        issues = ["won", "lost"] * 200
        cotes = [2.2] * 400
        resultat = intervalle_de_confiance_roi(issues, cotes)

        assert resultat["borne_basse"] <= resultat["roi_pct"] <= resultat["borne_haute"]

    def test_une_perte_franche_et_massive_est_declaree_significative(self):
        """Tout perdre sur 2 000 paris : le signe ne fait aucun doute."""
        resultat = intervalle_de_confiance_roi(["lost"] * 2000, [2.0] * 2000)

        assert resultat["roi_pct"] == -100.0
        assert resultat["significatif"] is True
        assert resultat["borne_haute"] < 0

    def test_un_faible_effectif_ne_permet_pas_de_conclure(self):
        """Le cas qui a piégé le projet : un ROI positif sur trop peu de paris."""
        generateur = np.random.default_rng(1)
        issues = ["won" if x else "lost" for x in generateur.random(60) < 0.5]
        resultat = intervalle_de_confiance_roi(issues, [2.1] * 60)

        assert resultat["significatif"] is False
        assert resultat["borne_basse"] < 0 < resultat["borne_haute"]

    def test_l_intervalle_se_resserre_quand_les_paris_se_multiplient(self):
        petit = intervalle_de_confiance_roi(["won", "lost"] * 50, [2.0] * 100)
        grand = intervalle_de_confiance_roi(["won", "lost"] * 2000, [2.0] * 4000)

        largeur = lambda r: r["borne_haute"] - r["borne_basse"]  # noqa: E731
        assert largeur(grand) < largeur(petit)

    def test_la_mesure_est_rejouable_a_l_identique(self):
        """Deux lectures du même backtest ne doivent pas diverger."""
        arguments = (["won", "lost", "won"] * 100, [1.9] * 300)
        premier = intervalle_de_confiance_roi(*arguments)
        second = intervalle_de_confiance_roi(*arguments)

        assert premier == second

    def test_un_niveau_plus_exigeant_elargit_l_intervalle(self):
        issues = ["won", "lost"] * 300
        cotes = [2.0] * 600
        large = intervalle_de_confiance_roi(issues, cotes, niveau=0.99)
        etroit = intervalle_de_confiance_roi(issues, cotes, niveau=0.80)

        assert large["borne_basse"] < etroit["borne_basse"]
        assert large["borne_haute"] > etroit["borne_haute"]
