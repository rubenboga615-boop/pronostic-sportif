"""Tests du règlement, de la valorisation, du backtest et de la calibration.

Ces quatre briques manquaient ou étaient fausses : la table `actual_results`
n'était écrite nulle part, `offered_odds` et `edge` n'étaient calculés nulle
part, le ROI du backtest se mesurait contre la cote du modèle lui-même — une
tautologie — et la calibration retournait ses entrées inchangées.
"""

from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import ActualResult, Base, Competition, Match, OddsSnapshot, Prediction, Team
from evaluation.backtest import (
    _accuracy_par_groupe,
    charger_evaluation,
    run_backtest,
    strategie_marche,
    strategie_naive,
)
from evaluation.metrics import auc, brier_score, erreur_de_calibration, log_loss, roi_simulation
from evaluation.pricing import (
    meilleures_cotes,
    probabilites_de_marche,
    valoriser_predictions,
)
from evaluation.settlement import persister_resultats, regler_match
from models.calibration import Calibrateur, ajuster_calibrateur, calibrate_probabilities


def _match(hg=2, ag=1, h1=1, a1=0, mid=1):
    return Match(
        id=mid,
        match_date=datetime(2024, 3, 1),
        home_team_id=1,
        away_team_id=2,
        home_goals=hg,
        away_goals=ag,
        home_ht_goals=h1,
        away_ht_goals=a1,
    )


class TestReglement:
    def test_victoire_a_domicile(self):
        issues = regler_match(_match(2, 1))

        assert issues[("1N2", "home")] == "won"
        assert issues[("1N2", "draw")] == "lost"
        assert issues[("1N2", "away")] == "lost"

    def test_double_chance_deux_gagnantes(self):
        """Sur une victoire à domicile, home_or_draw et home_or_away gagnent."""
        issues = regler_match(_match(2, 1))

        assert issues[("double_chance", "home_or_draw")] == "won"
        assert issues[("double_chance", "home_or_away")] == "won"
        assert issues[("double_chance", "draw_or_away")] == "lost"

    def test_match_nul(self):
        issues = regler_match(_match(1, 1))

        assert issues[("1N2", "draw")] == "won"
        assert issues[("double_chance", "home_or_draw")] == "won"
        assert issues[("double_chance", "draw_or_away")] == "won"
        assert issues[("double_chance", "home_or_away")] == "lost"

    def test_over_under_toutes_les_lignes(self):
        issues = regler_match(_match(2, 1))  # total = 3 buts

        assert issues[("over_under", "over_2.5")] == "won"
        assert issues[("over_under", "under_2.5")] == "lost"
        assert issues[("over_under", "over_3.5")] == "lost"
        assert issues[("over_under", "under_3.5")] == "won"
        assert issues[("over_under", "over_0.5")] == "won"

    def test_btts(self):
        assert regler_match(_match(2, 1))[("BTTS", "yes")] == "won"
        assert regler_match(_match(2, 0))[("BTTS", "yes")] == "lost"
        assert regler_match(_match(0, 0))[("BTTS", "no")] == "won"

    def test_mi_temps_la_plus_prolifique(self):
        # 1re mi-temps 1-0, score final 2-1 : une seconde période à 1-1.
        issues = regler_match(_match(2, 1, 1, 0))

        assert issues[("most_productive_half", "second_half")] == "won"
        assert issues[("most_productive_half", "first_half")] == "lost"

    def test_marches_de_mi_temps_absents_sans_score_de_mi_temps(self):
        """Un match sans HTHG n'est pas un match nul à la pause."""
        match = _match(2, 1)
        match.home_ht_goals = None

        issues = regler_match(match)

        assert not [cle for cle in issues if cle[0].endswith("_1H")]
        assert ("most_productive_half", "equal") not in issues

    def test_match_sans_score(self):
        match = _match()
        match.home_goals = None

        with pytest.raises(ValueError, match="sans score"):
            regler_match(match)

    def test_toutes_les_selections_sont_reglees(self):
        """Aucune sélection du contrat public ne doit rester sans issue."""
        from models.market_assembly import PUBLIC_SELECTIONS

        issues = regler_match(_match(2, 1, 1, 0))

        for marche, selections in PUBLIC_SELECTIONS.items():
            for selection in selections:
                assert (marche, selection) in issues, f"{marche}/{selection} non réglé"


