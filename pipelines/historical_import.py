"""Pipeline d'import des données historiques.

Étapes :
1. Télécharger les CSV des cinq championnats
2. Parser et normaliser les colonnes
3. Normaliser les noms d'équipes
4. Valider les scores et dates
5. Charger en base (upsert teams, matches, stats, odds)
6. Déduplication
7. Rapport de qualité
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy import null

from app.config import settings
from app.database import SessionLocal, engine
from app.models import (
    Base,
    Competition,
    Match,
    OddsSnapshot,
    Season,
    SourceHealth,
    Team,
    TeamMatchStats,
)
from collectors.football_data.league_config import LEAGUE_CONFIG
from collectors.football_data.parser import parse_csv
from collectors.football_data.team_normalizer import normalize_team_name

# ──────────────────────────────────────────────
# Bookmaker odds columns mapping
# ──────────────────────────────────────────────
# Séries de cotes lues dans les CSV, par bookmaker et par marché.
#
# La convention de nommage « B365_close » pour la clôture est celle des données
# déjà en base ; `is_closing` reste le discriminant fiable, et c'est lui
# qu'utilisent les features.
#
# Le marché over_under est ajouté ici : ses colonnes existaient dans les
# fichiers depuis toujours mais n'étaient pas lues, ce qui rendait impossible
# le calcul d'un edge sur l'un des marchés de la Phase 1.
SERIES_DE_COTES: tuple[dict[str, object], ...] = (
    {
        "bookmaker": "B365",
        "market": "1N2",
        "is_closing": False,
        "selections": {
            "home": "odds_b365_home",
            "draw": "odds_b365_draw",
            "away": "odds_b365_away",
        },
    },
    {
        "bookmaker": "B365_close",
        "market": "1N2",
        "is_closing": True,
        "selections": {
            "home": "odds_b365_close_home",
            "draw": "odds_b365_close_draw",
            "away": "odds_b365_close_away",
        },
    },
    {
        "bookmaker": "BW",
        "market": "1N2",
        "is_closing": False,
        "selections": {
            "home": "odds_bw_home",
            "draw": "odds_bw_draw",
            "away": "odds_bw_away",
        },
    },
    {
        "bookmaker": "IW",
        "market": "1N2",
        "is_closing": False,
        "selections": {
            "home": "odds_iw_home",
            "draw": "odds_iw_draw",
            "away": "odds_iw_away",
        },
    },
    {
        "bookmaker": "PS",
        "market": "1N2",
        "is_closing": False,
        "selections": {
            "home": "odds_pinnacle_home",
            "draw": "odds_pinnacle_draw",
            "away": "odds_pinnacle_away",
        },
    },
    {
        "bookmaker": "PS_close",
        "market": "1N2",
        "is_closing": True,
        "selections": {
            "home": "odds_pinnacle_close_home",
            "draw": "odds_pinnacle_close_draw",
            "away": "odds_pinnacle_close_away",
        },
    },
    {
        "bookmaker": "B365",
        "market": "over_under",
        "is_closing": False,
        "selections": {
            "over_2.5": "odds_b365_over_25",
            "under_2.5": "odds_b365_under_25",
        },
    },
    {
        "bookmaker": "B365_close",
        "market": "over_under",
        "is_closing": True,
        "selections": {
            "over_2.5": "odds_b365_close_over_25",
            "under_2.5": "odds_b365_close_under_25",
        },
    },
    {
        "bookmaker": "PS",
        "market": "over_under",
        "is_closing": False,
        "selections": {
            "over_2.5": "odds_pinnacle_over_25",
            "under_2.5": "odds_pinnacle_under_25",
        },
    },
    {
        "bookmaker": "PS_close",
        "market": "over_under",
        "is_closing": True,
        "selections": {
            "over_2.5": "odds_pinnacle_close_over_25",
            "under_2.5": "odds_pinnacle_close_under_25",
        },
    },
)


# ──────────────────────────────────────────────
# Stats columns mapping
# ──────────────────────────────────────────────
STATS_COLUMNS_HOME = {
    "home_shots": "shots",
    "home_shots_on_target": "shots_on_target",
    "home_corners": "corners",
    "home_fouls": "fouls",
    "home_yellow": "yellow_cards",
    "home_red": "red_cards",
}

STATS_COLUMNS_AWAY = {
    "away_shots": "shots",
    "away_shots_on_target": "shots_on_target",
    "away_corners": "corners",
    "away_fouls": "fouls",
    "away_yellow": "yellow_cards",
    "away_red": "red_cards",
}


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────


def _validate_goals(row: pd.Series) -> list[str]:
    """Valider la cohérence des buts, retourner les warnings."""
    warnings: list[str] = []
    hg = row.get("home_goals")
    ag = row.get("away_goals")
    hthg = row.get("home_ht_goals")
    htag = row.get("away_ht_goals")

    # Buts négatifs
    if pd.notna(hg) and hg < 0:
        warnings.append(f"Buts domicile négatifs: {hg}")
    if pd.notna(ag) and ag < 0:
        warnings.append(f"Buts extérieur négatifs: {ag}")

    # HT goals > FT goals
    if pd.notna(hthg) and pd.notna(hg) and hthg > hg:
        warnings.append(f"HT home {hthg} > FT home {hg}")
    if pd.notna(htag) and pd.notna(ag) and htag > ag:
        warnings.append(f"HT away {htag} > FT away {ag}")

    return warnings


def _validate_date(row: pd.Series) -> list[str]:
    """Valider la date du match."""
    warnings: list[str] = []
    d = row.get("match_date")
    if pd.isna(d):
        warnings.append("Date manquante")
        return warnings
    if d.year < 2000:
        warnings.append(f"Année suspecte: {d.year}")
    return warnings


# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────


def _upsert_competition(session, code: str, config: dict) -> Competition:
    """Upsert une compétition."""
    existing = session.query(Competition).filter_by(provider_code=code).first()
    if existing:
        return existing
    comp = Competition(
        provider_code=code,
        name=config["name"],
        country=config["country"],
        active=True,
    )
    session.add(comp)
    session.flush()
    return comp


def _upsert_season(session, competition_id: int, season_code: str) -> Season:
    """Upsert une saison."""
    existing = (
        session.query(Season)
        .filter_by(competition_id=competition_id, season_name=season_code)
        .first()
    )
    if existing:
        return existing
    # Déterminer le statut
    current_year = datetime.now().year
    season_start = 2000 + int(season_code[:2])
    status = "in_progress" if season_start == current_year else "complete"
    season = Season(
        competition_id=competition_id,
        season_name=season_code,
        start_date=datetime(season_start, 8, 1, tzinfo=UTC),
        end_date=datetime(season_start + 1, 5, 31, tzinfo=UTC),
        status=status,
    )
    session.add(season)
    session.flush()
    return season


def _upsert_team(session, canonical_name: str, country: str) -> tuple[Team, bool]:
    """Upsert une équipe. Retourne (équipe, créée_ou_non)."""
    existing = (
        session.query(Team)
        .filter_by(canonical_name=canonical_name, provider="football_data")
        .first()
    )
    if existing:
        return existing, False
    team = Team(
        canonical_name=canonical_name,
        country=country,
        provider="football_data",
        provider_team_id=canonical_name.lower().replace(" ", "-"),
        active=True,
    )
    session.add(team)
    session.flush()
    return team, True


def _find_existing_match(session, match_date, home_team_id: int, away_team_id: int) -> Match | None:
    """Chercher un match existant par date + équipes."""
    if pd.isna(match_date):
        return None
    return (
        session.query(Match)
        .filter(
            Match.provider == "football_data",
            Match.match_date == match_date,
            Match.home_team_id == home_team_id,
            Match.away_team_id == away_team_id,
        )
        .first()
    )


def _insert_team_match_stats(
    session,
    match_id: int,
    team_id: int,
    row: pd.Series,
    is_home: bool,
    source: str,
) -> int:
    """Insérer les stats d'équipe pour un match. Retourne 1 si inséré, 0 sinon."""
    cols_map = STATS_COLUMNS_HOME if is_home else STATS_COLUMNS_AWAY
    stats: dict = {}
    for src_col, db_col in cols_map.items():
        val = row.get(src_col)
        if pd.notna(val):
            stats[db_col] = int(val)
    if not stats:
        return 0
    tms = TeamMatchStats(
        match_id=match_id,
        team_id=team_id,
        shots=stats.get("shots"),
        shots_on_target=stats.get("shots_on_target"),
        corners=stats.get("corners"),
        fouls=stats.get("fouls"),
        yellow_cards=stats.get("yellow_cards"),
        red_cards=stats.get("red_cards"),
        source=source,
        quality_status="complete" if len(stats) >= 3 else "partial",
    )
    session.add(tms)
    return 1


