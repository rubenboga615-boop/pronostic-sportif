#!/usr/bin/env python3
"""Script de création de sauvegarde."""

import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from app.config import settings


def main():
    """Créer une sauvegarde de la base de données et des données."""
    logger.info("=== Création de sauvegarde ===")

    backup_dir = settings.backups_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Sauvegarder la base de données
    db_path = Path("data/pronostic.db")
    if db_path.exists():
        backup_db = backup_dir / f"pronostic_{timestamp}.db"
        shutil.copy2(db_path, backup_db)
        logger.info(f"Base de données sauvegardée : {backup_db}")

    logger.info("=== Sauvegarde terminée ===")


if __name__ == "__main__":
    main()
