"""Tests des marchés de mi-temps.

Le README annonçait ces marchés comme livrés. En réalité, `derive_first_half_markets`
existait mais n'était appelée nulle part, et `persist_predictions` aurait rejeté
ses sorties : elles n'appartenaient pas au contrat public.
"""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Competition, Feature, Match, Prediction, Team
from models.dixon_coles import DixonColesModel
from models.first_half import ModelesDeMiTemps, fit_half_models, separer_les_periodes
from models.market_assembly import PUBLIC_MARKETS, PUBLIC_SELECTIONS, build_half_markets
from models.market_derivation import derive_most_productive_half
from models.poisson import compute_score_matrix
from models.prediction_context import build_match_predictions
from pipelines.prediction_pipeline import generate_match_predictions


def _matchs_avec_mi_temps(n_equipes=6, tours=8):
    """Championnat simulé, avec des scores de mi-temps cohérents."""
    lignes = []
    for tour in range(tours):
        for i in range(n_equipes):
            for j in range(n_equipes):
                if i == j:
                    continue
                hg = (i + tour) % 4
                ag = (j + 1) % 3
                lignes.append(
                    {
                        "id": len(lignes),
                        "competition_id": 1,
                        "match_date": pd.Timestamp("2023-08-01")
                        + pd.Timedelta(days=len(lignes) // 5),
                        "home_team_id": i,
                        "away_team_id": j,
                        "home_goals": hg,
                        "away_goals": ag,
                        "home_ht_goals": hg // 2,
                        "away_ht_goals": ag // 2,
                    }
                )
    return pd.DataFrame(lignes)


class TestSeparationDesPeriodes:
    def test_les_buts_se_repartissent_sans_perte(self):
        df = _matchs_avec_mi_temps()

        premiere, seconde = separer_les_periodes(df)

        total = premiere["home_goals"].sum() + seconde["home_goals"].sum()
        assert total == df["home_goals"].sum()

    def test_aucun_but_negatif_en_seconde_periode(self):
        df = _matchs_avec_mi_temps()

        _, seconde = separer_les_periodes(df)

        assert (seconde["home_goals"] >= 0).all()
        assert (seconde["away_goals"] >= 0).all()

    def test_un_score_de_mi_temps_incoherent_est_ecarte(self):
        """Un score de mi-temps supérieur au score final est une donnée fausse."""
        df = _matchs_avec_mi_temps()
        df.loc[0, "home_ht_goals"] = 9

        premiere, seconde = separer_les_periodes(df)

        assert len(premiere) == len(df) - 1
        assert (seconde["home_goals"] >= 0).all()

    def test_colonnes_absentes(self):
        with pytest.raises(ValueError, match="Colonnes de mi-temps absentes"):
            separer_les_periodes(pd.DataFrame({"home_goals": [1], "away_goals": [0]}))


class TestAjustementDesMiTemps:
    def test_deux_modeles_distincts(self):
        modeles = fit_half_models(_matchs_avec_mi_temps(), xi=0.0)

        assert isinstance(modeles, ModelesDeMiTemps)
        assert modeles.premiere.home_advantage != modeles.seconde.home_advantage

    def test_moins_de_buts_attendus_en_premiere_periode(self):
        """Les données simulées mettent la moitié des buts en première période."""
        modeles = fit_half_models(_matchs_avec_mi_temps(), xi=0.0)

        lam_1h, _ = modeles.premiere.lambdas(0, 1)
        lam_2h, _ = modeles.seconde.lambdas(0, 1)

        assert lam_1h < lam_2h

    def test_matrices_normalisees(self):
        modeles = fit_half_models(_matchs_avec_mi_temps(), xi=0.0)

        m1, m2 = modeles.matrices(0, 1)

        assert m1.sum() == pytest.approx(1.0, abs=1e-12)
        assert m2.sum() == pytest.approx(1.0, abs=1e-12)

    def test_equipes_connues_des_deux_modeles(self):
        modeles = fit_half_models(_matchs_avec_mi_temps(), xi=0.0)

        assert modeles.connait(0, 1)
        assert not modeles.connait(0, 999)

    def test_serialisation(self):
        modeles = fit_half_models(_matchs_avec_mi_temps(), xi=0.0)

        rejoue = ModelesDeMiTemps.from_dict(modeles.to_dict())

        assert rejoue.premiere.lambdas(0, 1) == pytest.approx(modeles.premiere.lambdas(0, 1))


class TestMiTempsLaPlusProlifique:
    def test_les_trois_issues_somment_a_un(self):
        m1 = compute_score_matrix(0.6, 0.5, max_goals=6)
        m2 = compute_score_matrix(0.9, 0.7, max_goals=6)

        resultats = derive_most_productive_half(m1, m2)

        assert sum(r["probability"] for r in resultats) == pytest.approx(1.0, abs=1e-9)

    def test_la_periode_la_plus_prolifique_est_favorite(self):
        pauvre = compute_score_matrix(0.3, 0.2, max_goals=6)
        riche = compute_score_matrix(1.8, 1.5, max_goals=6)

        resultats = {
            r["selection"]: r["probability"] for r in derive_most_productive_half(pauvre, riche)
        }

        assert resultats["second_half"] > resultats["first_half"]

    def test_deux_periodes_identiques_sont_symetriques(self):
        m = compute_score_matrix(1.0, 0.8, max_goals=6)

        resultats = {r["selection"]: r["probability"] for r in derive_most_productive_half(m, m)}

        assert resultats["first_half"] == pytest.approx(resultats["second_half"])

    def test_resultat_identique_a_la_double_boucle(self):
        """Contrôle de la version vectorisée contre un calcul naïf explicite."""
        m1 = compute_score_matrix(0.7, 0.6, max_goals=5)
        m2 = compute_score_matrix(1.1, 0.9, max_goals=5)

        attendu = {"first_half": 0.0, "second_half": 0.0, "equal": 0.0}
        for i in range(m1.shape[0]):
            for j in range(m1.shape[1]):
                for k in range(m2.shape[0]):
                    for n in range(m2.shape[1]):
                        conjointe = m1[i][j] * m2[k][n]
                        if i + j > k + n:
                            attendu["first_half"] += conjointe
                        elif i + j < k + n:
                            attendu["second_half"] += conjointe
                        else:
                            attendu["equal"] += conjointe

        obtenu = {r["selection"]: r["probability"] for r in derive_most_productive_half(m1, m2)}
        for cle in attendu:
            assert obtenu[cle] == pytest.approx(attendu[cle], abs=1e-12)


class TestContratPublic:
    def test_quinze_marches_de_mi_temps(self):
        m1 = compute_score_matrix(0.6, 0.5, max_goals=6)
        m2 = compute_score_matrix(0.9, 0.7, max_goals=6)

        marches = build_half_markets(m1, m2)

        assert len(marches) == 15  # 3 + 3 + 6 + 3

    def test_tous_les_identifiants_sont_publics(self):
        m1 = compute_score_matrix(0.6, 0.5, max_goals=6)
        m2 = compute_score_matrix(0.9, 0.7, max_goals=6)

        for prediction in build_half_markets(m1, m2):
            assert prediction["market"] in PUBLIC_MARKETS
            assert prediction["selection"] in PUBLIC_SELECTIONS[prediction["market"]]

    def test_les_selections_1n2_sont_normalisees(self):
        """« home_win » interne devient « home » public, comme en match entier."""
        m1 = compute_score_matrix(0.6, 0.5, max_goals=6)
        m2 = compute_score_matrix(0.9, 0.7, max_goals=6)

        selections = {p["selection"] for p in build_half_markets(m1, m2) if p["market"] == "1N2_1H"}

        assert selections == {"home", "draw", "away"}

    def test_probabilites_coherentes(self):
        m1 = compute_score_matrix(0.6, 0.5, max_goals=6)
        m2 = compute_score_matrix(0.9, 0.7, max_goals=6)
        marches = build_half_markets(m1, m2)

        total_1n2 = sum(p["probability"] for p in marches if p["market"] == "1N2_1H")
        assert total_1n2 == pytest.approx(1.0, abs=1e-9)
        for prediction in marches:
            assert 0.0 <= prediction["probability"] <= 1.0
            assert prediction["fair_odds"] > 0


class TestIntegrationEnBase:
    @pytest.fixture
    def contexte(self, tmp_path):
        moteur = create_engine(f"sqlite:///{tmp_path}/test.db")
        Base.metadata.create_all(bind=moteur)
        with Session(moteur) as session:
            comp = Competition(name="T", country="T", provider_code="T")
            session.add(comp)
            session.flush()
            dom, ext = Team(canonical_name="D"), Team(canonical_name="E")
            session.add_all([dom, ext])
            session.flush()
            for i in range(10):
                session.add(
                    Match(
                        competition_id=comp.id,
                        match_date=datetime(2024, 1, 1 + i),
                        home_team_id=dom.id,
                        away_team_id=ext.id,
                        home_goals=2,
                        away_goals=1,
                    )
                )
            cible = Match(
                competition_id=comp.id,
                match_date=datetime(2024, 6, 1),
                home_team_id=dom.id,
                away_team_id=ext.id,
            )
            session.add(cible)
            session.flush()
            session.add_all(
                [
                    Feature(
                        match_id=cible.id,
                        team_id=dom.id,
                        goals_for_avg_5=2.0,
                        goals_against_avg_5=1.0,
                    ),
                    Feature(
                        match_id=cible.id,
                        team_id=ext.id,
                        goals_for_avg_5=1.0,
                        goals_against_avg_5=2.0,
                    ),
                ]
            )
            session.commit()
            return moteur, cible.id, dom.id, ext.id

    @staticmethod
    def _modeles(dom, ext):
        return ModelesDeMiTemps(
            premiere=DixonColesModel(
                attack={dom: 0.2, ext: -0.2},
                defense={dom: 0.1, ext: -0.1},
                home_advantage=0.2,
                rho=-0.05,
                n_matches=50,
            ),
            seconde=DixonColesModel(
                attack={dom: 0.3, ext: -0.3},
                defense={dom: 0.1, ext: -0.1},
                home_advantage=0.2,
                rho=-0.05,
                n_matches=50,
            ),
        )

    def test_sans_modeles_de_mi_temps_seize_predictions(self, contexte):
        moteur, match_id, _, _ = contexte

        with Session(moteur) as session:
            predictions = build_match_predictions(session, match_id)

        assert len(predictions) == 16
        assert not [p for p in predictions if p["market"].endswith("_1H")]

    def test_avec_modeles_trente_et_une_predictions(self, contexte):
        moteur, match_id, dom, ext = contexte

        with Session(moteur) as session:
            predictions = build_match_predictions(
                session, match_id, half_models=self._modeles(dom, ext)
            )

        assert len(predictions) == 31
        assert len([p for p in predictions if p["market"] == "most_productive_half"]) == 3

    def test_les_marches_de_mi_temps_sont_persistes(self, contexte):
        moteur, match_id, dom, ext = contexte

        with Session(moteur) as session:
            generate_match_predictions(
                session, match_id, "test-v1", half_models=self._modeles(dom, ext)
            )

        with Session(moteur) as lecture:
            marches = {p.market for p in lecture.query(Prediction).all()}

        assert "1N2_1H" in marches
        assert "most_productive_half" in marches
        assert lecture.query(Prediction).count() == 31

    def test_une_equipe_inconnue_supprime_les_marches_de_mi_temps(self, contexte):
        """Plutôt aucune prédiction de mi-temps qu'une prédiction inventée."""
        moteur, match_id, dom, _ = contexte
        partiels = self._modeles(dom, 9999)

        with Session(moteur) as session:
            predictions = build_match_predictions(session, match_id, half_models=partiels)

        assert len(predictions) == 16


class TestPerformance:
    def test_la_derivation_ne_boucle_plus_en_quatre_dimensions(self):
        """Vérifie l'ordre de grandeur, pas la microseconde."""
        import time

        m1 = compute_score_matrix(1.0, 0.9, max_goals=8)
        m2 = compute_score_matrix(1.2, 1.0, max_goals=8)

        debut = time.perf_counter()
        for _ in range(200):
            derive_most_productive_half(m1, m2)
        duree = time.perf_counter() - debut

        # La version à quatre boucles imbriquées dépassait la seconde pour 200
        # appels ; la version vectorisée reste très en dessous.
        assert duree < 1.0
        assert np.isfinite(duree)
