#!/usr/bin/env python3
"""Script d'import des données historiques.

Usage:
    python scripts/import_historical_data.py
    python scripts/import_historical_data.py --seasons 2324 2223
    python scripts/import_historical_data.py --leagues E0 SP1
    python scripts/import_historical_data.py --skip-download
    python scripts/import_historical_data.py --force
"""

import argparse
import sys
from pathlib import Path

# Ajouter la racine du projet au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from pipelines.historical_import import run_historical_import


def main() -> None:
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(
        description="Importer les données historiques Football-Data.co.uk"
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=None,
        help="Saisons à importer (ex: 2324 2223). Défaut : toutes.",
    )
    parser.add_argument(
        "--leagues",
        nargs="+",
        default=None,
        help="Ligues à importer (ex: E0 SP1). Défaut : toutes.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Ne pas télécharger, utiliser les fichiers existants.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-télécharger les fichiers existants.",
    )
    args = parser.parse_args()

    logger.info("=== Script d'import historique ===")
    report = run_historical_import(
        league_codes=args.leagues,
        seasons=args.seasons,
        skip_download=args.skip_download,
        force_download=args.force,
    )
    logger.info("=== Terminé ===")
    logger.info(
        f"Résultat: {report['files_processed']} fichiers, "
        f"{report['matches_inserted']} matchs insérés, "
        f"{report['matches_skipped_duplicates']} doublons"
    )


if __name__ == "__main__":
    main()
