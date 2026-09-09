"""Tests du backtest multi-championnats.

Deux risques, et un seul est visible. Le premier est d'oublier un championnat :
il se voit, le compte de matchs baisse. Le second ne se voit pas — agréger la
saison de **validation** au jeu de test. Une version de modèle porte aussi les
prédictions qui ont servi à ajuster son calibrateur ; les mélanger au test
flatte le résultat sans lever d'erreur. Ce défaut s'est déjà produit dans ce
projet (`charger_evaluation`, corrigé le 08/09/2026), d'où le test qui le fige.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    ActualResult,
    Base,
    Competition,
    Match,
    Prediction,
    Season,
    Team,
)
from scripts.mesurer_backtest import SAISONS_DE_TEST, charger_les_championnats, mesurer

VERSION = "dc-essai"

# Une saison de validation et deux de test, comme le protocole D-02.
SAISONS = {"2324": 1, "2425": 2, "2526": 3}


@pytest.fixture
def engine(tmp_path):
    """Deux championnats, trois saisons, une prédiction 1N2 réglée par match."""
    moteur = create_engine(f"sqlite:///{tmp_path / 'mesure.db'}")
    Base.metadata.create_all(bind=moteur)

    with Session(moteur) as session:
        for competition_id in (1, 2):
            session.add(
                Competition(
                    id=competition_id,
                    name=f"Championnat {competition_id}",
                    country="X",
                    provider_code=f"C{competition_id}",
                )
            )
            for team_id in (competition_id * 10, competition_id * 10 + 1):
                session.add(
                    Team(id=team_id, canonical_name=f"E{team_id}", provider="football_data")
                )
        for nom, saison_id in SAISONS.items():
            session.add(Season(id=saison_id, competition_id=1, season_name=nom))
        session.flush()

        match_id = 0
        for competition_id in (1, 2):
            for nom, saison_id in SAISONS.items():
                match_id += 1
                session.add(
                    Match(
                        id=match_id,
                        provider="football_data",
                        competition_id=competition_id,
                        season_id=saison_id,
                        match_date=datetime(2000 + saison_id, 3, 1),
                        home_team_id=competition_id * 10,
                        away_team_id=competition_id * 10 + 1,
                        home_goals=2,
                        away_goals=1,
                    )
                )
                session.add(
                    Prediction(
                        match_id=match_id,
                        model_version=f"{VERSION}-comp{competition_id}",
                        market="1N2",
                        selection="home",
                        probability=0.5,
                        fair_odds=2.0,
                        offered_odds=2.1,
                        edge=0.05,
                    )
                )
                session.add(
                    ActualResult(
                        match_id=match_id,
                        market="1N2",
                        selection="home",
                        actual_outcome="won",
                    )
                )
        session.commit()

    return moteur


class TestPerimetre:
    def test_la_validation_est_exclue_par_defaut(self, engine, tmp_path):
        """2023/24 a servi à calibrer : l'agréger au test gonflerait le résultat."""
        rapport = mesurer(version=VERSION, engine=engine, repertoire=str(tmp_path / "r"))

        assert rapport["perimetre"]["saisons"] == SAISONS_DE_TEST
        assert "2324" not in rapport["perimetre"]["saisons"]
        # deux championnats x deux saisons de test
        assert rapport["n_matchs"] == 4

    def test_les_cinq_versions_sont_reunies(self, engine):
        with Session(engine) as session:
            df = charger_les_championnats(session, VERSION, [1, 2], ["2425", "2526"])

        assert sorted(df["competition_id"].unique()) == [1, 2]
        assert sorted(df["model_version"].unique()) == [
            f"{VERSION}-comp1",
            f"{VERSION}-comp2",
        ]

    def test_une_competition_sans_prediction_est_ignoree_sans_faire_echouer(self, engine):
        with Session(engine) as session:
            df = charger_les_championnats(session, VERSION, [1, 2, 9], ["2425", "2526"])

        assert sorted(df["competition_id"].unique()) == [1, 2]

    def test_la_selection_explicite_restreint_les_championnats(self, engine, tmp_path):
        rapport = mesurer(
            version=VERSION,
            competitions=[1],
            engine=engine,
            repertoire=str(tmp_path / "r"),
        )

        assert rapport["perimetre"]["competitions"] == [1]
        assert rapport["n_matchs"] == 2


