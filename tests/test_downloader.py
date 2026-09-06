"""Tests du téléchargeur Football-Data.co.uk.

`PROJECT_SPEC.md` demande au pipeline de « réessayer les requêtes échouées ».
Le décorateur `@retry` était bien présent, mais la fonction qu'il décorait
attrapait elle-même toutes ses exceptions et retournait `None` : aucune
exception ne parvenait jamais à tenacity, et aucun réessai n'avait lieu.

Ces tests vérifient le comportement, pas la présence du décorateur.
"""

import httpx
import pytest

from collectors.football_data import downloader
from collectors.football_data.downloader import (
    DownloadFailedError,
    TransientDownloadError,
    _telecharger,
    download_league_season,
)

CONTENU = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,12/08/2023,Arsenal,Chelsea,2,1,H\n"


class _ClientFactice:
    """Client HTTP de substitution, scriptable réponse par réponse."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = 0

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        self.appels += 1
        reponse = self.reponses.pop(0) if self.reponses else self.reponses
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


def _reponse(code: int, contenu: bytes = CONTENU) -> httpx.Response:
    return httpx.Response(status_code=code, content=contenu)


@pytest.fixture(autouse=True)
def sans_attente(monkeypatch):
    """Neutraliser l'attente exponentielle : les tests ne doivent pas dormir."""
    monkeypatch.setattr(_telecharger.retry, "wait", lambda *a, **k: 0)


class TestReessais:
    async def test_une_erreur_reseau_est_reessayee(self, monkeypatch):
        client = _ClientFactice(
            [httpx.ConnectError("réseau coupé"), httpx.ConnectError("encore"), _reponse(200)]
        )
        monkeypatch.setattr(downloader.httpx, "AsyncClient", client)

        contenu = await _telecharger("https://exemple/test.csv")

        assert contenu == CONTENU
        assert client.appels == 3

    async def test_une_erreur_serveur_est_reessayee(self, monkeypatch):
        client = _ClientFactice([_reponse(503, b""), _reponse(200)])
        monkeypatch.setattr(downloader.httpx, "AsyncClient", client)

        assert await _telecharger("https://exemple/test.csv") == CONTENU
        assert client.appels == 2

    async def test_trois_echecs_abandonnent(self, monkeypatch):
        client = _ClientFactice([httpx.ConnectError("x")] * 5)
        monkeypatch.setattr(downloader.httpx, "AsyncClient", client)

        with pytest.raises(TransientDownloadError):
            await _telecharger("https://exemple/test.csv")

        assert client.appels == 3

    async def test_un_404_n_est_pas_reessaye(self, monkeypatch):
        """Une saison non publiée ne le deviendra pas en insistant."""
        client = _ClientFactice([_reponse(404, b""), _reponse(200)])
        monkeypatch.setattr(downloader.httpx, "AsyncClient", client)

        with pytest.raises(DownloadFailedError):
            await _telecharger("https://exemple/test.csv")

        assert client.appels == 1

    async def test_une_reponse_vide_est_refusee(self, monkeypatch):
        """Ne jamais écraser des données existantes par un fichier vide."""
        client = _ClientFactice([_reponse(200, b"")])
        monkeypatch.setattr(downloader.httpx, "AsyncClient", client)

        with pytest.raises(DownloadFailedError):
            await _telecharger("https://exemple/test.csv")


class TestEcriture:
    async def test_le_fichier_est_ecrit(self, monkeypatch, tmp_path):
        monkeypatch.setattr(downloader.settings, "raw_dir", tmp_path)
        monkeypatch.setattr(downloader.httpx, "AsyncClient", _ClientFactice([_reponse(200)]))

        chemin = await download_league_season("E0", "2324")

        assert chemin is not None
        assert chemin.read_bytes() == CONTENU
        assert chemin.name == "E0_2324.csv"

    async def test_aucun_fichier_partiel_ne_subsiste(self, monkeypatch, tmp_path):
        monkeypatch.setattr(downloader.settings, "raw_dir", tmp_path)
        monkeypatch.setattr(downloader.httpx, "AsyncClient", _ClientFactice([_reponse(200)]))

        await download_league_season("E0", "2324")

        assert list(tmp_path.rglob("*.partiel")) == []

    async def test_un_echec_ne_touche_pas_le_fichier_existant(self, monkeypatch, tmp_path):
        """Règle du spec : ne pas supprimer les anciennes données sur réponse vide."""
        monkeypatch.setattr(downloader.settings, "raw_dir", tmp_path)
        dossier = tmp_path / "football_data" / "E0"
        dossier.mkdir(parents=True)
        existant = dossier / "E0_2324.csv"
        existant.write_bytes(b"donnees precieuses")
        monkeypatch.setattr(
            downloader.httpx, "AsyncClient", _ClientFactice([_reponse(500, b"")] * 5)
        )

        chemin = await download_league_season("E0", "2324", force=True)

        assert chemin is None
        assert existant.read_bytes() == b"donnees precieuses"

    async def test_le_fichier_existant_evite_le_reseau(self, monkeypatch, tmp_path):
        monkeypatch.setattr(downloader.settings, "raw_dir", tmp_path)
        dossier = tmp_path / "football_data" / "E0"
        dossier.mkdir(parents=True)
        (dossier / "E0_2324.csv").write_bytes(CONTENU)
        client = _ClientFactice([_reponse(200)])
        monkeypatch.setattr(downloader.httpx, "AsyncClient", client)

        await download_league_season("E0", "2324")

        assert client.appels == 0

    async def test_un_echec_definitif_retourne_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(downloader.settings, "raw_dir", tmp_path)
        monkeypatch.setattr(downloader.httpx, "AsyncClient", _ClientFactice([_reponse(404, b"")]))

        assert await download_league_season("E0", "1516") is None
