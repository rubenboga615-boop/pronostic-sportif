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
    # Arbitre. Sans effet sur les marchés de buts de la Phase 1, mais c'est la
    # variable centrale des marchés de cartons de la Phase 2 : les écarts entre
    # arbitres y sont bien plus marqués qu'entre équipes. Elle est gratuite,
    # présente dans le CSV, et irrécupérable a posteriori si on ne l'importe
    # pas maintenant.
    "Referee": "referee",
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
    # Cotes Pinnacle (ouverture)
    "PSH": "odds_pinnacle_home",
    "PSD": "odds_pinnacle_draw",
    "PSA": "odds_pinnacle_away",
    # Cotes Pinnacle (clôture)
    "PSCH": "odds_pinnacle_close_home",
    "PSCD": "odds_pinnacle_close_draw",
    "PSCA": "odds_pinnacle_close_away",
    # Meilleure cote et cote moyenne du marché (anciennement BbMx / BbAv)
    "MaxH": "max_odds_home",
    "MaxD": "max_odds_draw",
    "MaxA": "max_odds_away",
    "AvgH": "avg_odds_home",
    "AvgD": "avg_odds_draw",
    "AvgA": "avg_odds_away",
    # Over/Under 2,5 buts — marché de Phase 1, longtemps ignoré à l'import
    # alors que la source le fournit, ouverture et clôture.
    "B365>2.5": "odds_b365_over_25",
    "B365<2.5": "odds_b365_under_25",
    "B365C>2.5": "odds_b365_close_over_25",
    "B365C<2.5": "odds_b365_close_under_25",
    "P>2.5": "odds_pinnacle_over_25",
    "P<2.5": "odds_pinnacle_under_25",
    "PC>2.5": "odds_pinnacle_close_over_25",
    "PC<2.5": "odds_pinnacle_close_under_25",
    "Max>2.5": "max_odds_over_25",
    "Max<2.5": "max_odds_under_25",
    "Avg>2.5": "avg_odds_over_25",
    "Avg<2.5": "avg_odds_under_25",
}

# Colonnes sans lesquelles une ligne n'est pas un match exploitable.
COLONNES_REQUISES: tuple[str, ...] = (
    "Date",
    "HomeTeam",
    "AwayTeam",
    "FTHG",
    "FTAG",
)

# Colonnes attendues mais dont l'absence est tolérée : elles varient selon la
# saison et le championnat. Leur disparition est signalée, jamais silencieuse —
# c'est ainsi qu'Interwetten (IWH/IWD/IWA) a cessé d'être publié entre 2023/24
# et 2024/25 sans que rien ne l'indique.
COLONNES_TOLEREES: frozenset[str] = frozenset(RESULT_COLUMNS) - frozenset(COLONNES_REQUISES)

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


def inspecter_colonnes(colonnes_presentes) -> dict[str, list[str]]:
    """Comparer les colonnes d'un fichier à celles que le parseur sait lire.

    Le format de Football-Data.co.uk change au fil des saisons : des
    bookmakers apparaissent, d'autres disparaissent, des colonnes sont
    renommées. Sans contrôle, une colonne qui disparaît est simplement ignorée
    et la variable qu'elle alimentait devient silencieusement vide.

    Returns:
        ``{"manquantes_requises": [...], "manquantes_tolerees": [...]}``, listes
        triées pour un rapport reproductible.
    """
    presentes = {str(c).strip() for c in colonnes_presentes}
    return {
        "manquantes_requises": sorted(set(COLONNES_REQUISES) - presentes),
        "manquantes_tolerees": sorted(COLONNES_TOLEREES - presentes),
    }


def parse_csv(file_path: Path) -> pd.DataFrame:
    """Parser un fichier CSV Football-Data.co.uk.

    Le rapport d'inspection des colonnes est attaché au tableau retourné, sous
    ``df.attrs["colonnes"]``, pour que l'import le remonte dans son rapport de
    qualité.
    """
    try:
        df = pd.read_csv(file_path, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding="latin-1")

    inspection = inspecter_colonnes(df.columns)
    if inspection["manquantes_requises"]:
        logger.error(
            f"{file_path.name} : colonnes requises absentes {inspection['manquantes_requises']}"
        )
    if inspection["manquantes_tolerees"]:
        logger.warning(
            f"{file_path.name} : {len(inspection['manquantes_tolerees'])} colonnes "
            f"attendues absentes {inspection['manquantes_tolerees']}"
        )

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
    df.attrs["colonnes"] = inspection
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
