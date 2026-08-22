"""Tests du pipeline d'import historique."""

import pytest
import pandas as pd
from datetime import datetime

from app.config import settings
from app.database import SessionLocal
from app.models import Match
from pipelines.historical_import import (
    _make_provider_match_id,
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


class TestProviderMatchId:
    """Tests de l'identifiant provider déterministe et stable."""

    def test_provider_match_id_is_deterministic(self):
        """Deux appels avec les mêmes arguments produisent le même identifiant."""
        args = ("E0", "24", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        assert _make_provider_match_id(*args) == _make_provider_match_id(*args)

    def test_provider_match_id_is_stable_across_process(self):
        """L'identifiant ne dépend pas de hash() (salé par processus).

        Valeur attendue pré-calculée via SHA-256 sur la clé canonique
        ``E0|24|2024-01-01T00:00:00|Arsenal|Chelsea`` : identique quel que soit
        le processus ou la machine.
        """
        expected_digest = "b67abdbcf695805edae6a419fe4b49cea082d5641b8ba2fb7d03cc8e62525da2"
        result = _make_provider_match_id("E0", "24", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        assert result == f"fd_E0_24_{expected_digest}"

    def test_provider_match_id_respects_home_away_order(self):
        """PSG|Lyon ne doit jamais produire le même identifiant que Lyon|PSG."""
        home_away = _make_provider_match_id("F1", "24", datetime(2024, 1, 1), "PSG", "Lyon")
        away_home = _make_provider_match_id("F1", "24", datetime(2024, 1, 1), "Lyon", "PSG")
        assert home_away != away_home

    def test_provider_match_id_differs_on_distinct_matches(self):
        """Des matchs différents (date ou équipe) produisent des identifiants différents."""
        base = _make_provider_match_id("E0", "24", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        diff_date = _make_provider_match_id("E0", "24", datetime(2024, 1, 2), "Arsenal", "Chelsea")
        diff_team = _make_provider_match_id("E0", "24", datetime(2024, 1, 1), "Arsenal", "Tottenham")
        assert base != diff_date
        assert base != diff_team

    def test_provider_match_id_includes_league_and_season(self):
        """Le code ligue et la saison sont inclus : pas de collision entre compétitions."""
        e0 = _make_provider_match_id("E0", "24", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        sp1 = _make_provider_match_id("SP1", "24", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        s24 = _make_provider_match_id("E0", "24", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        s25 = _make_provider_match_id("E0", "25", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        assert e0 != sp1
        assert s24 != s25

    def test_provider_match_id_missing_date(self):
        """Une date manquante (NaT) produit un identifiant stable sans crash."""
        a = _make_provider_match_id("E0", "24", pd.NaT, "Arsenal", "Chelsea")
        b = _make_provider_match_id("E0", "24", pd.NaT, "Arsenal", "Chelsea")
        assert a == b
        assert a.startswith("fd_E0_24_")

    def test_provider_match_id_format(self):
        """Le format respecte le préfixe et le digest SHA-256 complet (64 hex)."""
        mid = _make_provider_match_id("E0", "2024/2025", datetime(2024, 1, 1), "Arsenal", "Chelsea")
        assert mid.startswith("fd_E0_2024/2025_")
        digest = mid.rsplit("_", 1)[-1]
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_import_uses_provider_match_id(self):
        """L'identifiant déterministe est bien persisté lors de l'insertion."""
        csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
01/01/2024,Arsenal,Chelsea,2,1,H
"""
        raw_dir = settings.raw_dir / "football_data" / "E0"
        raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = raw_dir / "E0_24_pmid.csv"
        csv_file.write_text(csv_content)
        try:
            run_historical_import(
                league_codes=["E0"],
                seasons=["24"],
                skip_download=True,
            )
            session = SessionLocal()
            try:
                match = session.query(Match).filter_by(provider="football_data").first()
                assert match is not None
                home_canonical = normalize_team_name("Arsenal", "E0")
                away_canonical = normalize_team_name("Chelsea", "E0")
                expected = _make_provider_match_id(
                    "E0", "24", match.match_date, home_canonical, away_canonical
                )
                assert match.provider_match_id == expected
            finally:
                session.close()
        finally:
            csv_file.unlink(missing_ok=True)
