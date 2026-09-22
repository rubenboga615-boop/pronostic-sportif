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

        assert rapport == {
            "manquantes_requises": [],
            "manquantes_tolerees": [],
            "cotes_ignorees": [],
        }

    def test_les_colonnes_betbrain_sont_lues(self):
        """Elles ne sont pas mortes : c'est l'ancien nom des agrégats.

        Football-Data a renommé `BbMx` en `Max` et `BbAv` en `Avg` en 2019/20.
        Les avoir prises pour des colonnes obsolètes coûtait les cotes de trois
        saisons sur onze — 20 034 matchs sur le corpus complet — et
        l'inspection ne pouvait rien signaler, puisque la colonne n'avait pas
        disparu du fichier : elle avait disparu du parseur.
        """
        from collectors.football_data.parser import RESULT_COLUMNS

        for ancienne, moderne in (
            ("BbMxH", "MaxH"),
            ("BbAvA", "AvgA"),
            ("BbMx>2.5", "Max>2.5"),
            ("BbAv<2.5", "Avg<2.5"),
        ):
            assert ancienne in RESULT_COLUMNS, ancienne
            assert RESULT_COLUMNS[ancienne] == RESULT_COLUMNS[moderne], (
                f"{ancienne} et {moderne} désignent la même grandeur"
            )

    def test_une_graphie_d_epoque_absente_n_est_pas_une_anomalie(self):
        """`BbMxH` manque dans un fichier moderne, et c'est normal.

        Sans cette distinction, chaque fichier signalerait une dizaine de
        fausses disparitions, et on cesserait de lire le rapport — ce qui
        rendrait le contrôle inutile au moment précis où il servirait.
        """
        modernes = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "MaxH", "MaxD", "MaxA"]

        rapport = inspecter_colonnes(modernes)

        assert not [c for c in rapport["manquantes_tolerees"] if c.startswith("Bb")]
        assert "MaxH" not in rapport["manquantes_tolerees"]

    def test_une_cote_presente_et_lue_par_personne_est_signalee(self):
        """Le contrôle qui manquait, et qui aurait attrapé le défaut Betbrain.

        L'inspection ne regardait que ce qui manquait, jamais ce qui était
        offert par la source et laissé de côté. Les colonnes Betbrain étaient
        remplies à 100 %, et rien ne disait qu'elles partaient à la poubelle.
        """
        avec_inconnue = [
            "Date",
            "HomeTeam",
            "AwayTeam",
            "FTHG",
            "FTAG",
            "NEWBOOKH",
            "NEWBOOKD",
            "NEWBOOKA",
        ]

        rapport = inspecter_colonnes(avec_inconnue)

        assert set(rapport["cotes_ignorees"]) == {"NEWBOOKH", "NEWBOOKD", "NEWBOOKA"}

    def test_les_marches_hors_perimetre_ne_sont_pas_signales(self):
        """Le handicap asiatique est de Phase 2 : l'ignorer est une décision."""
        rapport = inspecter_colonnes(
            ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "B365AHH", "AHh", "BFH"]
        )

        assert rapport["cotes_ignorees"] == []


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

    def test_un_fichier_d_avant_2019_donne_bien_ses_cotes(self, contexte, tmp_path):
        """Le défaut, vérifié de bout en bout sur un fichier à l'ancienne.

        Avant la correction, un CSV Betbrain produisait **zéro** relevé
        Over/Under — mesuré sur 1617/E0 : 1 520 relevés manquants pour un seul
        fichier, 20 034 matchs sur le corpus complet.
        """
        ancien = tmp_path / "E0_1617.csv"
        ancien.write_text(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,"
            "B365H,B365D,B365A,BbMxH,BbMxD,BbMxA,BbAvH,BbAvD,BbAvA,"
            "BbMx>2.5,BbAv>2.5,BbMx<2.5,BbAv<2.5\n"
            "E0,13/08/2016,Arsenal,Chelsea,2,1,H,1,0,H,"
            "2.10,3.40,3.60,2.20,3.55,3.80,2.05,3.30,3.50,"
            "1.95,1.88,1.98,1.92\n",
            encoding="utf-8",
        )

        self._importer(contexte, ancien)

        with Session(engine) as lecture:
            ou = lecture.query(OddsSnapshot).filter_by(market="over_under").all()
            agregats = lecture.query(OddsSnapshot).filter_by(bookmaker="Max").all()

        assert {s.selection for s in ou} == {"over_2.5", "under_2.5"}
        # La meilleure cote du marché est celle de BbMx, lue comme `Max`.
        prix = {(s.market, s.selection): s.odds for s in agregats}
        assert prix[("1N2", "home")] == pytest.approx(2.20)
        assert prix[("over_under", "over_2.5")] == pytest.approx(1.95)

    def test_les_agregats_sont_marques_comme_tels(self, contexte, fichier_csv):
        """Ils doivent être reconnaissables en base, pour que la valorisation
        puisse les écarter du calcul de la probabilité de marché."""
        from evaluation.pricing import AGREGATS_DE_MARCHE

        self._importer(contexte, fichier_csv)

        with Session(engine) as lecture:
            books = {s.bookmaker for s in lecture.query(OddsSnapshot).all()}

        assert books & AGREGATS_DE_MARCHE, "aucun agrégat persisté"
        assert books - AGREGATS_DE_MARCHE, "aucun bookmaker réel persisté"

    def test_les_cotes_d_ouverture_ne_sont_pas_datees(self, contexte, fichier_csv):
        """Football-Data ne publie pas l'instant du relevé d'ouverture.

        Le prétendre connu ferait passer une cote non datée pour une cote
        pré-match exploitable. La colonne porte un `default=maintenant_utc` qu'il faut
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
