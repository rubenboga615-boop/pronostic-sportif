"""Téléchargeur de données depuis Football-Data.co.uk."""

from pathlib import Path

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

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


class DownloadFailedError(Exception):
    """Échec définitif du téléchargement d'un fichier."""


class TransientDownloadError(Exception):
    """Échec susceptible de réussir à la tentative suivante.

    Coupure réseau, délai dépassé, ou erreur 5xx du serveur. Une réponse 404,
    à l'inverse, est définitive : la saison n'est pas publiée, réessayer ne la
    fera pas apparaître.
    """


@retry(
    retry=retry_if_exception_type(TransientDownloadError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True,
)
async def _telecharger(url: str) -> bytes:
    """Récupérer le contenu d'un fichier, avec réessais sur erreur transitoire.

    Cette fonction laisse remonter ses exceptions : c'est ce qui permet à
    ``tenacity`` de réessayer. Enfermer la requête dans un ``try/except`` qui
    retourne ``None`` — comme le faisait la version précédente — rendait le
    décorateur inopérant, puisqu'aucune exception ne lui parvenait jamais.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
    except (httpx.TimeoutException, httpx.TransportError) as erreur:
        raise TransientDownloadError(f"{type(erreur).__name__}: {erreur}") from erreur

    if response.status_code >= 500:
        raise TransientDownloadError(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        raise DownloadFailedError(f"HTTP {response.status_code}")

    if not response.content:
        raise DownloadFailedError("réponse vide")

    return response.content


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
        Chemin du fichier téléchargé, ou None après échec définitif.

    """
    url = f"{BASE_URL}/mmz4281/{season}/{league_code}.csv"
    output_dir = settings.raw_dir / "football_data" / league_code
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{league_code}_{season}.csv"

    if output_file.exists() and not force:
        logger.info(f"Fichier déjà existant : {output_file}")
        return output_file

    try:
        contenu = await _telecharger(url)
    except DownloadFailedError as erreur:
        logger.error(f"Téléchargement refusé pour {url} : {erreur}")
        return None
    except TransientDownloadError as erreur:
        logger.error(f"Téléchargement abandonné après 3 tentatives pour {url} : {erreur}")
        return None
    except Exception as erreur:  # pragma: no cover — filet de sécurité
        logger.error(f"Erreur inattendue sur {url} : {erreur}")
        return None

    # Écriture atomique : un fichier partiel serait ensuite parsé comme s'il
    # était complet, et l'import y verrait simplement moins de matchs.
    temporaire = output_file.with_suffix(".csv.partiel")
    temporaire.write_bytes(contenu)
    temporaire.replace(output_file)

    logger.info(f"Téléchargé : {url} -> {output_file} ({len(contenu)} octets)")
    return output_file


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
    echecs: list[str] = []
    for league_code in league_codes:
        if league_code not in LEAGUE_CONFIG:
            logger.warning(f"Ligue inconnue : {league_code}")
            continue
        for season in seasons:
            result = await download_league_season(league_code, season, force=force)
            if result:
                downloaded.append(result)
            else:
                echecs.append(f"{league_code}_{season}")

    logger.info(f"Total téléchargé : {len(downloaded)} fichiers")
    if echecs:
        logger.warning(f"{len(echecs)} fichiers indisponibles : {echecs}")
    return downloaded
