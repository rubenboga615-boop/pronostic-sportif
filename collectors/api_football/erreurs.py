"""Erreurs typées du client API-Football.

Distinguer les causes n'est pas une coquetterie : elles n'appellent pas la même
réaction. Un quota épuisé ne se réessaie pas — il faut attendre le lendemain.
Une coupure réseau, si. Une clé refusée ne se réessaie jamais, elle se corrige.

Un client qui ne fait pas ces distinctions boucle sur des erreurs définitives et
consomme le quota qu'il essaie d'économiser.
"""

from __future__ import annotations


class ApiFootballError(Exception):
    """Racine des erreurs du collecteur."""


class CleManquanteError(ApiFootballError):
    """Aucune clé configurée. Définitif, et corrigeable en une ligne."""

    def __init__(self) -> None:
        super().__init__(
            "API_FOOTBALL_KEY n'est pas définie.\n"
            "  Ajoutez-la dans .env (voir .env.example), puis relancez.\n"
            "Aucun appel n'a été tenté."
        )


class AuthentificationError(ApiFootballError):
    """Clé refusée par le fournisseur. Définitif : ne jamais réessayer."""


class QuotaEpuiseError(ApiFootballError):
    """Quota journalier atteint.

    Définitif pour la journée. Réessayer ne fait qu'aggraver : certains plans
    comptent aussi les requêtes refusées.
    """

    def __init__(self, message: str = "", reinitialisation: str | None = None) -> None:
        self.reinitialisation = reinitialisation
        detail = f" Réinitialisation : {reinitialisation}." if reinitialisation else ""
        super().__init__(
            (message or "Quota journalier API-Football épuisé.") + detail + "\n"
            "Aucun réessai n'est tenté : certains plans décomptent aussi les "
            "requêtes refusées."
        )


class TransitoireError(ApiFootballError):
    """Panne passagère : coupure réseau, 5xx, dépassement de débit.

    C'est la seule famille que le client réessaie.
    """


class ReponseInattendueError(ApiFootballError):
    """Réponse reçue mais inexploitable : JSON invalide, enveloppe absente.

    Traitée comme définitive : réessayer la même requête donnerait la même
    réponse. C'est le schéma du fournisseur qui a changé, ou notre lecture qui
    est fausse.
    """
