"""Tests du choix du moteur de prédiction.

Le pipeline sait produire une matrice de scores de deux façons : depuis un
Dixon-Coles ajusté, ou depuis le Poisson alimenté par les moyennes glissantes.
Ce fichier vérifie que le bon moteur est retenu, et surtout que le repli est
sûr — un modèle absent ou incomplet ne doit jamais faire échouer une prédiction
ni produire silencieusement une prédiction moins fondée qu'annoncé.
"""

from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Competition, Feature, Match, Team
from models.dixon_coles import DixonColesModel, fit_dixon_coles
from models.model_registry import ModelRegistry
from models.prediction_context import build_match_predictions
from pipelines.prediction_pipeline import charger_modele


@pytest.fixture
def base(tmp_path):
    moteur = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(bind=moteur)
    return moteur


@pytest.fixture
def match_cible(base):
    """Un match à prédire, ses deux équipes, ses features et un historique."""
    with Session(base) as session:
        comp = Competition(name="Test", country="Test", provider_code="TST")
        session.add(comp)
        session.flush()
        dom = Team(canonical_name="Domicile")
        ext = Team(canonical_name="Exterieur")
        session.add_all([dom, ext])
        session.flush()

        for i in range(20):
            session.add(
                Match(
                    competition_id=comp.id,
                    match_date=datetime(2024, 1, 1 + i % 28),
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
        return {"match_id": cible.id, "dom": dom.id, "ext": ext.id}


def _modele(dom, ext, attaque_dom=0.6):
    """Modèle ajusté artificiellement, aux forces très marquées."""
    return DixonColesModel(
        attack={dom: attaque_dom, ext: -attaque_dom},
        defense={dom: 0.3, ext: -0.3},
        home_advantage=0.25,
        rho=-0.1,
        n_matches=100,
    )


class TestChoixDuMoteur:
    def test_le_modele_ajuste_change_les_probabilites(self, base, match_cible):
        """Si le modèle n'était pas utilisé, les deux séries seraient identiques."""
        with Session(base) as session:
            repli = build_match_predictions(session, match_cible["match_id"])
            avec_modele = build_match_predictions(
                session,
                match_cible["match_id"],
                model=_modele(match_cible["dom"], match_cible["ext"]),
            )

        p_repli = {(p["market"], p["selection"]): p["probability"] for p in repli}
        p_modele = {(p["market"], p["selection"]): p["probability"] for p in avec_modele}

        assert p_repli.keys() == p_modele.keys()
        assert p_modele[("1N2", "home")] != pytest.approx(p_repli[("1N2", "home")])
        # Forces très marquées : le modèle doit être plus tranché que le repli.
        assert p_modele[("1N2", "home")] > p_repli[("1N2", "home")]

    def test_le_contrat_public_est_respecte_par_les_deux_moteurs(self, base, match_cible):
        from models.market_assembly import PUBLIC_MARKETS, PUBLIC_SELECTIONS

        with Session(base) as session:
            for modele in (None, _modele(match_cible["dom"], match_cible["ext"])):
                predictions = build_match_predictions(
                    session, match_cible["match_id"], model=modele
                )

                assert len(predictions) == 16
                for p in predictions:
                    assert p["market"] in PUBLIC_MARKETS
                    assert p["selection"] in PUBLIC_SELECTIONS[p["market"]]
                    assert 0.0 <= p["probability"] <= 1.0

    def test_les_probabilites_1n2_somment_a_un(self, base, match_cible):
        with Session(base) as session:
            predictions = build_match_predictions(
                session,
                match_cible["match_id"],
                model=_modele(match_cible["dom"], match_cible["ext"]),
            )

        total = sum(p["probability"] for p in predictions if p["market"] == "1N2")
        assert total == pytest.approx(1.0, abs=1e-9)


class TestRepli:
    def test_sans_modele_le_repli_s_applique(self, base, match_cible):
        with Session(base) as session:
            predictions = build_match_predictions(session, match_cible["match_id"], model=None)

        assert len(predictions) == 16

    def test_une_equipe_inconnue_declenche_le_repli(self, base, match_cible):
        """Le modèle traiterait la promue comme moyenne ; le repli connaît sa forme."""
        partiel = DixonColesModel(
            attack={match_cible["dom"]: 0.6},
            defense={match_cible["dom"]: 0.3},
            home_advantage=0.25,
            rho=-0.1,
            n_matches=100,
        )

        with Session(base) as session:
            repli = build_match_predictions(session, match_cible["match_id"])
            avec_partiel = build_match_predictions(session, match_cible["match_id"], model=partiel)

        assert avec_partiel == repli


class TestChargementDepuisLeRegistre:
    def test_une_version_poisson_ne_charge_aucun_modele(self, tmp_path):
        assert charger_modele("poisson-v1", registry_dir=str(tmp_path)) is None

    def test_un_registre_vide_ne_fait_pas_echouer(self, tmp_path):
        assert charger_modele("dixon-coles-2026", registry_dir=str(tmp_path)) is None

    def test_le_modele_enregistre_est_rechargeable(self, tmp_path):
        lignes = [
            {
                "id": n,
                "competition_id": 1,
                "match_date": pd.Timestamp("2023-08-01") + pd.Timedelta(days=n),
                "home_team_id": n % 4,
                "away_team_id": (n + 1) % 4,
                "home_goals": n % 3,
                "away_goals": (n + 1) % 2,
            }
            for n in range(80)
        ]
        modele = fit_dixon_coles(pd.DataFrame(lignes), xi=0.0)
        registre = ModelRegistry(tmp_path)
        registre.register("dixon_coles", "dixon-coles-essai", payload=modele.to_dict())

        recharge = charger_modele("dixon-coles-essai", registry_dir=str(tmp_path))

        assert recharge is not None
        assert recharge.lambdas(0, 1) == pytest.approx(modele.lambdas(0, 1))
