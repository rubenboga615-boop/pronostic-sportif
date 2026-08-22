"""Téléchargeur de données depuis Football-Data.co.uk."""

from pathlib import Path

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

BASE_URL = "https://www.football-data.co.uk"

# Codes des championnats
LEAGUES = {
    "E0": "Premier League",
    "SP1": "La Liga",
    "I1": "Serie A",
    "D1": "Bundesliga",
    "F1": "Ligue 1",
}

# Saisons disponibles (à ajuster selon les données)
SEASONS = [
    "2324", "2223", "2122", "2021", "1920", "1819", "1718", "1617", "1516"
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def download_league_season(league_code: str, season: str) -> Path | None:
    """Télécharger les données d'un championnat et d'une saison."""
    url = f"{BASE_URL}/mmz4281/{season}/{league_code}.csv"
    output_dir = settings.raw_dir / "football_data" / league_code
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{league_code}_{season}.csv"

    if output_file.exists():
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


async def download_all() -> list[Path]:
    """Télécharger toutes les données disponibles."""
    downloaded = []
    for league_code in LEAGUES:
        for season in SEASONS:
            result = await download_league_season(league_code, season)
            if result:
                downloaded.append(result)
    logger.info(f"Total téléchargé : {len(downloaded)} fichiers")
    return downloaded