class TestRapport:
    def test_le_rapport_est_ecrit_sur_disque(self, engine, tmp_path):
        import json

        repertoire = tmp_path / "rapports"
        rapport = mesurer(version=VERSION, engine=engine, repertoire=str(repertoire))

        fichier = repertoire / rapport["fichier"].rsplit("/", 1)[-1]
        assert fichier.exists()
        relu = json.loads(fichier.read_text(encoding="utf-8"))
        assert relu["perimetre"]["version"] == VERSION

    def test_un_perimetre_vide_ne_leve_pas_mais_le_dit(self, engine, tmp_path):
        rapport = mesurer(
            version="version-inexistante",
            engine=engine,
            repertoire=str(tmp_path / "r"),
        )

        assert "erreur" in rapport

    def test_la_base_n_est_pas_modifiee(self, engine, tmp_path):
        with Session(engine) as session:
            avant = session.query(Prediction).count(), session.query(ActualResult).count()

        mesurer(version=VERSION, engine=engine, repertoire=str(tmp_path / "r"))

        with Session(engine) as session:
            apres = session.query(Prediction).count(), session.query(ActualResult).count()
        assert avant == apres


class TestAffichage:
    """L'affichage lit le rapport de `run_backtest` : ses clés font partie du
    contrat. Elles ont déjà été lues de travers une fois — `roi` au lieu de
    `roi_pct`, `n_paris` au lieu de `paris` —, ce qui affichait « 0 pari, ROI
    indisponible » sur un backtest parfaitement valorisé.
    """

    def test_le_roi_est_lu_sous_la_cle_que_le_backtest_ecrit(self, engine, tmp_path):
        from scripts.mesurer_backtest import _paris, _roi

        rapport = mesurer(version=VERSION, engine=engine, repertoire=str(tmp_path / "r"))
        rendement = rapport["par_marche"]["1N2"]["rendement"]

        assert _paris(rendement) > 0, "des cotes sont présentes : les paris doivent être comptés"
        assert _roi(rendement) != "—"
        # Le backtest exprime déjà le ROI en pourcentage : ne pas le multiplier.
        assert _roi(rendement) == f"{rendement['roi_pct']:+.2f} %"

    def test_les_strategies_portent_leur_rendement_dans_un_sous_bloc(self, engine, tmp_path):
        from scripts.mesurer_backtest import _paris

        rapport = mesurer(version=VERSION, engine=engine, repertoire=str(tmp_path / "r"))

        for nom, resultat in rapport["strategies"].items():
            assert "rendement" in resultat, f"{nom} : rendement attendu dans un sous-bloc"
        assert _paris(rapport["strategies"]["favori_du_marche"]["rendement"]) > 0

    def test_un_rendement_absent_s_affiche_sans_lever(self):
        from scripts.mesurer_backtest import _paris, _roi

        assert _roi(None) == "—"
        assert _roi({}) == "—"
        assert _roi({"roi_pct": None}) == "—"
        assert _paris(None) == 0


class TestIntervalles:
    """Les bornes doivent encadrer **les paris publiés**, pas d'autres.

    Les filtres sont écrits deux fois : dans `evaluation.backtest` pour le
    rendement, dans `mesurer_backtest` pour l'intervalle. Une divergence ne
    lèverait aucune erreur — elle publierait simplement un intervalle qui ne
    correspond pas au chiffre qu'il est censé encadrer. Ce test compare les
    effectifs des deux côtés, et c'est sa seule raison d'être.
    """

    def test_les_effectifs_des_strategies_coincident(self, engine, tmp_path):
        rapport = mesurer(version=VERSION, engine=engine, repertoire=str(tmp_path / "r"))

        for nom, bloc in rapport["strategies"].items():
            if nom not in rapport["intervalles"]["strategies"]:
                continue
            publies = (bloc.get("rendement") or {}).get("paris") or 0
            encadres = rapport["intervalles"]["strategies"][nom]["paris"]
            assert publies == encadres, f"{nom} : {publies} paris publiés, {encadres} encadrés"

    def test_les_effectifs_par_marche_coincident(self, engine, tmp_path):
        rapport = mesurer(version=VERSION, engine=engine, repertoire=str(tmp_path / "r"))

        for marche, metriques in rapport["par_marche"].items():
            publies = (metriques.get("rendement") or {}).get("paris") or 0
            encadres = rapport["intervalles"]["par_marche"].get(marche, {}).get("paris", 0)
            assert publies == encadres, f"{marche} : {publies} publiés, {encadres} encadrés"

    def test_le_roi_ponctuel_est_le_meme_des_deux_cotes(self, engine, tmp_path):
        rapport = mesurer(version=VERSION, engine=engine, repertoire=str(tmp_path / "r"))

        publie = rapport["par_marche"]["1N2"]["rendement"]["roi_pct"]
        encadre = rapport["intervalles"]["par_marche"]["1N2"]["roi_pct"]
        assert publie == pytest.approx(encadre, abs=1e-9)
