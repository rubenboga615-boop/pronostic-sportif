"""Tests de l'import des cotes Over/Under et du suivi des colonnes de la source.

Deux constats de l'audit sont couverts ici :

- les colonnes de cotes Over/Under 2,5 existaient dans les fichiers depuis
  toujours mais n'étaient pas lues, ce qui rendait impossible tout calcul
  d'``edge`` sur l'un des marchés de la Phase 1 ;
- le format de Football-Data.co.uk change au fil des saisons sans que rien ne
  le signale — Interwetten a disparu entre 2023/24 et 2024/25, et les colonnes
  ``BbMx*`` étaient encore déclarées alors qu'elles n'existent plus.
"""

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import Competition, OddsSnapshot, Season
from collectors.football_data.parser import inspecter_colonnes, parse_csv
from pipelines.historical_import import SERIES_DE_COTES, _process_match_row

EN_TETE = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,"
    "HS,AS,HST,AST,HC,AC,HF,AF,HY,AY,HR,AR,"
    "B365H,B365D,B365A,BWH,BWD,BWA,PSH,PSD,PSA,"
    "MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,"
    "B365>2.5,B365<2.5,P>2.5,P<2.5,Max>2.5,Max<2.5,Avg>2.5,Avg<2.5,"
    "B365CH,B365CD,B365CA,PSCH,PSCD,PSCA,"
    "B365C>2.5,B365C<2.5,PC>2.5,PC<2.5"
)
LIGNE = (
    "E0,12/08/2023,Arsenal,Chelsea,2,1,H,1,0,H,"
    "15,9,6,3,7,4,10,12,1,2,0,0,"
    "1.90,3.60,4.20,1.88,3.55,4.10,1.92,3.65,4.30,"
    "1.95,3.70,4.40,1.89,3.58,4.15,"
    "1.80,2.05,1.82,2.08,1.85,2.10,1.81,2.06,"
    "1.85,3.70,4.50,1.87,3.72,4.55,"
    "1.75,2.12,1.77,2.14"
)


@pytest.fixture
def fichier_csv(tmp_path):
    chemin = tmp_path / "E0_2324.csv"
    chemin.write_text(f"{EN_TETE}\n{LIGNE}\n", encoding="utf-8")
    return chemin


class TestLectureDesCotesOverUnder:
    def test_les_colonnes_sont_lues(self, fichier_csv):
        df = parse_csv(fichier_csv)

        assert df.loc[0, "odds_b365_over_25"] == pytest.approx(1.80)
        assert df.loc[0, "odds_b365_under_25"] == pytest.approx(2.05)
        assert df.loc[0, "odds_b365_close_over_25"] == pytest.approx(1.75)
        assert df.loc[0, "odds_pinnacle_close_under_25"] == pytest.approx(2.14)

    def test_la_cloture_pinnacle_1n2_est_lue(self, fichier_csv):
        """PSCH/PSCD/PSCA n'étaient pas mappées : une clôture de plus perdue."""
        df = parse_csv(fichier_csv)

        assert df.loc[0, "odds_pinnacle_close_home"] == pytest.approx(1.87)

    def test_les_cotes_max_et_moyennes_sont_lues(self, fichier_csv):
        """MaxH/AvgH ont remplacé BbMxH, qui n'existe plus dans aucun fichier."""
        df = parse_csv(fichier_csv)

        assert df.loc[0, "max_odds_home"] == pytest.approx(1.95)
        assert df.loc[0, "avg_odds_away"] == pytest.approx(4.15)


