"""Tests du compléteur de cotes.

Ce module comble un angle mort découvert le 08/09/2026 : `historical_import`
insère les cotes en même temps que le match, si bien qu'un match déjà présent
— classé « doublon » — ne reçoit jamais les colonnes que le parseur a apprises
depuis. Les saisons 2023/24 et 2024/25 se trouvaient ainsi sans aucune cote
Over/Under, alors que leurs fichiers en portaient vingt colonnes.

Deux garanties comptent ici, et toutes deux protègent l'existant :
le module ne crée aucun match, et il ne duplique aucune cote.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models import Base, Match, OddsSnapshot, Team

ENTETE = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,B365H,B365D,B365A,B365>2.5,B365<2.5"
)
LIGNE = "E0,12/08/23,Arsenal,Chelsea,2,1,H,1,0,H,1.80,3.60,4.50,1.95,1.90"


@pytest.fixture
def fichier(tmp_path):
    chemin = tmp_path / "E0_2324.csv"
    chemin.write_text(f"{ENTETE}\n{LIGNE}\n", encoding="utf-8")
    return chemin


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Un match Arsenal-Chelsea en base, sans aucune cote."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import pipelines.completer_cotes as module

    moteur = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    monkeypatch.setattr(module, "SessionLocal", fabrique)

    session = fabrique()
    arsenal = Team(canonical_name="Arsenal", provider="football_data")
    chelsea = Team(canonical_name="Chelsea", provider="football_data")
    session.add_all([arsenal, chelsea])
    session.flush()
    session.add(
        Match(
            provider="football_data",
            match_date=datetime(2023, 8, 12),
            home_team_id=arsenal.id,
            away_team_id=chelsea.id,
            home_goals=2,
            away_goals=1,
        )
    )
    session.commit()
    session.close()
    return fabrique


class TestComplétion:
    def test_les_cotes_manquantes_sont_ajoutees(self, base, fichier):
        from pipelines.completer_cotes import completer_cotes

        rapport = completer_cotes([fichier])

        assert rapport["matchs_retrouves"] == 1
        assert rapport["cotes_ajoutees"] > 0

        session = base()
        marches = {o.market for o in session.query(OddsSnapshot)}
        assert "1N2" in marches
        assert "over_under" in marches, "les cotes Over/Under sont la raison d'être du module"
        session.close()

    def test_les_over_under_portent_leurs_deux_selections(self, base, fichier):
        from pipelines.completer_cotes import completer_cotes

        completer_cotes([fichier])

        session = base()
        selections = {
            o.selection for o in session.query(OddsSnapshot).filter_by(market="over_under")
        }
        assert selections == {"over_2.5", "under_2.5"}
        session.close()

    def test_aucun_match_n_est_cree(self, base, fichier):
        """Le module ajoute des cotes, il n'importe pas de matchs."""
        from pipelines.completer_cotes import completer_cotes

        session = base()
        avant = session.query(Match).count()
        session.close()

        completer_cotes([fichier])

        session = base()
        assert session.query(Match).count() == avant
        session.close()

    def test_un_match_absent_est_compte_pas_cree(self, base, tmp_path):
        """Une rencontre inconnue de la base relève d'historical_import."""
        from pipelines.completer_cotes import completer_cotes

        autre = tmp_path / "E0_autre.csv"
        autre.write_text(
            f"{ENTETE}\nE0,20/08/23,Liverpool,Everton,1,0,H,0,0,D,2.0,3.5,4.0,1.9,1.95\n",
            encoding="utf-8",
        )

        rapport = completer_cotes([autre])

        assert rapport["matchs_introuvables"] == 1
        assert rapport["cotes_ajoutees"] == 0

        session = base()
        assert session.query(Match).count() == 1
        session.close()

    def test_le_module_est_idempotent(self, base, fichier):
        """Les cotes n'ont pas de contrainte d'unicité au niveau du schéma :
        c'est le module qui doit refuser le doublon."""
        from pipelines.completer_cotes import completer_cotes

        premier = completer_cotes([fichier])
        second = completer_cotes([fichier])

        assert premier["cotes_ajoutees"] > 0
        assert second["cotes_ajoutees"] == 0
        assert second["cotes_deja_presentes"] == premier["cotes_ajoutees"]

        session = base()
        total = session.query(OddsSnapshot).count()
        session.close()
        assert total == premier["cotes_ajoutees"]

    def test_la_simulation_n_ecrit_rien(self, base, fichier):
        from pipelines.completer_cotes import completer_cotes

        rapport = completer_cotes([fichier], simuler=True)

        assert rapport["cotes_ajoutees"] > 0
        session = base()
        assert session.query(OddsSnapshot).count() == 0
        session.close()

    def test_une_serie_incomplete_est_ecartee(self, base, tmp_path):
        """Sans toutes ses sélections, la marge du bookmaker n'est pas
        calculable et la série n'a pas de sens."""
        from pipelines.completer_cotes import completer_cotes

        partiel = tmp_path / "E0_partiel.csv"
        # B365D absent : la série 1N2 est incomplète. L'Over/Under reste entier.
        partiel.write_text(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,"
            "B365H,B365D,B365A,B365>2.5,B365<2.5\n"
            "E0,12/08/23,Arsenal,Chelsea,2,1,H,1,0,H,1.80,,4.50,1.95,1.90\n",
            encoding="utf-8",
        )

        completer_cotes([partiel])

        session = base()
        marches = {o.market for o in session.query(OddsSnapshot)}
        session.close()
        assert "1N2" not in marches, "une série 1N2 amputée a été insérée"
        assert "over_under" in marches

    def test_la_cote_d_ouverture_reste_non_datee(self, base, fichier):
        """Une cote d'ouverture n'a pas d'instant de relevé connu ; la lui
        inventer la ferait passer pour une cote pré-match exploitable
        (migration 20260906_purge_odds_movement)."""
        from pipelines.completer_cotes import completer_cotes

        completer_cotes([fichier])

        session = base()
        ouvertures = session.query(OddsSnapshot).filter_by(is_closing=False).all()
        session.close()
        assert ouvertures
        assert all(o.captured_at is None for o in ouvertures)


