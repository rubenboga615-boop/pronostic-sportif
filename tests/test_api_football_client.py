"""Tests du client API-Football, sans le moindre appel réseau.

`httpx.MockTransport` permet de rejouer exactement les réponses que le
fournisseur envoie, y compris ses cas tordus. Le plus important d'entre eux :
**API-Football répond 200 sur ses erreurs applicatives**, en plaçant le détail
dans le champ `errors`. Un client qui se fie au code HTTP prend une clé invalide
pour un succès et enregistre une liste vide — rien ne signale alors que la
donnée manque.
"""

import json

import httpx
import pytest

from collectors.api_football.cache import TOUJOURS, CacheDisque
from collectors.api_football.client import ClientApiFootball
from collectors.api_football.erreurs import (
    AuthentificationError,
    CleManquanteError,
    QuotaEpuiseError,
    ReponseInattendueError,
    TransitoireError,
)
from collectors.api_football.quota import SuiviQuota


def _client(transport, tmp_path, **kwargs):
    """Client dont les appels HTTP passent par un transport simulé."""
    client = ClientApiFootball(
        cle="cle-de-test",
        cache=CacheDisque(tmp_path / "cache"),
        **kwargs,
    )

    async def _appeler(endpoint, params):
        url = f"{client.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(transport=transport) as http:
            reponse = await http.get(url, params=params, headers={"x-apisports-key": client.cle})
        client.quota.observer(reponse.headers)
        if reponse.status_code == 429:
            raise QuotaEpuiseError("429")
        if reponse.status_code in (401, 403):
            raise AuthentificationError(f"HTTP {reponse.status_code}")
        if reponse.status_code >= 500:
            raise TransitoireError(f"erreur serveur HTTP {reponse.status_code}")
        if reponse.status_code != 200:
            raise ReponseInattendueError(f"HTTP {reponse.status_code}")
        enveloppe = reponse.json()
        ClientApiFootball._verifier_erreurs_applicatives(endpoint, enveloppe)
        return enveloppe

    client._appeler = _appeler
    return client


def _succes(contenu, entetes=None):
    def gestionnaire(requete):
        return httpx.Response(
            200,
            json={"errors": [], "results": len(contenu), "response": contenu},
            headers=entetes or {},
        )

    return httpx.MockTransport(gestionnaire)


class TestErreursApplicativesSur200:
    """Le piège central du fournisseur."""

    @pytest.mark.asyncio
    async def test_une_cle_invalide_ne_passe_pas_pour_un_succes(self, tmp_path):
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"errors": {"token": "Invalid API key"}})
        )

        with pytest.raises(AuthentificationError, match="Invalid API key"):
            await _client(transport, tmp_path).get("fixtures")

    @pytest.mark.asyncio
    async def test_un_quota_epuise_annonce_en_200_est_reconnu(self, tmp_path):
        transport = httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"errors": {"requests": "You have reached the request limit for the day"}},
            )
        )

        with pytest.raises(QuotaEpuiseError):
            await _client(transport, tmp_path).get("fixtures")

    @pytest.mark.asyncio
    async def test_une_erreur_applicative_inconnue_ne_passe_pas_silencieusement(self, tmp_path):
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"errors": ["paramètre inconnu : leage"]})
        )

        with pytest.raises(ReponseInattendueError, match="leage"):
            await _client(transport, tmp_path).get("fixtures")

    @pytest.mark.asyncio
    async def test_une_liste_errors_vide_est_un_vrai_succes(self, tmp_path):
        client = _client(_succes([{"fixture": {"id": 1}}]), tmp_path)

        enveloppe = await client.get("fixtures")

        assert ClientApiFootball.reponses(enveloppe) == [{"fixture": {"id": 1}}]


class TestReessais:
    @pytest.mark.asyncio
    async def test_une_panne_passagere_est_reessayee(self, tmp_path, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _ne_dort_pas)
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            if appels["n"] < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"errors": [], "response": [{"ok": True}]})

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)

        enveloppe = await client.get("fixtures")

        assert appels["n"] == 3
        assert ClientApiFootball.reponses(enveloppe) == [{"ok": True}]

    @pytest.mark.asyncio
    async def test_un_quota_epuise_n_est_jamais_reessaye(self, tmp_path, monkeypatch):
        """Réessayer aggrave : certains plans décomptent aussi les refus."""
        monkeypatch.setattr("asyncio.sleep", _ne_dort_pas)
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            return httpx.Response(429)

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)

        with pytest.raises(QuotaEpuiseError):
            await client.get("fixtures")

        assert appels["n"] == 1

    @pytest.mark.asyncio
    async def test_une_cle_refusee_n_est_jamais_reessayee(self, tmp_path, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _ne_dort_pas)
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            return httpx.Response(401)

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)

        with pytest.raises(AuthentificationError):
            await client.get("fixtures")

        assert appels["n"] == 1

    @pytest.mark.asyncio
    async def test_l_echec_persistant_finit_par_lever(self, tmp_path, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _ne_dort_pas)
        transport = httpx.MockTransport(lambda r: httpx.Response(503))

        with pytest.raises(TransitoireError, match="3 tentatives"):
            await _client(transport, tmp_path).get("fixtures")


async def _ne_dort_pas(_):
    """Remplace asyncio.sleep : les tests ne doivent pas attendre réellement."""
    return None


