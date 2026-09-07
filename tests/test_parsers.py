"""Tests des parseurs de données."""

import pandas as pd

from collectors.football_data.parser import parse_csv


class TestParser:
    """Tests du parseur CSV Football-Data.co.uk."""

    def test_parse_csv_columns(self, tmp_path):
        """Vérifier que les colonnes sont correctement renommées."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR
2024-01-01,Arsenal,Chelsea,2,1,H,1,0,H
2024-01-08,Liverpool,Man Utd,1,1,D,0,0,D
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert "match_date" in df.columns
        assert "home_team" in df.columns
        assert "away_team" in df.columns
        assert "home_goals" in df.columns
        assert "away_goals" in df.columns

    def test_parse_csv_dates(self, tmp_path):
        """Vérifier que les dates sont correctement parsées."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
01/01/2024,Arsenal,Chelsea,2,1,H
08/01/2024,Liverpool,Man Utd,1,1,D
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert pd.api.types.is_datetime64_any_dtype(df["match_date"])

    def test_parse_csv_numeric_goals(self, tmp_path):
        """Vérifier que les buts sont numériques."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
2024-01-01,Arsenal,Chelsea,2,1,H
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert pd.api.types.is_numeric_dtype(df["home_goals"])
        assert pd.api.types.is_numeric_dtype(df["away_goals"])

    def test_parse_csv_goals_are_integers(self, tmp_path):
        """Vérifier que les buts sont convertis en entiers."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
01/01/2024,Arsenal,Chelsea,2,1,H
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert df["home_goals"].iloc[0] == 2
        assert df["away_goals"].iloc[0] == 1

    def test_parse_csv_odds_columns(self, tmp_path):
        """Vérifier que les colonnes de cotes sont correctement renommées."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A
01/01/2024,Arsenal,Chelsea,2,1,H,1.5,4.0,6.5
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert "odds_b365_home" in df.columns
        assert "odds_b365_draw" in df.columns
        assert "odds_b365_away" in df.columns
        assert df["odds_b365_home"].iloc[0] == 1.5

    def test_parse_csv_missing_columns(self, tmp_path):
        """Vérifier que les colonnes absentes ne provoquent pas d'erreur."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
01/01/2024,Arsenal,Chelsea,2,1,H
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        # Colonnes absentes ne sont pas dans le résultat
        assert "home_ht_goals" not in df.columns or df["home_ht_goals"].isna().all()
        # Le parsing ne plante pas

    def test_parse_csv_encoding_latin1(self, tmp_path):
        """Vérifier que les fichiers latin-1 sont parsés."""
        csv_content = (
            "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
            "01/01/2024,Mallorca,Atl\\u00e9tico Madrid,1,0,H\n"
        )
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content, encoding="latin-1")

        df = parse_csv(csv_file)

        assert len(df) == 1

    def test_parse_csv_drop_empty_rows(self, tmp_path):
        """Vérifier que les lignes sans équipes sont supprimées."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
01/01/2024,Arsenal,Chelsea,2,1,H
,,
08/01/2024,Liverpool,Man Utd,1,1,D
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert len(df) == 2

    def test_parse_csv_ht_stats(self, tmp_path):
        """Vérifier que les statistiques mi-temps sont parsées."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR
01/01/2024,Arsenal,Chelsea,2,1,H,1,0,H
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert "home_ht_goals" in df.columns
        assert df["home_ht_goals"].iloc[0] == 1

    def test_parse_csv_shots_and_corners(self, tmp_path):
        """Vérifier que les tirs et corners sont parsés."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,HST,AST,HC,AC
01/01/2024,Arsenal,Chelsea,2,1,H,15,10,7,4,8,3
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        df = parse_csv(csv_file)

        assert "home_shots" in df.columns
        assert df["home_shots"].iloc[0] == 15
        assert df["away_shots_on_target"].iloc[0] == 4
        assert df["home_corners"].iloc[0] == 8


class TestArbitre:
    """La colonne Referee est lue, nettoyée, et tolérée absente.

    Sans effet sur les marchés de buts de la Phase 1. Importée maintenant parce
    qu'elle est gratuite, présente dans le CSV, et qu'elle serait irrécupérable
    a posteriori — les fichiers de Football-Data ne sont pas versionnés.
    """

    def test_l_arbitre_est_lu(self, tmp_path):
        csv = tmp_path / "E0_2526.csv"
        csv.write_text(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,Referee\n"
            "E0,10/08/2025,Arsenal,Chelsea,2,1,H,M Oliver\n",
            encoding="utf-8",
        )

        df = parse_csv(csv)

        assert "referee" in df.columns
        assert df["referee"].iloc[0] == "M Oliver"

    def test_son_absence_est_toleree(self, tmp_path):
        """Elle manque dans les saisons anciennes de certains championnats."""
        csv = tmp_path / "E0_1415.csv"
        csv.write_text(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,10/08/2014,Arsenal,Chelsea,2,1,H\n",
            encoding="utf-8",
        )

        df = parse_csv(csv)

        assert "referee" not in df.columns or df["referee"].isna().all()
