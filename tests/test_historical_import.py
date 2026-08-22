"""Tests du pipeline d'import historique."""

import pytest
import pandas as pd
from datetime import datetime

from app.config import settings
from pipelines.historical_import import (
    _validate_goals,
    _validate_date,
    run_historical_import,
)
from collectors.football_data.parser import parse_csv
from collectors.football_data.team_normalizer import normalize_team_name


class TestValidateGoals:
    """Tests de validation des buts."""

    def test_valid_goals(self):
        row = pd.Series({"home_goals": 2, "away_goals": 1})
        assert _validate_goals(row) == []

    def test_ht_goals_less_than_ft(self):
        row = pd.Series({"home_goals": 2, "away_goals": 1, "home_ht_goals": 1, "away_ht_goals": 0})
        assert _validate_goals(row) == []

    def test_ht_goals_greater_than_ft_home(self):
        row = pd.Series({"home_goals": 1, "away_goals": 0, "home_ht_goals": 2, "away_ht_goals": 0})
        warnings = _validate_goals(row)
        assert len(warnings) == 1
        assert "HT home 2 > FT home 1" in warnings[0]

    def test_ht_goals_greater_than_ft_away(self):
        row = pd.Series({"home_goals": 1, "away_goals": 0, "home_ht_goals": 0, "away_ht_goals": 1})
        warnings = _validate_goals(row)
        assert len(warnings) == 1
        assert "HT away 1 > FT away 0" in warnings[0]

    def test_negative_goals(self):
        row = pd.Series({"home_goals": -1, "away_goals": 0})
        warnings = _validate_goals(row)
        assert any("négatifs" in w for w in warnings)


class TestValidateDate:
    """Tests de validation des dates."""

    def test_valid_date(self):
        row = pd.Series({"match_date": datetime(2024, 1, 1)})
        assert _validate_date(row) == []

    def test_missing_date(self):
        row = pd.Series({"match_date": pd.NaT})
        warnings = _validate_date(row)
        assert len(warnings) == 1
        assert "manquante" in warnings[0]

    def test_suspicious_year(self):
        row = pd.Series({"match_date": datetime(1999, 1, 1)})
        warnings = _validate_date(row)
        assert any("suspecte" in w for w in warnings)


class TestHistoricalImport:
    """Tests du pipeline d'import historique."""

    def test_import_produces_report(self):
        """Vérifier que l'import produit un rapport."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,HS,AS,B365H,B365D,B365A
01/01/2024,Arsenal,Chelsea,2,1,H,1,0,H,15,10,1.5,4.0,6.5
08/01/2024,Liverpool,Manchester City,1,1,D,0,0,D,12,14,2.5,3.5,2.8
"""
        raw_dir = settings.raw_dir / "football_data" / "E0"
        raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = raw_dir / "E0_24_test.csv"
        csv_file.write_text(csv_content)

        try:
            report = run_historical_import(
                league_codes=["E0"],
                seasons=["24"],
                skip_download=True,
            )

            assert "files_processed" in report
            assert report["files_processed"] >= 1
            assert "matches_inserted" in report
            assert "total_matches" in report
        finally:
            csv_file.unlink(missing_ok=True)

    def test_import_no_csv_returns_empty_report(self):
        """Vérifier que l'import sans fichier retourne un rapport vide."""
        report = run_historical_import(
            league_codes=["XX"],
            seasons=["9999"],
            skip_download=True,
        )
        assert report["files_processed"] == 0

    def test_import_deduplication(self):
        """Vérifier que les doublons sont détectés au sein du même fichier."""
        # Utiliser des équipes uniques pour ne pas碰撞er avec d'autres tests
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
01/01/2024,Wolves,Tottenham,3,0,H
01/01/2024,Wolves,Tottenham,3,0,H
"""
        raw_dir = settings.raw_dir / "football_data" / "E0"
        raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = raw_dir / "E0_24_dedup.csv"
        csv_file.write_text(csv_content)

        try:
            report = run_historical_import(
                league_codes=["E0"],
                seasons=["24"],
                skip_download=True,
            )
            # Seulement 1 match inséré malgré 2 lignes identiques
            assert report["matches_inserted"] == 1
        finally:
            csv_file.unlink(missing_ok=True)
