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
    # Cotes BWin (ouverture et clôture). La clôture n'était pas lue : c'est le
    # nouveau contrôle `cotes_ignorees` qui l'a signalée à sa première
    # exécution. Un bookmaker complet de plus à la clôture, c'est un candidat
    # de plus au calcul de la marge minimale — là où le projet ne disposait
    # que de Bet365 et Pinnacle.
    "BWH": "odds_bw_home",
    "BWD": "odds_bw_draw",
    "BWA": "odds_bw_away",
    "BWCH": "odds_bw_close_home",
    "BWCD": "odds_bw_close_draw",
    "BWCA": "odds_bw_close_away",
    # Cotes Interwetten (ouverture et clôture). Interwetten a cessé d'être
    # publié entre 2023/24 et 2024/25 : son absence est attendue sur les
    # saisons récentes, et l'inspection la signale sans la traiter en anomalie.
    "IWH": "odds_iw_home",
    "IWD": "odds_iw_draw",
    "IWA": "odds_iw_away",
    "IWCH": "odds_iw_close_home",
    "IWCD": "odds_iw_close_draw",
    "IWCA": "odds_iw_close_away",
    # Cotes Pinnacle (ouverture)
    "PSH": "odds_pinnacle_home",
    "PSD": "odds_pinnacle_draw",
    "PSA": "odds_pinnacle_away",
    # Cotes Pinnacle (clôture)
    "PSCH": "odds_pinnacle_close_home",
    "PSCD": "odds_pinnacle_close_draw",
    "PSCA": "odds_pinnacle_close_away",
    # Agrégats de marché : meilleure cote disponible et cote moyenne.
    #
    # Football-Data les a renommés en 2019/20 — `BbMx` est devenu `Max`, `BbAv`
    # est devenu `Avg`. Les deux graphies désignent la même grandeur et pointent
    # donc vers la même cible : le reste du code ignore l'époque du fichier.
    # Elles ne coexistent jamais dans un même fichier.
    #
    # Ne lire que les noms modernes coûtait les cotes de trois saisons sur onze
    # — 20 034 matchs sur le corpus complet — sans qu'aucune alerte ne se
    # déclenche, puisque la colonne n'avait pas disparu : elle avait changé de
    # nom.
    "MaxH": "max_odds_home",
    "BbMxH": "max_odds_home",
    "MaxD": "max_odds_draw",
    "BbMxD": "max_odds_draw",
    "MaxA": "max_odds_away",
    "BbMxA": "max_odds_away",
    "AvgH": "avg_odds_home",
    "BbAvH": "avg_odds_home",
    "AvgD": "avg_odds_draw",
    "BbAvD": "avg_odds_draw",
    "AvgA": "avg_odds_away",
    "BbAvA": "avg_odds_away",
    # Agrégats à la clôture. Ils n'étaient lus par personne, alors que c'est
    # contre la clôture que le rendement est mesuré : chaque pari était donc
    # valorisé au meilleur de Bet365 et Pinnacle, et non au meilleur du marché.
    # Mesuré sur six saisons et cinq championnats, l'écart est de +3,57 % sur
    # le 1N2 et +1,87 % sur l'Over/Under — autant de rendement perdu.
    "MaxCH": "max_odds_close_home",
    "MaxCD": "max_odds_close_draw",
    "MaxCA": "max_odds_close_away",
    "AvgCH": "avg_odds_close_home",
    "AvgCD": "avg_odds_close_draw",
    "AvgCA": "avg_odds_close_away",
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
    "BbMx>2.5": "max_odds_over_25",
    "Max<2.5": "max_odds_under_25",
    "BbMx<2.5": "max_odds_under_25",
    "Avg>2.5": "avg_odds_over_25",
    "BbAv>2.5": "avg_odds_over_25",
    "Avg<2.5": "avg_odds_under_25",
    "BbAv<2.5": "avg_odds_under_25",
    "MaxC>2.5": "max_odds_close_over_25",
    "MaxC<2.5": "max_odds_close_under_25",
    "AvgC>2.5": "avg_odds_close_over_25",
    "AvgC<2.5": "avg_odds_close_under_25",
}


def familles_de_colonnes() -> dict[str, tuple[str, ...]]:
    """Cible -> graphies qui l'alimentent, toutes époques confondues.

    Obtenue en inversant :data:`RESULT_COLUMNS`. Deux graphies partageant une
    cible sont, par construction, deux noms de la même grandeur — c'est ce qui
    permet à :func:`inspecter_colonnes` de ne pas signaler `BbMxH` comme
    manquante dans un fichier moderne, ni `MaxH` dans un fichier ancien.
    """
    familles: dict[str, list[str]] = {}
    for source, cible in RESULT_COLUMNS.items():
        familles.setdefault(cible, []).append(source)
    return {cible: tuple(sources) for cible, sources in familles.items()}


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

_CIBLES_REQUISES: frozenset[str] = frozenset(RESULT_COLUMNS[source] for source in COLONNES_REQUISES)

# Colonnes de cotes que le projet choisit de ne pas lire, et pourquoi. Les
# nommer explicitement est la contrepartie de :func:`cotes_ignorees` : sans
# cette liste, elle crierait à chaque fichier et on cesserait de l'écouter.
COTES_ECARTEES_MOTIFS: dict[str, str] = {
    "AH": "handicap asiatique — marché de Phase 2, désactivé",
    "BF": "Betfair Exchange — cotes de bourse, commission non modélisée",
}