class TestPersistanceDesResultats:
    @pytest.fixture
    def base(self, tmp_path):
        moteur = create_engine(f"sqlite:///{tmp_path}/t.db")
        Base.metadata.create_all(bind=moteur)
        with Session(moteur) as session:
            session.add_all([Team(id=1, canonical_name="A"), Team(id=2, canonical_name="B")])
            session.add(_match())
            session.commit()
        return moteur

    def test_les_lignes_sont_ecrites(self, base):
        with Session(base) as session:
            ecrits = persister_resultats(session, session.get(Match, 1))
            session.commit()

        with Session(base) as lecture:
            assert lecture.query(ActualResult).count() == ecrits
            assert ecrits == 31

    def test_deux_executions_ne_creent_pas_de_doublon(self, base):
        with Session(base) as session:
            match = session.get(Match, 1)
            persister_resultats(session, match)
            session.commit()
            persister_resultats(session, match)
            session.commit()

        with Session(base) as lecture:
            assert lecture.query(ActualResult).count() == 31


class TestValorisation:
    @pytest.fixture
    def base(self, tmp_path):
        moteur = create_engine(f"sqlite:///{tmp_path}/t.db")
        Base.metadata.create_all(bind=moteur)
        with Session(moteur) as session:
            session.add_all([Team(id=1, canonical_name="A"), Team(id=2, canonical_name="B")])
            session.add(_match())
            # Deux bookmakers, marges différentes : B365 à 6 %, PS à 2 %.
            for bookmaker, cotes in (
                ("B365", {"home": 2.00, "draw": 3.40, "away": 4.00}),
                ("PS", {"home": 2.10, "draw": 3.50, "away": 4.20}),
            ):
                for selection, cote in cotes.items():
                    session.add(
                        OddsSnapshot(
                            match_id=1,
                            bookmaker=bookmaker,
                            market="1N2",
                            selection=selection,
                            odds=cote,
                            is_closing=False,
                        )
                    )
            for selection, p in (("home", 0.55), ("draw", 0.25), ("away", 0.20)):
                session.add(
                    Prediction(
                        match_id=1,
                        model_version="v1",
                        market="1N2",
                        selection=selection,
                        probability=p,
                        fair_odds=1 / p,
                    )
                )
            session.commit()
        return moteur

    def test_la_meilleure_cote_est_retenue(self, base):
        with Session(base) as session:
            cotes = session.query(OddsSnapshot).all()

            meilleures = meilleures_cotes(cotes)

        assert meilleures[("1N2", "home")] == pytest.approx(2.10)  # PS, pas B365

    def test_les_probabilites_de_marche_somment_a_un(self, base):
        with Session(base) as session:
            probabilites = probabilites_de_marche(session.query(OddsSnapshot).all())

        total = sum(v for (marche, _), v in probabilites.items() if marche == "1N2")
        assert total == pytest.approx(1.0)

    def test_edge_et_cote_offerte_sont_ecrits(self, base):
        with Session(base) as session:
            valorisees = valoriser_predictions(session, 1, "v1")
            session.commit()

        assert valorisees == 3
        with Session(base) as lecture:
            home = lecture.query(Prediction).filter_by(selection="home").first()
            assert home.offered_odds == pytest.approx(2.10)
            assert home.edge is not None
            # Modèle à 0,55 contre un marché autour de 0,47 : edge positif.
            assert home.edge > 0

    def test_un_marche_incomplet_ne_donne_pas_de_probabilite(self, tmp_path):
        """Sans toutes les issues, la marge n'est pas mesurable."""
        moteur = create_engine(f"sqlite:///{tmp_path}/t2.db")
        Base.metadata.create_all(bind=moteur)
        with Session(moteur) as session:
            session.add(_match())
            session.add(
                OddsSnapshot(
                    match_id=1,
                    bookmaker="B365",
                    market="1N2",
                    selection="home",
                    odds=2.0,
                    is_closing=False,
                )
            )
            session.commit()
            probabilites = probabilites_de_marche(session.query(OddsSnapshot).all())

        assert probabilites == {}