class TestCache:
    @pytest.mark.asyncio
    async def test_un_second_appel_ne_touche_pas_le_reseau(self, tmp_path):
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            return httpx.Response(200, json={"errors": [], "response": [{"id": 1}]})

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)

        await client.get("fixtures", {"league": 39})
        await client.get("fixtures", {"league": 39})

        assert appels["n"] == 1

    @pytest.mark.asyncio
    async def test_des_parametres_differents_ne_partagent_pas_l_entree(self, tmp_path):
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            return httpx.Response(200, json={"errors": [], "response": []})

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)

        await client.get("fixtures", {"league": 39})
        await client.get("fixtures", {"league": 140})

        assert appels["n"] == 2

    @pytest.mark.asyncio
    async def test_l_ordre_des_parametres_est_indifferent(self, tmp_path):
        """Deux appels identiques doivent partager leur entrée."""
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            return httpx.Response(200, json={"errors": [], "response": []})

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)

        await client.get("fixtures", {"league": 39, "season": 2025})
        await client.get("fixtures", {"season": 2025, "league": 39})

        assert appels["n"] == 1

    @pytest.mark.asyncio
    async def test_forcer_ignore_le_cache_en_lecture(self, tmp_path):
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            return httpx.Response(200, json={"errors": [], "response": []})

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)

        await client.get("fixtures")
        await client.get("fixtures", forcer=True)

        assert appels["n"] == 2

    def test_une_entree_expiree_n_est_pas_servie(self, tmp_path):
        cache = CacheDisque(tmp_path / "c")
        cache.ecrire("fixtures", {}, {"response": []})

        fichier = cache.chemin("fixtures", {})
        enveloppe = json.loads(fichier.read_text(encoding="utf-8"))
        enveloppe["_ecrit_a"] -= 3600 * 48  # écrite il y a deux jours
        fichier.write_text(json.dumps(enveloppe), encoding="utf-8")

        assert cache.lire("fixtures", {}, duree_heures=24) is None
        assert cache.lire("fixtures", {}, duree_heures=TOUJOURS) is not None

    def test_une_entree_corrompue_est_ignoree_sans_planter(self, tmp_path):
        """Un fichier tronqué ne doit pas faire échouer une collecte."""
        cache = CacheDisque(tmp_path / "c")
        fichier = cache.chemin("fixtures", {})
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text('{"reponse": {"tronq', encoding="utf-8")

        assert cache.lire("fixtures", {}, duree_heures=24) is None

    def test_l_ecriture_ne_laisse_aucun_fichier_partiel(self, tmp_path):
        cache = CacheDisque(tmp_path / "c")
        cache.ecrire("fixtures", {"league": 39}, {"response": [1, 2]})

        assert not list((tmp_path / "c").rglob("*.partiel"))
        assert cache.lire("fixtures", {"league": 39}, 24) == {"response": [1, 2]}


class TestQuota:
    def test_les_entetes_sont_lues(self):
        suivi = SuiviQuota()

        suivi.observer(
            {"x-ratelimit-requests-remaining": "742", "x-ratelimit-requests-limit": "7500"}
        )

        assert suivi.restant == 742
        assert suivi.limite == 7500
        assert suivi.consommes == 1

    def test_des_entetes_absentes_ne_cassent_rien(self):
        """Leur nom a déjà changé par le passé ; leur absence n'est pas fatale."""
        suivi = SuiviQuota()

        suivi.observer({})

        assert suivi.restant is None
        assert suivi.consommes == 1
        assert suivi.autorise()

    def test_la_reserve_protege_les_appels_du_lendemain(self):
        suivi = SuiviQuota(reserve=50)

        suivi.observer({"x-ratelimit-requests-remaining": "50"})

        assert not suivi.autorise()
        assert "Réserve" in suivi.motif_de_refus()

    def test_le_plafond_arrete_une_boucle_fautive(self):
        suivi = SuiviQuota(plafond_execution=3)

        for _ in range(3):
            suivi.observer({})

        assert not suivi.autorise()
        assert "Plafond" in suivi.motif_de_refus()

    @pytest.mark.asyncio
    async def test_le_client_refuse_de_partir_quota_entame(self, tmp_path):
        client = _client(_succes([]), tmp_path, quota=SuiviQuota(plafond_execution=0))

        with pytest.raises(QuotaEpuiseError, match="Plafond"):
            await client.get("fixtures")


class TestCleManquante:
    @pytest.mark.asyncio
    async def test_sans_cle_aucun_appel_n_est_tente(self, tmp_path):
        appels = {"n": 0}

        def gestionnaire(requete):
            appels["n"] += 1
            return httpx.Response(200, json={"errors": [], "response": []})

        client = _client(httpx.MockTransport(gestionnaire), tmp_path)
        client.cle = ""

        with pytest.raises(CleManquanteError, match="API_FOOTBALL_KEY"):
            await client.get("fixtures")

        assert appels["n"] == 0

    @pytest.mark.asyncio
    async def test_le_cache_repond_meme_sans_cle(self, tmp_path):
        """Une collecte doit rester rejouable hors ligne, sans clé."""
        client = _client(_succes([{"id": 7}]), tmp_path)
        await client.get("fixtures", {"league": 39})

        hors_ligne = _client(_succes([]), tmp_path)
        hors_ligne.cle = ""
        hors_ligne.cache = client.cache

        enveloppe = await hors_ligne.get("fixtures", {"league": 39})

        assert ClientApiFootball.reponses(enveloppe) == [{"id": 7}]
