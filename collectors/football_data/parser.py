"""Parseur de fichiers CSV Football-Data.co.uk."""

from pathlib import Path

import pandas as pd
from loguru import logger

# Colonnes attendues (peuvent varier selon les saisons)
RESULT_COLUMNS = {
    # Identité
    "Div": "division",
    "Date": "match_date",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    # Score final
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "FTR": "result",
    # Score mi-temps
    "HTHG": "home_ht_goals",
    "HTAG": "away_ht_goals",
    "HTR": "ht_result",
    # Statistiques match
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
    # Cotes Bet365 (ouverture)
    "B365H": "odds_b365_home",
    "B365D": "odds_b365_draw",
    "B365A": "odds_b365_away",
    # Cotes Bet365 (clôture)
    "B365CH": "odds_b365_close_home",
    "B365CD": "odds_b365_close_draw",
    "B365CA": "odds_b365_close_away",
    # Cotes BWin
    "BWH": "odds_bw_home",
    "BWD": "odds_bw_draw",
    "BWA": "odds_bw_away",
    # Cotes Interwetten
    "IWH": "odds_iw_home",
    "IWD": "odds_iw_draw",
    "IWA": "odds_iw_away",
    # Cotes Pinnacle
    "PSH": "odds_pinnacle_home",
    "PSD": "odds_pinnacle_draw",
    "PSA": "odds_pinnacle_away",
    # Max odds (BbMx = Best odds max across bookmakers)
    "BbMxH": "max_odds_home",
    "BbMxD": "max_odds_draw",
    "BbMxA": "max_odds_away",
}

# Colonnes numériques à convertir
NUMERIC_COLUMNS = [
    "home_goals",
    "away_goals",
    "home_ht_goals",
    "away_ht_goals",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
    "home_corners",
    "away_corners",
    "home_fouls",
    "away_fouls",
    "home_yellow",
    "away_yellow",
    "home_red",
    "away_red",
    "odds_b365_home",
    "odds_b365_draw",
    "odds_b365_away",
    "odds_b365_close_home",
    "odds_b365_close_draw",
    "odds_b365_close_away",
    "odds_bw_home",
    "odds_bw_draw",
    "odds_bw_away",
    "odds_iw_home",
    "odds_iw_draw",
    "odds_iw_away",
    "odds_pinnacle_home",
    "odds_pinnacle_draw",
    "odds_pinnacle_away",
    "max_odds_home",
    "max_odds_draw",
    "max_odds_away",
]

# Colonnes entières (buts, cartons, etc.)
INTEGER_COLUMNS = [
    "home_goals",
    "away_goals",
    "home_ht_goals",
    "away_ht_goals",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
    "home_corners",
    "away_corners",
    "home_fouls",
    "away_fouls",
    "home_yellow",
    "away_yellow",
    "home_red",
    "away_red",
]


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
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Convertir les colonnes entières (buts, cartons)
    for col in INTEGER_COLUMNS:
        if col in df.columns:
            df[col] = df[col].round().astype("Int64")

    # Supprimer les lignes sans équipes (souvent des en-têtes dupliqués)
    if "home_team" in df.columns and "away_team" in df.columns:
        df = df.dropna(subset=["home_team", "away_team"])

    logger.info(f"Parsed {file_path.name}: {len(df)} matchs, {len(df.columns)} colonnes")
    return df


def parse_all_files(data_dir: Path) -> pd.DataFrame:
    """Parser tous les fichiers CSV d'un répertoire."""
    all_dfs: list[pd.DataFrame] = []
    for csv_file in sorted(data_dir.rglob("*.csv")):
        df = parse_csv(csv_file)
        df["_source_file"] = csv_file.name
        all_dfs.append(df)

    if not all_dfs:
        logger.warning(f"Aucun fichier CSV trouvé dans {data_dir}")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    logger.info(f"Total combiné : {len(combined)} matchs")
    return combined
