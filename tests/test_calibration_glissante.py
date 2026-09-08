"""Tests de la calibration réajustée au fil du temps.

Le risque dominant est unique et connu du projet : un calibrateur ajusté sur
des matchs postérieurs à celui qu'il corrige donne des résultats flatteurs et
faux, sans lever d'erreur. C'est le défaut que le dépôt a déjà rencontré trois
fois — cotes de clôture dans les features, classement inter-saisons, filtre xG
sur la date de collecte. Il est donc testé en premier, et par un mouchard :
un historique empoisonné qui trahirait toute lecture du futur.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.calibration_glissante import calibrer_en_glissant, erreur_de_calibration


def _jeu(n: int, debut: str = "2023-08-01", graine: int = 7) -> pd.DataFrame:
    """Prédictions réglées, une par jour, avec un biais de surconfiance."""
    rng = np.random.default_rng(graine)
    p = rng.uniform(0.05, 0.95, n)
    return pd.DataFrame(
        {
            "match_date": pd.date_range(debut, periods=n, freq="D"),
            "probability": p,
            # Le modèle annonce p, la réalité vaut 0,8 p : surconfiance nette.
            "gagnant": (rng.uniform(size=n) < p * 0.8).astype(int),
        }
    )


class TestAntiFuite:
    def test_aucun_match_futur_n_entre_dans_la_calibration(self):
        """Mouchard : la seconde moitié est empoisonnée par des issues
        inversées. Si elle influençait la première, la calibration de celle-ci
        s'en trouverait changée."""
        propre = _jeu(800)
        empoisonne = propre.copy()
        moitie = len(empoisonne) // 2
        empoisonne.loc[moitie:, "gagnant"] = 1 - empoisonne.loc[moitie:, "gagnant"]

        a = calibrer_en_glissant(propre, minimum=200)
        b = calibrer_en_glissant(empoisonne, minimum=200)

        debut_a = a.head(moitie)["p_calibree"].to_numpy()
        debut_b = b.head(moitie)["p_calibree"].to_numpy()
        assert np.allclose(debut_a, debut_b), "des matchs futurs ont influencé le passé"

    def test_les_matchs_du_meme_jour_ne_s_informent_pas(self):
        """Deux matchs d'une même journée doivent recevoir la même correction :
        aucun des deux ne peut avoir servi à calibrer l'autre."""
        base = _jeu(400)
        # Deux lignes de plus, même jour, même probabilité, issues opposées.
        jour = base["match_date"].max() + pd.Timedelta(days=1)
        paire = pd.DataFrame(
            {
                "match_date": [jour, jour],
                "probability": [0.5, 0.5],
                "gagnant": [1, 0],
            }
        )
        df = pd.concat([base, paire], ignore_index=True)

        sortie = calibrer_en_glissant(df, minimum=200)
        derniers = sortie[sortie["match_date"] == jour]["p_calibree"].to_numpy()

        assert derniers[0] == pytest.approx(derniers[1])

    def test_les_premieres_lignes_restent_brutes(self):
        """Tant que l'historique est trop court, mieux vaut ne rien corriger
        qu'apprendre le bruit de quelques dizaines de matchs."""
        df = _jeu(500)

        sortie = calibrer_en_glissant(df, minimum=300)

        debut = sortie.head(100)
        assert (debut["p_calibree"] == debut["probability"]).all()
        assert not debut["calibree"].any()


class TestEfficacite:
    def test_la_calibration_reduit_l_erreur_sur_la_partie_calibree(self):
        """Sur un biais stable, la correction doit se voir."""
        df = _jeu(1500)
        sortie = calibrer_en_glissant(df, minimum=300)
        calibrees = sortie[sortie["calibree"]]

        avant = erreur_de_calibration(calibrees["probability"], calibrees["gagnant"])
        apres = erreur_de_calibration(calibrees["p_calibree"], calibrees["gagnant"])

        assert apres < avant

    def test_une_fenetre_bornee_oublie_le_passe_lointain(self):
        """Une fenêtre glissante ne doit pas donner le même résultat qu'une
        fenêtre croissante : c'est toute sa raison d'être."""
        df = _jeu(1200)

        croissante = calibrer_en_glissant(df, minimum=300)
        glissante = calibrer_en_glissant(df, minimum=300, fenetre=400)

        assert not np.allclose(
            croissante["p_calibree"].to_numpy(), glissante["p_calibree"].to_numpy()
        )

    def test_les_probabilites_restent_dans_zero_un(self):
        sortie = calibrer_en_glissant(_jeu(900), minimum=300)

        assert sortie["p_calibree"].between(0.0, 1.0).all()


class TestRobustesse:
    def test_un_jeu_vide_ne_leve_pas(self):
        vide = pd.DataFrame(columns=["match_date", "probability", "gagnant"])

        sortie = calibrer_en_glissant(vide)

        assert sortie.empty
        assert "p_calibree" in sortie.columns

    def test_une_seule_issue_observee_laisse_les_probabilites_brutes(self):
        """Rien à apprendre quand tout le monde gagne."""
        df = _jeu(600)
        df["gagnant"] = 1

        sortie = calibrer_en_glissant(df, minimum=200)

        assert (sortie["p_calibree"] == sortie["probability"]).all()

    def test_l_ordre_d_entree_ne_change_pas_le_resultat(self):
        """Le tri chronologique est fait par la fonction, pas par l'appelant."""
        df = _jeu(700)
        melange = df.sample(frac=1.0, random_state=3).reset_index(drop=True)

        a = calibrer_en_glissant(df, minimum=300)
        b = calibrer_en_glissant(melange, minimum=300)

        assert np.allclose(a["p_calibree"].to_numpy(), b["p_calibree"].to_numpy())
