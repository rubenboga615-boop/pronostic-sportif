"""Téléchargeur de données depuis Football-Data.co.uk."""

from pathlib import Path

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

BASE_URL = "https://www.football-data.co.uk"

# Saisons disponibles
SEASONS = [
    "2526",
    "2425",
    "2324",
    "2223",
    "2122",
    "2021",
    "1920",
    "1819",
    "1718",
    "1617",
    "1516",
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def download_league_season(
    league_code: str,
    season: str,
    *,
    force: bool = False,
) -> Path | None:
    """Télécharger les données d'un championnat et d'une saison.

    Args:
        league_code: Code du championnat (E0, SP1, I1, D1, F1)
        season: Code de la saison (ex: 2324)
        force: Si True, re-télécharger même si le fichier existe

    Returns:
        Chemin du fichier téléchargé ou None en cas d'erreur

    """
    url = f"{BASE_URL}/mmz4281/{season}/{league_code}.csv"
    output_dir = settings.raw_dir / "football_data" / league_code
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{league_code}_{season}.csv"

    if output_file.exists() and not force:
        logger.info(f"Fichier déjà existant : {output_file}")
        return output_file

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            output_file.write_bytes(response.content)
            logger.info(f"Downloaded : {url} -> {output_file}")
            return output_file
        except httpx.HTTPStatusError as e:
            logger.error(f"Erreur HTTP {e.response.status_code} pour {url}")
            return None
        except Exception as e:
            logger.error(f"Erreur téléchargement {url}: {e}")
            return None


async def download_all(
    league_codes: list[str] | None = None,
    seasons: list[str] | None = None,
    *,
    force: bool = False,
) -> list[Path]:
    """Télécharger toutes les données disponibles.

    Args:
        league_codes: Liste des codes de ligues (None = toutes)
        seasons: Liste des saisons (None = toutes)
        force: Si True, re-télécharger les fichiers existants

    """
    from collectors.football_data.league_config import LEAGUE_CONFIG

    if league_codes is None:
        league_codes = list(LEAGUE_CONFIG.keys())
    if seasons is None:
        seasons = SEASONS

    downloaded: list[Path] = []
    for league_code in league_codes:
        if league_code not in LEAGUE_CONFIG:
            logger.warning(f"Ligue inconnue : {league_code}")
            continue
        for season in seasons:
            result = await download_league_season(league_code, season, force=force)
            if result:
                downloaded.append(result)
    logger.info(f"Total téléchargé : {len(downloaded)} fichiers")
    return downloaded
