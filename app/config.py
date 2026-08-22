"""Configuration de l'application."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Paramètres de l'application chargés depuis les variables d'environnement."""

    # App
    app_env: str = "development"
    app_debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Database
    database_url: str = "sqlite:///data/pronostic.db"

    # API Keys
    api_football_key: str = ""
    odds_api_key: str = ""

    # Cache
    cache_dir: str = "data/cache"
    cache_ttl_hours: int = 24

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/app.log"

    # Paths
    data_dir: Path = Path("data")
    raw_dir: Path = Path("data/raw")
    cleaned_dir: Path = Path("data/cleaned")
    features_dir: Path = Path("data/features")
    backups_dir: Path = Path("data/backups")

    # Pipeline
    pipeline_daily_hour: int = 6
    pipeline_prediction_hour: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