# Bookmakers individuels que `Max` et `Avg` résument déjà. Les lire un par un
# n'améliorerait pas le meilleur prix — `Max` est par définition le maximum du
# marché — et ce sont tous des opérateurs grand public, à marge large : aucun
# ne remporterait le concours de marge minimale que Pinnacle, déjà lu, gagne
# presque toujours.
#
# Les importer coûterait environ deux millions de lignes de cotes sur le corpus
# complet, pour une information nulle. Ils sont donc écartés **explicitement** :
# c'est une décision, pas un oubli, et `cotes_ignorees` le vérifie.
BOOKMAKERS_RESUMES: frozenset[str] = frozenset(
    {
        "VC",  # VC Bet
        "WH",  # William Hill
        "LB",  # Ladbrokes
        "SJ",  # Stan James
        "SB",  # Sportingbet
        "GB",  # Gamebookers
        "BS",  # Blue Square
        "SY",  # Stanleybet
        "SO",  # Sporting Odds
        "1XB",  # 1xBet
        "BMGM",  # BetMGM
        "BV",  # BetVictor
        "CL",  # Coral
        "PP",  # Paddy Power
        "SKB",  # Skybet
    }
)

# Colonnes numériques à convertir.
#
# Dérivée de RESULT_COLUMNS plutôt que tenue à la main : la liste parallèle
# oubliait systématiquement les colonnes nouvellement ajoutées — aucune cote
# Over/Under n'y figurait, ni les agrégats de clôture. Une colonne restée en
# type `object` compare mal, et `val > 0` lève alors sur une chaîne.
NUMERIC_COLUMNS: list[str] = sorted(
    {
        cible
        for cible in RESULT_COLUMNS.values()
        if cible.startswith(("odds_", "max_odds_", "avg_odds_"))
    }
    | {
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
        "home_goals",
        "away_goals",
        "home_ht_goals",
        "away_ht_goals",
    }
)

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

    Le format de Football-Data.co.uk change au fil des saisons : des bookmakers
    apparaissent, d'autres disparaissent, des colonnes sont renommées. Sans
    contrôle, une colonne qui disparaît est simplement ignorée et la variable
    qu'elle alimentait devient silencieusement vide.

    Deux raisonnements distincts, et c'est leur confusion qui avait laissé
    passer le défaut des colonnes Betbrain :

    - une **grandeur** manque quand *aucune* de ses graphies n'est présente.
      `MaxH` absente n'est pas une perte si `BbMxH` est là : c'est le même
      chiffre sous l'autre nom. Signaler l'une ou l'autre comme manquante
      noierait les vraies disparitions sous le bruit des changements d'époque ;
    - une **colonne de cotes présente dans le fichier et lue par personne** est
      une perte sèche, et c'est le cas que rien ne surveillait. Elle est
      désormais remontée sous ``cotes_ignorees``.

    Returns:
        ``{"manquantes_requises", "manquantes_tolerees", "cotes_ignorees"}``,
        listes triées pour un rapport reproductible.
    """
    presentes = {str(c).strip() for c in colonnes_presentes}
    familles = familles_de_colonnes()

    # Une grandeur ne manque que si aucune de ses graphies n'est là.
    manquantes = sorted(
        graphies[0]
        for cible, graphies in familles.items()
        if cible not in _CIBLES_REQUISES and not (set(graphies) & presentes)
    )

    return {
        "manquantes_requises": sorted(set(COLONNES_REQUISES) - presentes),
        "manquantes_tolerees": manquantes,
        "cotes_ignorees": sorted(cotes_ignorees(presentes)),
    }


def cotes_ignorees(colonnes_presentes) -> set[str]:
    """Colonnes de cotes présentes dans le fichier et lues par personne.

    C'est le contrôle qui manquait. Les colonnes Betbrain étaient remplies à
    100 % sur trois saisons, et aucun signal ne disait qu'elles partaient à la
    poubelle : l'inspection ne regardait que ce qui manquait, jamais ce qui
    était offert et laissé de côté.

    Une colonne est tenue pour une cote si son nom porte une ligne de but
    (``>2.5``) ou se termine par ``H``/``D``/``A`` après un préfixe de
    bookmaker — heuristique volontairement large : mieux vaut un faux positif
    à écarter explicitement qu'une cote perdue en silence.
    """
    presentes = {str(c).strip() for c in colonnes_presentes}
    inconnues = presentes - set(RESULT_COLUMNS)

    def ecartee(colonne: str) -> bool:
        if any(motif in colonne for motif in COTES_ECARTEES_MOTIFS):
            return True
        # Préfixe de bookmaker résumé par Max/Avg, éventuellement suivi du `C`
        # de clôture : VCH, WHD, VCCA…
        for prefixe in BOOKMAKERS_RESUMES:
            if colonne.startswith(prefixe):
                return True
        return False

    def ressemble_a_une_cote(colonne: str) -> bool:
        return ">" in colonne or "<" in colonne or colonne[-1:] in ("H", "D", "A")

    return {c for c in inconnues if ressemble_a_une_cote(c) and not ecartee(c)}


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