class TestIdempotenceDeLImport:
    """`historical_import` ne duplique pas les cotes — et ne les rattrape pas.

    Les deux moitiés de la réponse comptent autant l'une que l'autre. Un match
    déjà présent est classé « doublon » et sa ligne abandonnée, cotes
    comprises : relancer l'import ne crée aucun doublon, mais ne corrige rien
    non plus. C'est la raison d'être de ce module, et c'est ce qui décide de la
    marche à suivre quand le parseur gagne des colonnes après coup — le cas
    s'est produit deux fois.
    """

    # Fichier à l'ancienne : agrégats Betbrain, aucune colonne moderne. Avant
    # la correction du parseur, il ne produisait aucune cote Over/Under.
    CSV_BETBRAIN = (
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,"
        "B365H,B365D,B365A,BbMxH,BbMxD,BbMxA,BbMx>2.5,BbMx<2.5\n"
        "E0,13/08/2016,Arsenal,Chelsea,2,1,H,1,0,H,"
        "2.10,3.40,3.60,2.20,3.55,3.80,1.95,1.98\n"
    )

    @pytest.fixture
    def terrain(self, tmp_path, monkeypatch):
        """Base vide, plus le fichier à importer. Aucun match pré-créé."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import pipelines.completer_cotes as module
        from app.models import Competition, Season

        moteur = create_engine(f"sqlite:///{tmp_path / 'idem.db'}")
        Base.metadata.create_all(moteur)
        fabrique = sessionmaker(bind=moteur)
        monkeypatch.setattr(module, "SessionLocal", fabrique)

        session = fabrique()
        comp = Competition(name="Premier League", country="England", provider_code="E0")
        session.add(comp)
        session.flush()
        saison = Season(competition_id=comp.id, season_name="1617")
        session.add(saison)
        session.commit()

        csv = tmp_path / "E0_1617.csv"
        csv.write_text(self.CSV_BETBRAIN, encoding="utf-8")
        return fabrique, session, comp, saison, csv

    @staticmethod
    def _importer(session, comp, saison, csv):
        from collectors.football_data.parser import parse_csv
        from pipelines.historical_import import _process_match_row

        ligne = parse_csv(csv).iloc[0]
        resultat = _process_match_row(session, ligne, comp, saison, "E0", "England")
        session.commit()
        return resultat

    @staticmethod
    def _amputer(session):
        """Retirer ce que l'ancien parseur ne savait pas lire."""
        session.query(OddsSnapshot).filter(
            (OddsSnapshot.bookmaker == "Max") | (OddsSnapshot.market == "over_under")
        ).delete(synchronize_session=False)
        session.commit()

    def test_un_second_import_ne_duplique_aucune_cote(self, terrain):
        from sqlalchemy import func

        _, session, comp, saison, csv = terrain

        premier = self._importer(session, comp, saison, csv)
        apres_un = session.query(func.count(OddsSnapshot.id)).scalar()
        second = self._importer(session, comp, saison, csv)

        assert premier["disposition"] == "inserted"
        assert premier["odds"] > 0
        assert second["disposition"] == "duplicate"
        assert second["odds"] == 0
        assert session.query(func.count(OddsSnapshot.id)).scalar() == apres_un
        assert session.query(func.count(Match.id)).scalar() == 1

    def test_un_second_import_ne_rattrape_rien_non_plus(self, terrain):
        """L'autre moitié, et c'est elle qui dicte la marche à suivre.

        Une cote jamais lue — faute d'une colonne que le parseur ignorait — ne
        revient pas par un réimport : le match existe, sa ligne est abandonnée
        avant même qu'on regarde ses cotes.
        """
        from sqlalchemy import func

        _, session, comp, saison, csv = terrain
        self._importer(session, comp, saison, csv)
        self._amputer(session)
        ampute = session.query(func.count(OddsSnapshot.id)).scalar()

        self._importer(session, comp, saison, csv)

        assert session.query(func.count(OddsSnapshot.id)).scalar() == ampute, (
            "le réimport a rattrapé des cotes, ce qu'il n'est pas censé faire"
        )

    def test_completer_cotes_rattrape_ce_que_l_import_ne_rattrape_pas(self, terrain):
        """Le chemin complet : importer, amputer, rattraper, relancer."""
        from sqlalchemy import func

        from pipelines.completer_cotes import completer_cotes

        fabrique, session, comp, saison, csv = terrain
        self._importer(session, comp, saison, csv)
        complet = session.query(func.count(OddsSnapshot.id)).scalar()
        self._amputer(session)
        session.close()

        rapport = completer_cotes([csv], "E0")

        assert rapport["cotes_ajoutees"] > 0
        assert rapport["matchs_introuvables"] == 0
        with fabrique() as lecture:
            assert lecture.query(func.count(OddsSnapshot.id)).scalar() == complet
            assert "over_under" in {s.market for s in lecture.query(OddsSnapshot).all()}
            assert "Max" in {s.bookmaker for s in lecture.query(OddsSnapshot).all()}

        # Et la relance ne crée rien.
        assert completer_cotes([csv], "E0")["cotes_ajoutees"] == 0
