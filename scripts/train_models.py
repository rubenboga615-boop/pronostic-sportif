#!/usr/bin/env python3
"""Script d'entraînement des modèles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def main():
    """Entraîner les modèles de prédiction."""
    logger.info("=== Entraînement des modèles ===")

    models_to_train = [
        "Poisson",
        "Dixon-Coles",
        "Régression logistique",
        "XGBoost (si disponible)",
    ]

    for model in models_to_train:
        logger.info(f"Entraînement : {model}")
        # TODO: implémenter l'entraînement

    logger.info("=== Entraînement terminé ===")


if __name__ == "__main__":
    main()