class TestMetriques:
    def test_log_loss_penalise_la_confiance_fausse(self):
        prudent = log_loss([1, 0], [0.6, 0.4])
        temeraire = log_loss([1, 0], [0.99, 0.99])

        assert temeraire > prudent

    def test_brier_parfait(self):
        assert brier_score([1, 0, 1], [1.0, 0.0, 1.0]) == pytest.approx(0.0)

    def test_auc_classement_parfait(self):
        assert auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)

    def test_auc_classement_inverse(self):
        assert auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(0.0)

    def test_auc_indefinie_sans_variete(self):
        assert np.isnan(auc([1, 1, 1], [0.2, 0.5, 0.9]))

    def test_erreur_de_calibration_nulle_si_parfaite(self):
        y_prob = [0.1] * 100 + [0.9] * 100
        y_true = [0] * 90 + [1] * 10 + [0] * 10 + [1] * 90

        assert erreur_de_calibration(y_true, y_prob) == pytest.approx(0.0, abs=1e-9)

    def test_roi_utilise_la_cote_offerte(self):
        """Un pari gagnant à 3.0 rapporte deux unités pour une misée."""
        resultat = roi_simulation(["won"], [3.0])

        assert resultat["profit"] == pytest.approx(2.0)
        assert resultat["roi_pct"] == pytest.approx(200.0)

    def test_roi_negatif_sur_serie_perdante(self):
        resultat = roi_simulation(["lost"] * 10, [2.0] * 10)

        assert resultat["roi_pct"] == pytest.approx(-100.0)
        assert resultat["drawdown_max"] == pytest.approx(10.0)

    def test_remboursement_neutre(self):
        resultat = roi_simulation(["push"] * 5, [2.0] * 5)

        assert resultat["profit"] == pytest.approx(0.0)
        assert resultat["paris"] == 5

    def test_drawdown_mesure_depuis_le_sommet(self):
        # Deux gains puis trois pertes : sommet à +2, creux à -1.
        resultat = roi_simulation(["won", "won", "lost", "lost", "lost"], [2.0] * 5)

        assert resultat["drawdown_max"] == pytest.approx(3.0)

    def test_cote_invalide_ignoree(self):
        resultat = roi_simulation(["won", "won"], [1.0, 2.0])

        assert resultat["paris"] == 1


class TestBacktest:
    @pytest.fixture
    def base_complete(self, tmp_path):
        """Vingt matchs prédits, réglés et valorisés."""
        moteur = create_engine(f"sqlite:///{tmp_path}/t.db")
        Base.metadata.create_all(bind=moteur)
        with Session(moteur) as session:
            comp = Competition(id=1, name="L", country="C", provider_code="L")
            session.add(comp)
            session.add_all([Team(id=1, canonical_name="A"), Team(id=2, canonical_name="B")])
            session.flush()
            for i in range(20):
                domicile_gagne = i % 2 == 0
                match = Match(
                    id=i + 1,
                    competition_id=1,
                    season_id=1,
                    match_date=datetime(2024, 3, 1 + i),
                    home_team_id=1,
                    away_team_id=2,
                    home_goals=2 if domicile_gagne else 0,
                    away_goals=0 if domicile_gagne else 2,
                    home_ht_goals=1 if domicile_gagne else 0,
                    away_ht_goals=0 if domicile_gagne else 1,
                )
                session.add(match)
                session.flush()
                for selection, p, cote in (
                    ("home", 0.55, 2.0),
                    ("draw", 0.25, 3.5),
                    ("away", 0.20, 4.0),
                ):
                    session.add(
                        Prediction(
                            match_id=match.id,
                            model_version="v1",
                            market="1N2",
                            selection=selection,
                            probability=p,
                            fair_odds=1 / p,
                            offered_odds=cote,
                            edge=p - 1 / cote,
                        )
                    )
                persister_resultats(session, match)
            session.commit()
        return moteur

    def test_les_predictions_sont_appariees_aux_resultats(self, base_complete):
        with Session(base_complete) as session:
            df = charger_evaluation(session, "v1")

        assert len(df) == 60  # 20 matchs x 3 sélections
        assert df["gagnant"].sum() == 20  # une gagnante par match

    def test_rapport_complet(self, base_complete):
        with Session(base_complete) as session:
            rapport = run_backtest(charger_evaluation(session, "v1"))

        assert rapport["n_matchs"] == 20
        assert "1N2" in rapport["par_marche"]
        assert rapport["par_marche"]["1N2"]["accuracy"] == pytest.approx(0.5)
        assert rapport["par_championnat"]["1"]["n_matchs"] == 20
        assert rapport["par_saison"]["1"]["n_matchs"] == 20

    def test_le_roi_utilise_la_cote_offerte_et_non_la_cote_du_modele(self, base_complete):
        """Le rendement doit se mesurer au prix du marché, pas à celui du modèle.

        Les deux jeux de cotes donnent ici des résultats franchement
        différents, ce qui rend la substitution détectable :

        - cotes offertes (2,0 / 3,5 / 4,0) : mise 60, retour 60, ROI nul ;
        - cotes équitables du modèle (1,82 / 4,0 / 5,0) : retour 68,2,
          soit un ROI de +13,6 % — un rendement qui n'existe que sur le papier.
        """
        with Session(base_complete) as session:
            df = charger_evaluation(session, "v1")
            rapport = run_backtest(df)

        rendement = rapport["par_marche"]["1N2"]["rendement"]
        avec_cote_du_modele = roi_simulation(df["actual_outcome"], df["fair_odds"])

        assert rendement["paris"] == 60
        assert rendement["roi_pct"] == pytest.approx(0.0, abs=1e-9)
        assert avec_cote_du_modele["roi_pct"] == pytest.approx(13.64, abs=0.1)
        assert rendement["roi_pct"] != pytest.approx(avec_cote_du_modele["roi_pct"])

    def test_strategie_naive(self, base_complete):
        with Session(base_complete) as session:
            resultat = strategie_naive(charger_evaluation(session, "v1"), "home")

        assert resultat["taux_de_reussite"] == pytest.approx(0.5)

    def test_strategie_du_favori_du_marche(self, base_complete):
        with Session(base_complete) as session:
            resultat = strategie_marche(charger_evaluation(session, "v1"))

        # Le favori du marché est « home » (cote 2.0), gagnant une fois sur deux.
        assert resultat["taux_de_reussite"] == pytest.approx(0.5)

    def test_backtest_vide(self):
        import pandas as pd

        assert "erreur" in run_backtest(pd.DataFrame())


