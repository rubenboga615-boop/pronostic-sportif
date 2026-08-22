#!/usr/bin/env python3
"""Script de validation des données.

Vérifie l'intégrité et la qualité des données importées.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pandas as pd
from loguru import logger


def validate_csv(file_path: Path) -> dict:
    """Valider un fichier CSV."""
    try:
        df = pd.read_csv(file_path)
        return {
            "file": file_path.name,
            "status": "ok",
            "rows": len(df),
            "columns": len(df.columns),
            "null_counts": df.isnull().sum().to_dict(),
        }
    except Exception as e:
        return {
            "file": file_path.name,
            "status": "error",
            "error": str(e),
        }


def validate_all(data_dir: Path) -> list[dict]:
    """Valider tous les fichiers CSV d'un répertoire."""
    results = []
    for csv_file in data_dir.rglob("*.csv"):
        result = validate_csv(csv_file)
        results.append(result)
        status = result["status"]
        if status == "ok":
            logger.info(f"✅ {result['file']}: {result['rows']} lignes")
        else:
            logger.error(f"❌ {result['file']}: {result.get('error', 'erreur inconnue')}")
    return results


if __name__ == "__main__":
    data_dir = Path("data/raw/football_data")
    if data_dir.exists():
        results = validate_all(data_dir)
        ok = sum(1 for r in results if r["status"] == "ok")
        logger.info(f"Validation : {ok}/{len(results)} fichiers OK")
    else:
        logger.warning(f"Répertoire non trouvé : {data_dir}")
