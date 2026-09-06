"""Tests d'isolation des chemins de données.

Vérifie que les tests n'écrivent pas dans les répertoires de production
(``data/raw``, ``data/cleaned``) : les répertoires d'écriture sont redirigés
vers des dossiers temporaires.
"""

from pathlib import Path

from app.config import settings

PRODUCTION_RAW = Path("data/raw").resolve()
PRODUCTION_CLEANED = Path("data/cleaned").resolve()


def test_raw_dir_redirected():
    """Le répertoire raw utilisé par les tests n'est pas celui de production."""
    assert settings.raw_dir.resolve() != PRODUCTION_RAW


def test_cleaned_dir_redirected():
    """Le répertoire cleaned utilisé par les tests n'est pas celui de production."""
    assert settings.cleaned_dir.resolve() != PRODUCTION_CLEANED


def test_import_does_not_touch_production_cleaned():
    """L'import de test écrit le rapport dans le répertoire temporaire, pas en production."""
    from pipelines.historical_import import run_historical_import

    prod_report = PRODUCTION_CLEANED / "import_report.json"
    before = prod_report.read_bytes() if prod_report.exists() else None

    raw_league_dir = settings.raw_dir / "football_data" / "E0"
    raw_league_dir.mkdir(parents=True, exist_ok=True)
    csv_file = raw_league_dir / "E0_24_iso.csv"
    csv_file.write_text("Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2024,Wolves,Tottenham,3,0,H\n")

    run_historical_import(league_codes=["E0"], seasons=["24"], skip_download=True)

    # Le rapport doit être écrit dans le répertoire temporaire
    assert (settings.cleaned_dir / "import_report.json").exists()

    # La production ne doit pas avoir été modifiée
    after = prod_report.read_bytes() if prod_report.exists() else None
    assert after == before