class TestAccuracyParGroupe:
    def test_la_double_chance_n_a_pas_d_accuracy(self):
        import pandas as pd

        df = pd.DataFrame(
            {
                "match_id": [1, 1, 1],
                "selection": ["home_or_draw", "home_or_away", "draw_or_away"],
                "probability": [0.8, 0.75, 0.45],
                "actual_outcome": ["won", "won", "lost"],
            }
        )

        assert _accuracy_par_groupe(df, "double_chance") is None

    def test_l_over_under_est_evalue_ligne_par_ligne(self):
        """Sans découpage par ligne, l'accuracy désignerait toujours over_0.5."""
        import pandas as pd

        df = pd.DataFrame(
            {
                "match_id": [1, 1, 1, 1],
                "selection": ["over_0.5", "under_0.5", "over_2.5", "under_2.5"],
                "probability": [0.95, 0.05, 0.45, 0.55],
                "actual_outcome": ["won", "lost", "lost", "won"],
            }
        )

        # Les deux lignes sont correctement prédites : accuracy = 1.
        assert _accuracy_par_groupe(df, "over_under") == pytest.approx(1.0)


class TestCalibration:
    @staticmethod
    def _jeu_surconfiant(n=2000, graine=3):
        """Probabilités systématiquement trop tranchées par rapport au réel."""
        rng = np.random.default_rng(graine)
        vraies = rng.uniform(0.1, 0.9, n)
        annoncees = np.clip(vraies + (vraies - 0.5) * 0.6, 0.01, 0.99)
        issues = (rng.uniform(size=n) < vraies).astype(int)
        return issues, annoncees

    def test_platt_reduit_l_erreur_de_calibration(self):
        y, p = self._jeu_surconfiant()
        moitie = len(y) // 2

        calibrateur = ajuster_calibrateur(y[:moitie], p[:moitie], "platt")
        corrigees = calibrateur.transform(p[moitie:])

        avant = erreur_de_calibration(y[moitie:], p[moitie:])
        apres = erreur_de_calibration(y[moitie:], corrigees)
        assert apres < avant

    def test_isotonique_reduit_l_erreur_de_calibration(self):
        y, p = self._jeu_surconfiant()
        moitie = len(y) // 2

        calibrateur = ajuster_calibrateur(y[:moitie], p[:moitie], "isotonic")
        corrigees = calibrateur.transform(p[moitie:])

        assert erreur_de_calibration(y[moitie:], corrigees) < erreur_de_calibration(
            y[moitie:], p[moitie:]
        )

    def test_les_probabilites_restent_dans_zero_un(self):
        y, p = self._jeu_surconfiant()
        calibrateur = ajuster_calibrateur(y, p, "isotonic")

        corrigees = calibrateur.transform([0.0, 0.001, 0.5, 0.999, 1.0])

        assert (corrigees >= 0).all() and (corrigees <= 1).all()

    def test_serialisation(self):
        y, p = self._jeu_surconfiant()
        calibrateur = ajuster_calibrateur(y, p, "platt")

        rejoue = Calibrateur.from_dict(calibrateur.to_dict())

        np.testing.assert_allclose(rejoue.transform(p[:10]), calibrateur.transform(p[:10]))

    def test_methode_inconnue(self):
        with pytest.raises(ValueError, match="Méthode inconnue"):
            ajuster_calibrateur([0, 1], [0.3, 0.7], "magique")

    def test_jeu_sans_variete(self):
        with pytest.raises(ValueError, match="Une seule issue"):
            ajuster_calibrateur([1, 1, 1], [0.3, 0.5, 0.7])

    def test_sans_calibrateur_les_probabilites_ne_changent_pas(self):
        brutes = [0.2, 0.5, 0.8]

        np.testing.assert_allclose(calibrate_probabilities(brutes), brutes)