def _insert_odds(
    session,
    match_id: int,
    row: pd.Series,
    match_date,
) -> int:
    """Insérer les cotes d'un match. Retourne le nombre de relevés insérés.

    Une série n'est insérée que complète : sans les trois cotes d'un 1N2 ou les
    deux d'un Over/Under, la marge du bookmaker n'est pas calculable et la
    série partielle n'aurait pas de sens.
    """
    inserted = 0
    for serie in SERIES_DE_COTES:
        is_closing = bool(serie["is_closing"])
        valeurs: dict[str, float] = {}
        complete = True
        for selection, colonne in serie["selections"].items():
            val = row.get(colonne)
            if pd.notna(val) and val > 0:
                valeurs[selection] = float(val)
            else:
                complete = False
        if not complete:
            continue

        # Football-Data.co.uk n'horodate pas ses relevés. Seule la cote de
        # clôture a un instant connu — le coup d'envoi. Pour l'ouverture,
        # l'instant reste NULL : le prétendre égal à la date du match ferait
        # passer une cote non datée pour une cote pré-match exploitable.
        #
        # `null()` et non `None` : la colonne porte un `default=maintenant_utc` que
        # SQLAlchemy appliquerait sinon, redatant silencieusement le relevé au
        # moment de l'import.
        captured_at = (
            (match_date if pd.notna(match_date) else datetime.now(UTC)) if is_closing else null()
        )
        for selection, cote in valeurs.items():
            session.add(
                OddsSnapshot(
                    match_id=match_id,
                    bookmaker=serie["bookmaker"],
                    market=serie["market"],
                    selection=selection,
                    odds=cote,
                    captured_at=captured_at,
                    is_closing=is_closing,
                    source="football_data",
                )
            )
            inserted += 1
    return inserted