class TestSuiviDesColonnes:
    def test_une_colonne_requise_absente_est_signalee(self):
        rapport = inspecter_colonnes(["Date", "HomeTeam", "AwayTeam", "FTHG"])

        assert rapport["manquantes_requises"] == ["FTAG"]

    def test_une_colonne_toleree_absente_est_signalee(self, fichier_csv):
        """Interwetten n'est pas dans ce fichier : la disparition est visible."""
        df = parse_csv(fichier_csv)

        manquantes = df.attrs["colonnes"]["manquantes_tolerees"]
        assert {"IWH", "IWD", "IWA"} <= set(manquantes)
        assert df.attrs["colonnes"]["manquantes_requises"] == []

    def test_un_fichier_complet_ne_signale_rien(self):
        from collectors.football_data.parser import RESULT_COLUMNS

        rapport = inspecter_colonnes(list(RESULT_COLUMNS))

        assert rapport == {"manquantes_requises": [], "manquantes_tolerees": []}

    def test_bbmx_n_est_plus_attendue(self):
        """Les colonnes mortes ne doivent plus figurer parmi les attendues."""
        from collectors.football_data.parser import RESULT_COLUMNS

        assert not [c for c in RESULT_COLUMNS if c.startswith("BbMx")]


class TestSeriesDeCotes:
    def test_le_marche_over_under_est_declare(self):
        marches = {serie["market"] for serie in SERIES_DE_COTES}

        assert marches == {"1N2", "over_under"}

    def test_les_selections_suivent_le_contrat_public(self):
        """Les sélections doivent être celles que persist_predictions accepte."""
        from models.market_assembly import PUBLIC_SELECTIONS

        for serie in SERIES_DE_COTES:
            if serie["market"] != "over_under":
                continue
            assert set(serie["selections"]) <= PUBLIC_SELECTIONS["over_under"]


class TestInsertionEnBase:
    @pytest.fixture
    def contexte(self):
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()
        comp = Competition(name="Premier League", country="England", provider_code="E0")
        session.add(comp)
        session.flush()
        saison = Season(competition_id=comp.id, season_name="2324")
        session.add(saison)
        session.flush()
        yield session, comp, saison
        session.close()

    def _importer(self, contexte, fichier_csv):
        session, comp, saison = contexte
        ligne = parse_csv(fichier_csv).iloc[0]
        resultat = _process_match_row(session, ligne, comp, saison, "E0", "England")
        session.commit()
        return resultat

    def test_les_cotes_over_under_sont_persistees(self, contexte, fichier_csv):
        session, _, _ = contexte
        self._importer(contexte, fichier_csv)

        with Session(engine) as lecture:
            ou = (
                lecture.query(OddsSnapshot)
                .filter_by(market="over_under", bookmaker="B365", is_closing=False)
                .all()
            )

        assert {snap.selection for snap in ou} == {"over_2.5", "under_2.5"}
        assert sorted(snap.odds for snap in ou) == pytest.approx([1.80, 2.05])

    def test_les_cotes_d_ouverture_ne_sont_pas_datees(self, contexte, fichier_csv):
        """Football-Data ne publie pas l'instant du relevé d'ouverture.

        Le prétendre connu ferait passer une cote non datée pour une cote
        pré-match exploitable. La colonne porte un `default=utcnow` qu'il faut
        neutraliser explicitement.
        """
        self._importer(contexte, fichier_csv)

        with Session(engine) as lecture:
            ouvertures = lecture.query(OddsSnapshot).filter_by(is_closing=False).all()
            clotures = lecture.query(OddsSnapshot).filter_by(is_closing=True).all()

        assert ouvertures and clotures
        assert all(snap.captured_at is None for snap in ouvertures)
        assert all(snap.captured_at == pd.Timestamp("2023-08-12") for snap in clotures)

    def test_une_serie_incomplete_est_ignoree(self, contexte, tmp_path):
        """Sans les deux cotes d'un Over/Under, la marge n'est pas calculable."""
        sans_under = tmp_path / "E0_2324.csv"
        colonnes = EN_TETE.split(",")
        valeurs = LIGNE.split(",")
        valeurs[colonnes.index("B365<2.5")] = ""
        sans_under.write_text(f"{EN_TETE}\n{','.join(valeurs)}\n", encoding="utf-8")

        self._importer(contexte, sans_under)

        with Session(engine) as lecture:
            ou = (
                lecture.query(OddsSnapshot)
                .filter_by(market="over_under", bookmaker="B365", is_closing=False)
                .all()
            )

        assert ou == []
