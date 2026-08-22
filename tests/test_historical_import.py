"""Tests du pipeline d'import historique."""

import pytest
import pandas as pd
from datetime import datetime

from app.config import settings
from pipelines.historical_import import (
    _process_match_row,
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
            assert "rows_read" in report
            assert report["rows_read"] == 2
            assert report["matches_inserted"] == 2
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
            assert report["rows_read"] == 2
            assert report["matches_inserted"] == 1
            assert report["matches_duplicates"] == 1
            assert report["matches_skipped_invalid"] == 0
            assert report["rows_errored"] == 0
            # Invariant de conservation du rapport
            assert (
                report["rows_read"]
                == report["matches_inserted"]
                + report["matches_duplicates"]
                + report["matches_skipped_invalid"]
                + report["rows_errored"]
            )
        finally:
            csv_file.unlink(missing_ok=True)


class TestReportCounters:
    """Tests des compteurs du rapport d'import."""

    def test_missing_team_is_skipped_invalid(self):
        """Une ligne sans équipe est classée 'invalid' (non insérée)."""
        row = pd.Series({"home_team": None, "away_team": "Chelsea"})
        result = _process_match_row(None, row, None, None, "E0", "England")
        assert result["disposition"] == "invalid"

    def test_teams_odds_stats_counted(self):
        """Les équipes, cotes et stats sont réellement comptées."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,B365H,B365D,B365A
01/01/2024,Arsenal,Chelsea,2,1,H,15,10,1.5,4.0,6.5
"""
        raw_dir = settings.raw_dir / "football_data" / "E0"
        raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = raw_dir / "E0_24_cnt.csv"
        csv_file.write_text(csv_content)
        try:
            report = run_historical_import(
                league_codes=["E0"],
                seasons=["24"],
                skip_download=True,
            )
            assert report["matches_inserted"] == 1
            assert report["teams_created"] == 2
            assert report["odds_inserted"] == 3  # 1 bookmaker x 3 sélections
            assert report["stats_inserted"] == 2  # domicile + extérieur
        finally:
            csv_file.unlink(missing_ok=True)

    def test_validation_warnings_counted(self):
        """Les buts négatifs sont comptés et remontés (sans bloquer l'insertion)."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
01/01/2024,Arsenal,Chelsea,-1,0,H
"""
        raw_dir = settings.raw_dir / "football_data" / "E0"
        raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = raw_dir / "E0_24_warn.csv"
        csv_file.write_text(csv_content)
        try:
            report = run_historical_import(
                league_codes=["E0"],
                seasons=["24"],
                skip_download=True,
            )
            # La ligne reste insérée (validation non bloquante)...
            assert report["matches_inserted"] == 1
            # ...mais le warning est compté et visible.
            assert report["validation_warnings"] >= 1
            assert any("négatifs" in w for w in report["warnings"])
        finally:
            csv_file.unlink(missing_ok=True)
