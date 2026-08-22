#!/usr/bin/env python3
"""Script d'import des données historiques."""

import asyncio
import sys
from pathlib import Path

# Ajouter la racine du projet au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from pipelines.historical_import import run_historical_import


def main():
    """Point d'entrée principal."""
    logger.info("=== Script d'import historique ===")
    run_historical_import()
    logger.info("=== Terminé ===")


if __name__ == "__main__":
    main()
