#!/usr/bin/env python3
"""Script de génération de prédictions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def main():
    """Générer les prédictions pour les matchs à venir."""
    logger.info("=== Génération de prédictions ===")
    # TODO: implémenter avec pipelines.prediction_pipeline
    logger.info("=== Prédictions générées ===")


if __name__ == "__main__":
    main()
