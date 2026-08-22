"""Tests des parseurs de données."""

import pandas as pd
import pytest
from pathlib import Path
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
