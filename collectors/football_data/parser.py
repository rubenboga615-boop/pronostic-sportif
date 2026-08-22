"""Parseur de fichiers CSV Football-Data.co.uk."""

from pathlib import Path

import pandas as pd
from loguru import logger


# Colonnes attendues (peuvent varier selon les saisons)
RESULT_COLUMNS = {
    "Date": "match_date",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "FTR": "result",
    "HTHG": "home_ht_goals",
    "HTAG": "away_ht_goals",
    "HTR": "ht_result",
    "HS": "home_shots",
    "AS": "away_shots",
    "HST": "home_shots_on_target",
    "AST": "away_shots_on_target",
    "HC": "home_corners",
    "AC": "away_corners",
    "HF": "home_fouls",
    "AF": "away_fouls",
    "HY": "home_yellow",
    "AY": "away_yellow",
    "HR": "home_red",
    "AR": "away_red",
}


def parse_csv(file_path: Path) -> pd.DataFrame:
    """Parser un fichier CSV Football-Data.co.uk."""
    try:
        df = pd.read_csv(file_path, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding="latin-1")

    # Renommer les colonnes disponibles
    rename_map = {k: v for k, v in RESULT_COLUMNS.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # Parser les dates
    if "match_date" in df.columns:
        df["match_date"] = pd.to_datetime(df["match_date"], dayfirst=True, errors="coerce")

    # Convertir les colonnes numériques
    numeric_cols = [
        "home_goals", "away_goals", "home_ht_goals", "away_ht_goals",
        "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info(f"Parsed {file_path.name}: {len(df)} matchs, {len(df.columns)} colonnes")
    return df


def parse_all_files(data_dir: Path) -> pd.DataFrame:
    """Parser tous les fichiers CSV d'un répertoire."""
    all_dfs = []
    for csv_file in data_dir.rglob("*.csv"):
        df = parse_csv(csv_file)
        df["_source_file"] = csv_file.name
        all_dfs.append(df)

    if not all_dfs:
        logger.warning(f"Aucun fichier CSV trouvé dans {data_dir}")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    logger.info(f"Total combiné : {len(combined)} matchs")
    return combined