# ──────────────────────────────────────────────
# Quality report
# ──────────────────────────────────────────────


def _write_quality_report(report: dict, output_dir: Path) -> Path:
    """Écrire le rapport de qualité en JSON, horodaté et archivé.

    Un nom fixe écrasait le rapport précédent à chaque exécution : la trace de
    l'import qui avait réellement chargé les données était perdue, et le
    « journal des sources » attendu au livrable de première année restait
    impossible à constituer. Chaque exécution laisse désormais son propre
    fichier ; ``import_report.json`` continue de pointer sur la dernière.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    horodatage = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    archive = output_dir / f"import_report_{horodatage}.json"
    contenu = json.dumps(report, indent=2, default=str, ensure_ascii=False)
    archive.write_text(contenu, encoding="utf-8")

    dernier = output_dir / "import_report.json"
    dernier.write_text(contenu, encoding="utf-8")

    logger.info(f"Rapport de qualité écrit : {archive}")
    return archive


# ──────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────


def run_historical_import(
    league_codes: list[str] | None = None,
    seasons: list[str] | None = None,
    *,
    skip_download: bool = False,
    force_download: bool = False,
) -> dict:
    """Exécuter le pipeline d'import historique complet.

    Args:
        league_codes: Ligues à importer (None = toutes)
        seasons: Saisons à importer (None = toutes disponibles)
        skip_download: Si True, ne pas télécharger (utiliser les fichiers existants)
        force_download: Si True, re-télécharger les fichiers existants

    Returns:
        Rapport de qualité

    """
    from collectors.football_data.downloader import download_all

    logger.info("=== Début de l'import historique ===")

    # Initialiser les tables
    Base.metadata.create_all(bind=engine)

    # Rapport
    report: dict = {
        "started_at": datetime.now(UTC).isoformat(),
        # Fichiers
        "files_processed": 0,
        "files_skipped": 0,
        # Lignes (invariant : rows_read == matches_inserted + matches_duplicates
        #          + matches_skipped_invalid + rows_errored)
        "rows_read": 0,
        "matches_inserted": 0,
        "matches_duplicates": 0,
        "matches_skipped_invalid": 0,
        "rows_errored": 0,
        # Volumes réellement insérés
        "teams_created": 0,
        "odds_inserted": 0,
        "stats_inserted": 0,
        # Qualité (advisory, non bloquant)
        "validation_warnings": 0,
        "colonnes_absentes": {},
        "warnings": [],
        "errors": [],
    }

    # Étape 1 : Téléchargement
    downloaded_files: list[Path] = []
    if not skip_download:
        logger.info("Étape 1 : Téléchargement des CSV...")
        import asyncio

        try:
            downloaded_files = asyncio.get_event_loop().run_until_complete(
                download_all(league_codes, seasons, force=force_download)
            )
        except RuntimeError:
            downloaded_files = asyncio.run(
                download_all(league_codes, seasons, force=force_download)
            )
    else:
        logger.info("Étape 1 : Skip téléchargement, utilisation des fichiers existants")
        raw_dir = settings.raw_dir / "football_data"
        if raw_dir.exists():
            downloaded_files = sorted(raw_dir.rglob("*.csv"))
        logger.info(f"  {len(downloaded_files)} fichiers trouvés sur disque")

    if not downloaded_files:
        logger.warning("Aucun fichier à traiter")
        report["errors"].append("Aucun fichier téléchargé ou trouvé")
        return report

    # Étape 2-6 : Parse, normalisation, validation, insertion
    logger.info("Étape 2-6 : Parse, normalisation, validation, insertion...")

    session = SessionLocal()
    try:
        for csv_file in downloaded_files:
            file_report = _process_file(session, csv_file, report)
            report["files_processed"] += file_report["processed"]
            report["files_skipped"] += file_report["skipped"]
            report["rows_read"] += file_report["total"]
            report["matches_inserted"] += file_report["inserted"]
            report["matches_duplicates"] += file_report["duplicates"]
            report["matches_skipped_invalid"] += file_report["invalid"]
            report["rows_errored"] += file_report["errored"]
            report["teams_created"] += file_report["teams_created"]
            report["odds_inserted"] += file_report["odds"]
            report["stats_inserted"] += file_report["stats"]
            report["validation_warnings"] += file_report["validation_warnings"]

        session.commit()

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur fatale pendant l'import : {e}")
        report["errors"].append(str(e))
        raise
    finally:
        session.close()

    # Étape 7 : Rapport de qualité
    report["finished_at"] = datetime.now(UTC).isoformat()
    _write_quality_report(report, settings.cleaned_dir)

    # Source health
    _update_source_health(report)

    logger.info("=== Fin de l'import historique ===")
    logger.info(
        f"Fichiers: {report['files_processed']} (ignorés: {report['files_skipped']}) | "
        f"Lignes: {report['rows_read']} | "
        f"Insérés: {report['matches_inserted']} | "
        f"Doublons: {report['matches_duplicates']} | "
        f"Erreurs: {report['rows_errored']}"
    )
    return report


def _process_file(session, csv_file: Path, report: dict) -> dict:
    """Traiter un fichier CSV individuel. Retourne un sous-rapport."""
    file_report = {
        "processed": 0,
        "skipped": 0,
        "total": 0,
        "inserted": 0,
        "duplicates": 0,
        "invalid": 0,
        "errored": 0,
        "teams_created": 0,
        "odds": 0,
        "stats": 0,
        "validation_warnings": 0,
    }

    # Extraire league et season du nom de fichier
    # Format attendu : {LEAGUE}_{SEASON}.csv
    stem = csv_file.stem  # ex: E0_2324
    parts = stem.split("_")
    if len(parts) < 2:
        report["warnings"].append(f"Nom de fichier inattendu: {csv_file.name}")
        file_report["skipped"] = 1
        return file_report

    league_code = parts[0]
    season_code = parts[1]

    if league_code not in LEAGUE_CONFIG:
        report["warnings"].append(
            f"Ligue inconnue dans le fichier: {league_code} ({csv_file.name})"
        )
        file_report["skipped"] = 1
        return file_report

    league_config = LEAGUE_CONFIG[league_code]
    country = league_config["country"]

    # Parse le CSV
    try:
        df = parse_csv(csv_file)
    except Exception as e:
        logger.error(f"Erreur parsing {csv_file.name}: {e}")
        report["errors"].append(f"Parse error {csv_file.name}: {e}")
        file_report["skipped"] = 1
        return file_report

    file_report["processed"] = 1

    # Changements de format de la source : une colonne attendue qui disparaît
    # ne doit jamais passer inaperçue.
    inspection = df.attrs.get("colonnes", {})
    for colonne in inspection.get("manquantes_requises", []):
        report["errors"].append(f"{csv_file.name} : colonne requise absente ({colonne})")
    if inspection.get("manquantes_tolerees"):
        report["colonnes_absentes"][csv_file.name] = inspection["manquantes_tolerees"]
        report["warnings"].append(
            f"{csv_file.name} : colonnes attendues absentes {inspection['manquantes_tolerees']}"
        )

    if df.empty:
        logger.warning(f"Fichier vide: {csv_file.name}")
        return file_report

    file_report["total"] = len(df)

    # Upsert competition et season
    competition = _upsert_competition(session, league_code, league_config)
    season = _upsert_season(session, competition.id, season_code)

    # Traiter chaque ligne
    for idx, row in df.iterrows():
        try:
            result = _process_match_row(session, row, competition, season, league_code, country)
            disposition = result["disposition"]
            if disposition == "inserted":
                file_report["inserted"] += 1
            elif disposition == "duplicate":
                file_report["duplicates"] += 1
            elif disposition == "invalid":
                file_report["invalid"] += 1
            file_report["teams_created"] += result["teams_created"]
            file_report["odds"] += result["odds"]
            file_report["stats"] += result["stats"]
            if result["validation_warnings"]:
                file_report["validation_warnings"] += len(result["validation_warnings"])
                for w in result["validation_warnings"]:
                    report["warnings"].append(f"{csv_file.name} ligne {idx}: {w}")
        except Exception as e:
            logger.warning(f"Erreur ligne {idx} dans {csv_file.name}: {e}")
            report["warnings"].append(f"Row {idx} in {csv_file.name}: {e}")
            file_report["errored"] += 1

    logger.info(
        f"  {csv_file.name}: {file_report['total']} matchs, "
        f"{file_report['inserted']} insérés, "
        f"{file_report['duplicates']} doublons"
    )

    return file_report


def _make_provider_match_id(
    league_code: str,
    season_name: str,
    match_date,
    home_canonical: str,
    away_canonical: str,
) -> str:
    """Construire un identifiant provider déterministe et stable.

    Utilise un condensat SHA-256 (déterministe, indépendant du processus) sur une
    clé canonique ``league_code | season_name | date_iso | home | away``. L'ordre
    domicile/extérieur est conservé : ``PSG|Lyon`` ne produit jamais le même
    identifiant que ``Lyon|PSG``. L'inclusion du code ligue et de la saison évite
    qu'un même match logique dans deux compétitions partage le même identifiant.
    """
    date_key = match_date.isoformat() if pd.notna(match_date) else "NaT"
    key = "|".join([league_code, season_name, date_key, home_canonical, away_canonical])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"fd_{league_code}_{season_name}_{digest}"


def _process_match_row(
    session,
    row: pd.Series,
    competition: Competition,
    season: Season,
    league_code: str,
    country: str,
) -> dict:
    """Traiter une ligne de match.

    Retourne un dictionnaire :
    - ``disposition`` : ``'inserted'`` | ``'duplicate'`` | ``'invalid'`` ;
    - ``teams_created``, ``odds``, ``stats`` : volumes réellement insérés ;
    - ``validation_warnings`` : avertissements de validation (advisory).
    """
    home_name = row.get("home_team")
    away_name = row.get("away_team")

    if pd.isna(home_name) or pd.isna(away_name):
        return {
            "disposition": "invalid",
            "teams_created": 0,
            "odds": 0,
            "stats": 0,
            "validation_warnings": [],
        }

    # Normaliser les noms
    home_canonical = normalize_team_name(str(home_name), league_code)
    away_canonical = normalize_team_name(str(away_name), league_code)

    # Valider les buts et la date (advisory : n'empêche pas l'insertion)
    validation_warnings = _validate_goals(row) + _validate_date(row)

    # Déterminer le statut du match
    hg = row.get("home_goals")
    ag = row.get("away_goals")
    match_status = "unknown" if (pd.isna(hg) or pd.isna(ag)) else "completed"

    # Upsert teams
    home_team, home_created = _upsert_team(session, home_canonical, country)
    away_team, away_created = _upsert_team(session, away_canonical, country)
    teams_created = int(home_created) + int(away_created)

    # Vérifier les doublons
    match_date = row.get("match_date")
    existing = _find_existing_match(session, match_date, home_team.id, away_team.id)
    if existing:
        return {
            "disposition": "duplicate",
            "teams_created": teams_created,
            "odds": 0,
            "stats": 0,
            "validation_warnings": validation_warnings,
        }

    # Insérer le match
    match = Match(
        provider="football_data",
        provider_match_id=_make_provider_match_id(
            league_code,
            season.season_name,
            match_date,
            home_canonical,
            away_canonical,
        ),
        competition_id=competition.id,
        season_id=season.id,
        match_date=match_date if pd.notna(match_date) else None,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        status=match_status,
        home_goals=int(hg) if pd.notna(hg) else None,
        away_goals=int(ag) if pd.notna(ag) else None,
        home_ht_goals=int(row["home_ht_goals"]) if pd.notna(row.get("home_ht_goals")) else None,
        away_ht_goals=int(row["away_ht_goals"]) if pd.notna(row.get("away_ht_goals")) else None,
        home_shots=int(row["home_shots"]) if pd.notna(row.get("home_shots")) else None,
        away_shots=int(row["away_shots"]) if pd.notna(row.get("away_shots")) else None,
        home_shots_on_target=int(row["home_shots_on_target"])
        if pd.notna(row.get("home_shots_on_target"))
        else None,
        away_shots_on_target=int(row["away_shots_on_target"])
        if pd.notna(row.get("away_shots_on_target"))
        else None,
    )
    session.add(match)
    session.flush()

    # Insérer les stats d'équipe
    stats_inserted = _insert_team_match_stats(
        session, match.id, home_team.id, row, is_home=True, source="football_data"
    )
    stats_inserted += _insert_team_match_stats(
        session, match.id, away_team.id, row, is_home=False, source="football_data"
    )

    # Insérer les cotes
    odds_inserted = _insert_odds(session, match.id, row, match_date)

    return {
        "disposition": "inserted",
        "teams_created": teams_created,
        "odds": odds_inserted,
        "stats": stats_inserted,
        "validation_warnings": validation_warnings,
    }


def _update_source_health(report: dict) -> None:
    """Mettre à jour la table source_health."""
    session = SessionLocal()
    try:
        existing = session.query(SourceHealth).filter_by(source="football_data").first()
        if existing:
            existing.last_success_at = datetime.now(UTC)
            existing.records_last_run = report["matches_inserted"]
            existing.status = "healthy" if not report["errors"] else "degraded"
        else:
            sh = SourceHealth(
                source="football_data",
                last_success_at=datetime.now(UTC),
                records_last_run=report["matches_inserted"],
                status="healthy" if not report["errors"] else "degraded",
            )
            session.add(sh)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    run_historical_import()
