"""Tests du script de génération de prédictions par championnat.

Le défaut que ce script existe pour empêcher est silencieux : `charger_modele`
se rabat sur n'importe quel Dixon-Coles enregistré quand la version demandée
est absente. Demander le modèle de la compétition 2 alors que seul celui de la
compétition 1 existe renvoie donc le modèle anglais, sans un mot — c'est ce qui
a produit, le 08/09/2026, 1 372 matchs prédits par le mauvais modèle et un
backtest inexploitable.

Deux garanties sont vérifiées ici : aucune compétition n'est prédite par le
modèle d'une autre, et les matchs soumis à un modèle sont ceux de son
championnat.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Competition, Feature, Match, Prediction, Season, Team
from models.dixon_coles import DixonColesModel
from models.model_registry import ModelRegistry
from scripts.generate_predictions import (
    charger_couple_de_modeles,
    competitions_en_base,
    predire,
)

COUPURE = datetime(2025, 1, 1)
VERSION = "dc-test"

CHAMPIONNATS = {1: "Premier League", 2: "Bundesliga"}


def _identifiants(competition_id: int) -> tuple[int, int]:
    """Identifiants des deux équipes d'une compétition."""
    return competition_id * 10, competition_id * 10 + 1


@pytest.fixture
def engine(tmp_path):
    """Deux championnats, deux équipes chacun, un historique et un match à venir."""
    moteur = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(bind=moteur)

    with Session(moteur) as session:
        for competition_id, nom in CHAMPIONNATS.items():
            session.add(
                Competition(
                    id=competition_id,
                    name=nom,
                    country=nom,
                    provider_code=f"C{competition_id}",
                )
            )
            session.add(
                Season(id=competition_id, competition_id=competition_id, season_name="2425")
            )
            domicile, exterieur = _identifiants(competition_id)
            for team_id in (domicile, exterieur):
                session.add(
                    Team(id=team_id, canonical_name=f"E{team_id}", provider="football_data")
                )
        session.flush()

        for competition_id in CHAMPIONNATS:
            domicile, exterieur = _identifiants(competition_id)

            # Historique antérieur à la coupure : moyenne de la ligue.
            for jour in range(8):
                session.add(
                    Match(
                        provider="football_data",
                        competition_id=competition_id,
                        season_id=competition_id,
                        match_date=datetime(2024, 1, 1 + jour),
                        home_team_id=domicile,
                        away_team_id=exterieur,
                        home_goals=2,
                        away_goals=1,
                    )
                )

            # Un match à prédire, avec ses deux features.
            match = Match(
                id=competition_id * 100,
                provider="football_data",
                competition_id=competition_id,
                season_id=competition_id,
                match_date=datetime(2025, 6, 1),
                home_team_id=domicile,
                away_team_id=exterieur,
            )
            session.add(match)
            for team_id in (domicile, exterieur):
                session.add(
                    Feature(
                        match_id=match.id,
                        team_id=team_id,
                        goals_for_avg_5=1.4,
                        goals_against_avg_5=1.1,
                    )
                )
        session.commit()

    return moteur


@pytest.fixture
def registre(tmp_path):
    """Un registre ne portant que le modèle de la compétition 1."""
    repertoire = tmp_path / "registre"
    registre = ModelRegistry(repertoire)
    domicile, exterieur = _identifiants(1)
    modele = DixonColesModel(
        attack={domicile: 0.30, exterieur: 0.10},
        defense={domicile: 0.20, exterieur: 0.05},
        home_advantage=0.25,
        rho=-0.03,
        n_matches=380,
        competition_id=1,
    )
    registre.register("dixon_coles", f"{VERSION}-comp1", metrics={}, payload=modele.to_dict())
    return str(repertoire)


class TestChargementStrict:
    """Aucune version approchante : c'est tout l'objet du script."""

    def test_version_absente_ne_rabat_sur_aucun_autre_modele(self, registre):
        modele, mi_temps = charger_couple_de_modeles(f"{VERSION}-comp2", ModelRegistry(registre))
        assert modele is None
        assert mi_temps is None

    def test_le_repli_du_pipeline_lui_renverrait_le_modele_anglais(self, registre):
        """Le contre-exemple : sans ce script, la compétition 2 serait prédite
        par le modèle de la compétition 1, sans erreur ni avertissement."""
        from pipelines.prediction_pipeline import charger_modele

        rabattu = charger_modele(f"{VERSION}-comp2", registry_dir=registre)
        assert rabattu is not None
        assert rabattu.competition_id == 1

    def test_mi_temps_absentes_ne_bloquent_pas_le_modele_principal(self, registre):
        modele, mi_temps = charger_couple_de_modeles(f"{VERSION}-comp1", ModelRegistry(registre))
        assert modele is not None
        assert modele.competition_id == 1
        assert mi_temps is None


class TestCompetitionsEnBase:
    def test_seules_les_competitions_ayant_des_matchs_sont_listees(self, engine):
        with Session(engine) as session:
            session.add(Competition(id=9, name="Vide", country="V", provider_code="C9"))
            session.commit()

        assert competitions_en_base(engine) == [(1, "Premier League"), (2, "Bundesliga")]


class TestPredictionParChampionnat:
    def test_une_competition_sans_modele_est_sautee(self, engine, registre):
        rapports = predire(
            version=VERSION,
            reference_date=COUPURE,
            engine=engine,
            registry_dir=registre,
            valoriser=False,
        )

        assert set(rapports) == {1}, "la compétition 2 n'a pas de modèle : à sauter"
        assert rapports[1]["succeeded"] == [100]
        assert rapports[1]["failed"] == []

        with Session(engine) as session:
            ecrites = session.query(Prediction).all()
            assert {p.model_version for p in ecrites} == {f"{VERSION}-comp1"}
            assert {p.match_id for p in ecrites} == {100}

    def test_aucune_prediction_ecrite_pour_le_championnat_saute(self, engine, registre):
        predire(
            version=VERSION,
            reference_date=COUPURE,
            engine=engine,
            registry_dir=registre,
            valoriser=False,
        )

        with Session(engine) as session:
            assert session.query(Prediction).filter(Prediction.match_id == 200).count() == 0

    def test_la_selection_explicite_restreint_les_championnats(self, engine, registre):
        rapports = predire(
            version=VERSION,
            reference_date=COUPURE,
            competitions=[2],
            engine=engine,
            registry_dir=registre,
            valoriser=False,
        )

        assert rapports == {}

    def test_le_modele_recu_par_le_pipeline_est_celui_de_la_competition(
        self, engine, registre, monkeypatch
    ):
        """Le script charge le modèle lui-même et le passe : le pipeline ne
        doit jamais avoir à le résoudre, donc jamais à se rabattre."""
        appels = []

        def espion(**kwargs):
            appels.append(kwargs)
            return {"succeeded": [], "failed": [], "predictions_created_or_updated": 0}

        monkeypatch.setattr(
            "pipelines.prediction_pipeline.run_prediction_pipeline", espion, raising=True
        )
        predire(
            version=VERSION,
            reference_date=COUPURE,
            engine=engine,
            registry_dir=registre,
            valoriser=False,
        )

        assert len(appels) == 1
        appel = appels[0]
        assert appel["competition_id"] == 1
        assert appel["model_version"] == f"{VERSION}-comp1"
        assert appel["model"] is not None
        assert appel["model"].competition_id == 1
