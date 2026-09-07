"""Client HTTP API-Football.

Assemble trois pièces qui protègent chacune d'un échec différent :

- :mod:`collectors.api_football.quota` — ne pas brûler le quota, et le savoir
  avant de partir plutôt qu'au milieu d'une collecte à moitié écrite ;
- :mod:`collectors.api_football.cache` — ne pas redemander ce qu'on a déjà, et
  rendre toute collecte rejouable hors ligne ;
- :mod:`collectors.api_football.erreurs` — distinguer ce qui se réessaie de ce
  qui ne se réessaie pas.

Ce dernier point mérite d'être explicite, car c'est là que les clients écrits à
la hâte perdent leur quota : un réessai sur quota épuisé ou sur clé refusée ne
réussira jamais, et certains plans décomptent aussi les requêtes refusées. Le
client ne réessaie donc **que** les pannes passagères.

Une particularité du fournisseur, à connaître : **il répond 200 sur des erreurs
applicatives**, en plaçant le détail dans le champ ``errors`` de l'enveloppe
JSON. Un client qui se fie au seul code HTTP prend une clé invalide pour un
succès et enregistre une liste vide. L'enveloppe est donc inspectée à chaque
réponse.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from app.config import settings
from collectors.api_football.cache import TOUJOURS, CacheDisque
from collectors.api_football.erreurs import (
    AuthentificationError,
    CleManquanteError,
    QuotaEpuiseError,
    ReponseInattendueError,
    TransitoireError,
)
from collectors.api_football.quota import SuiviQuota

BASE_URL_PAR_DEFAUT = "https://v3.football.api-sports.io"

TENTATIVES = 3
ATTENTE_INITIALE = 2.0

# Messages d'erreur applicative renvoyés avec un code 200. Comparés en
# minuscules et par inclusion : leur formulation exacte a déjà changé.
MOTIFS_QUOTA = ("reached the request limit", "quota", "too many requests")
MOTIFS_AUTH = ("invalid api key", "not subscribed", "missing api key", "invalid token")


@dataclass
class ClientApiFootball:
    """Client asynchrone, avec quota, cache et réessais."""

    cle: str = ""
    base_url: str = BASE_URL_PAR_DEFAUT
    cache: CacheDisque | None = None
    quota: SuiviQuota = field(default_factory=SuiviQuota)
    timeout: float = 20.0

    def __post_init__(self) -> None:
        self.cle = self.cle or settings.api_football_key
        if self.cache is None:
            self.cache = CacheDisque(Path(settings.raw_dir) / "api_football")

    # ── Appel ────────────────────────────────────────────────────────────

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        duree_cache_heures: float = 24.0,
        forcer: bool = False,
    ) -> dict[str, Any]:
        """Appeler un endpoint, en passant par le cache.

        Args:
            endpoint: chemin relatif, ``"fixtures"`` par exemple.
            params: paramètres de requête.
            duree_cache_heures: validité de l'entrée en cache.
                :data:`~collectors.api_football.cache.TOUJOURS` pour un fait
                passé, qui ne changera plus.
            forcer: ignorer le cache en lecture. L'écriture a lieu quand même.

        Returns:
            L'enveloppe JSON complète du fournisseur.

        Raises:
            CleManquanteError: aucune clé configurée.
            AuthentificationError: clé refusée.
            QuotaEpuiseError: quota atteint, ou réserve locale entamée.
            TransitoireError: échec passager persistant après réessais.
            ReponseInattendueError: réponse inexploitable.
        """
        params = params or {}

        if not forcer:
            en_cache = self.cache.lire(endpoint, params, duree_cache_heures)
            if en_cache is not None:
                logger.debug(f"Cache : {endpoint} {params}")
                return en_cache

        if not self.cle:
            raise CleManquanteError()

        motif = self.quota.motif_de_refus()
        if motif:
            raise QuotaEpuiseError(motif)

        reponse = await self._appeler_avec_reessais(endpoint, params)
        self.cache.ecrire(endpoint, params, reponse)
        return reponse

    async def _appeler_avec_reessais(self, endpoint: str, params: dict) -> dict:
        """Réessayer les seules pannes passagères, en espaçant les tentatives."""
        attente = ATTENTE_INITIALE
        derniere: Exception | None = None

        for tentative in range(1, TENTATIVES + 1):
            try:
                return await self._appeler(endpoint, params)
            except TransitoireError as erreur:
                derniere = erreur
                if tentative == TENTATIVES:
                    break
                logger.warning(
                    f"{endpoint} : échec passager ({erreur}), "
                    f"nouvelle tentative dans {attente:.0f} s "
                    f"[{tentative}/{TENTATIVES}]"
                )
                await asyncio.sleep(attente)
                attente *= 2

        raise TransitoireError(
            f"{endpoint} : échec après {TENTATIVES} tentatives. Dernière cause : {derniere}"
        )

    async def _appeler(self, endpoint: str, params: dict) -> dict:
        """Une tentative, et l'inspection complète de la réponse."""
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        entetes = {"x-apisports-key": self.cle}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                reponse = await client.get(url, params=params, headers=entetes)
        except (httpx.TimeoutException, httpx.TransportError) as erreur:
            raise TransitoireError(f"réseau indisponible : {erreur}") from erreur

        self.quota.observer(reponse.headers)

        if reponse.status_code == 429:
            raise QuotaEpuiseError(
                "Le fournisseur a répondu 429 (trop de requêtes).",
                reinitialisation=reponse.headers.get("x-ratelimit-reset"),
            )
        if reponse.status_code in (401, 403):
            raise AuthentificationError(
                f"Clé refusée par le fournisseur (HTTP {reponse.status_code}). "
                f"Vérifiez API_FOOTBALL_KEY et l'état de l'abonnement."
            )
        if reponse.status_code >= 500:
            raise TransitoireError(f"erreur serveur HTTP {reponse.status_code}")
        if reponse.status_code != 200:
            raise ReponseInattendueError(
                f"{endpoint} : HTTP {reponse.status_code} — {reponse.text[:200]}"
            )

        try:
            enveloppe = reponse.json()
        except ValueError as erreur:
            raise ReponseInattendueError(f"{endpoint} : JSON invalide") from erreur

        if not isinstance(enveloppe, dict):
            raise ReponseInattendueError(f"{endpoint} : enveloppe inattendue")

        self._verifier_erreurs_applicatives(endpoint, enveloppe)
        return enveloppe

    @staticmethod
    def _verifier_erreurs_applicatives(endpoint: str, enveloppe: dict) -> None:
        """API-Football répond 200 sur ses erreurs applicatives.

        Sans cette inspection, une clé invalide passe pour un succès et le
        collecteur enregistre une liste vide — le pire des deux mondes, puisque
        rien ne signale que la donnée manque.
        """
        erreurs = enveloppe.get("errors")
        if not erreurs:
            return
        if isinstance(erreurs, dict):
            messages = [str(v) for v in erreurs.values()]
        elif isinstance(erreurs, list):
            messages = [str(e) for e in erreurs]
        else:
            messages = [str(erreurs)]

        texte = " | ".join(messages)
        minuscule = texte.lower()

        if any(motif in minuscule for motif in MOTIFS_QUOTA):
            raise QuotaEpuiseError(f"{endpoint} : {texte}")
        if any(motif in minuscule for motif in MOTIFS_AUTH):
            raise AuthentificationError(f"{endpoint} : {texte}")

        raise ReponseInattendueError(f"{endpoint} : le fournisseur signale — {texte}")

    # ── Confort ──────────────────────────────────────────────────────────

    @staticmethod
    def reponses(enveloppe: dict) -> list:
        """Le contenu utile d'une enveloppe, toujours sous forme de liste."""
        contenu = enveloppe.get("response")
        if contenu is None:
            return []
        return contenu if isinstance(contenu, list) else [contenu]

    def etat_quota(self) -> dict:
        return self.quota.etat()


__all__ = ["TOUJOURS", "BASE_URL_PAR_DEFAUT", "ClientApiFootball"]
