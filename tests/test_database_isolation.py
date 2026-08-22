"""Tests d'isolation de la base de données.

Vérifie que la suite de tests n'utilise jamais la base de production
(``data/pronostic.db``) et que le moteur SQLAlchemy pointe bien vers la base de
test temporaire dédiée.
"""

from pathlib import Path

from app.config import settings
from app.database import engine


PRODUCTION_DB_PATH = Path("data/pronostic.db").resolve()


def _settings_db_path() -> Path:
    """Chemin de la base configurée, déduit de ``settings.database_url``."""
    return Path(settings.database_url.replace("sqlite:///", "")).resolve()


def test_settings_point_away_from_production():
    """La configuration ne doit pas pointer vers la base de production."""
    assert _settings_db_path() != PRODUCTION_DB_PATH


def test_engine_uses_same_database_as_settings():
    """Le moteur SQLAlchemy doit utiliser la même base que la configuration."""
    assert Path(engine.url.database).resolve() == _settings_db_path()


def test_engine_is_not_production():
    """Le moteur SQLAlchemy ne doit pas pointer vers la base de production."""
    assert Path(engine.url.database).resolve() != PRODUCTION_DB_PATH
