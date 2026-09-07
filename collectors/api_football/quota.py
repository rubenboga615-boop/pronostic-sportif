"""Suivi du quota API-Football.

Le fournisseur renvoie l'état du quota dans les en-têtes de chaque réponse. Les
lire coûte zéro appel — les ignorer oblige à découvrir l'épuisement en s'y
cognant, souvent au milieu d'une collecte, à moitié écrite.

Deux garde-fous distincts :

- une **réserve** sous laquelle le client refuse de partir. Elle protège les
  appels indispensables du lendemain contre un script qui boucle ;
- un **plafond par exécution**, pour qu'une erreur de boucle ne brûle pas la
  journée entière en quelques secondes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

# En-têtes publiés par api-sports.io. Leur nom a déjà changé par le passé ; leur
# absence n'est donc pas une erreur, seulement une information en moins.
ENTETE_RESTANT = "x-ratelimit-requests-remaining"
ENTETE_LIMITE = "x-ratelimit-requests-limit"

RESERVE_PAR_DEFAUT = 50
PLAFOND_PAR_DEFAUT = 1000


@dataclass
class SuiviQuota:
    """État du quota, mis à jour à chaque réponse."""

    reserve: int = RESERVE_PAR_DEFAUT
    plafond_execution: int = PLAFOND_PAR_DEFAUT

    restant: int | None = None
    limite: int | None = None
    consommes: int = 0
    _prevenu: bool = field(default=False, repr=False)

    def observer(self, entetes) -> None:
        """Lire l'état du quota dans les en-têtes d'une réponse."""
        self.consommes += 1

        brut = entetes.get(ENTETE_RESTANT) if entetes else None
        if brut is not None:
            try:
                self.restant = int(brut)
            except (TypeError, ValueError):
                logger.warning(f"En-tête de quota illisible : {brut!r}")

        brut_limite = entetes.get(ENTETE_LIMITE) if entetes else None
        if brut_limite is not None:
            try:
                self.limite = int(brut_limite)
            except (TypeError, ValueError):
                pass

        if self.restant is not None and self.restant <= self.reserve and not self._prevenu:
            logger.warning(
                f"Quota API-Football bas : {self.restant} requêtes restantes, "
                f"réserve fixée à {self.reserve}. Les appels non essentiels "
                f"vont être refusés."
            )
            self._prevenu = True

    def autorise(self) -> bool:
        """Peut-on encore émettre une requête ?"""
        return self.motif_de_refus() is None

    def motif_de_refus(self) -> str | None:
        """Pourquoi la prochaine requête serait refusée, ou ``None``."""
        if self.consommes >= self.plafond_execution:
            return (
                f"Plafond de cette exécution atteint : {self.consommes} requêtes. "
                f"Ce plafond existe pour qu'une boucle fautive ne brûle pas le "
                f"quota de la journée ; relevez-le sciemment si c'est voulu."
            )
        if self.restant is not None and self.restant <= self.reserve:
            return (
                f"Réserve de quota atteinte : {self.restant} requêtes restantes "
                f"pour une réserve de {self.reserve}. Les appels indispensables "
                f"de demain sont protégés."
            )
        return None

    def etat(self) -> dict:
        """Résumé destiné au journal et à `source_health`."""
        return {
            "consommes": self.consommes,
            "restant": self.restant,
            "limite": self.limite,
            "reserve": self.reserve,
            "plafond_execution": self.plafond_execution,
        }