class TestDependancesOptionnelles:
    """Le noyau doit tourner sans les extras.

    scikit-learn, FastAPI et Streamlit doivent être compilés depuis les
    sources sur les plateformes sans roue précompilée — Termux sur Android,
    par exemple. Les exiger pour lancer un simple import de CSV était un
    obstacle inutile.
    """

    MODULES_DU_NOYAU = (
        "pipelines.historical_import",
        "pipelines.feature_pipeline",
        "pipelines.prediction_pipeline",
        "models.dixon_coles",
        "models.first_half",
        "models.market_assembly",
        "evaluation.settlement",
        "evaluation.pricing",
        "evaluation.backtest",
        "evaluation.metrics",
    )

    EXTRAS = {"sklearn", "streamlit", "fastapi", "uvicorn", "statsmodels"}

    @pytest.fixture
    def sans_extras(self, monkeypatch):
        """Rendre les extras introuvables, le temps du test."""
        import builtins

        importer_reel = builtins.__import__

        def importer(nom, *args, **kwargs):
            if nom.split(".")[0] in self.EXTRAS:
                raise ImportError(f"{nom} indisponible (simulation)")
            return importer_reel(nom, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", importer)

    def test_le_noyau_s_importe_sans_les_extras(self):
        """Un interpréteur neuf doit importer tout le noyau sans les extras.

        Le test tourne dans un sous-processus. Réimporter les modules dans
        l'interpréteur courant laisserait des objets modules neufs attachés au
        paquet parent : les tests qui remplacent une fonction du pipeline
        patcheraient alors un module que plus personne n'appelle — une
        contamination silencieuse, et c'est exactement ce qui s'est produit à
        la première rédaction de ce test.
        """
        import subprocess
        import sys
        import textwrap

        programme = textwrap.dedent(f"""
            import sys

            interdits = {sorted(self.EXTRAS)!r}

            class Bloqueur:
                def find_spec(self, nom, chemin=None, cible=None):
                    if nom.split(".")[0] in interdits:
                        raise ImportError(nom + " indisponible (simulation)")
                    return None

            sys.meta_path.insert(0, Bloqueur())
            import importlib
            for module in {list(self.MODULES_DU_NOYAU)!r}:
                importlib.import_module(module)
            print("ok")
        """)

        resultat = subprocess.run(
            [sys.executable, "-c", programme],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert resultat.returncode == 0, resultat.stderr
        assert "ok" in resultat.stdout

    def test_la_calibration_explique_ce_qui_manque(self, sans_extras):
        """Un ImportError nu n'aiderait personne à comprendre quoi installer."""
        with pytest.raises(ImportError, match=r'pip install -e ".\[ml\]"'):
            ajuster_calibrateur([0, 1, 0, 1], [0.2, 0.8, 0.3, 0.7], "platt")

    def test_les_dependances_du_noyau_sont_pures_ou_courantes(self):
        """Le noyau déclaré ne doit contenir aucun extra."""
        import tomllib
        from pathlib import Path

        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        noyau = {d.split(">")[0].split("[")[0] for d in pyproject["project"]["dependencies"]}

        assert not (noyau & {"scikit-learn", "statsmodels", "streamlit", "fastapi", "uvicorn"})
        assert {"pandas", "numpy", "scipy", "sqlalchemy", "loguru"} <= noyau
