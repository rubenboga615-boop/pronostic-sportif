"""Cache disque des réponses API-Football.

Le cahier des charges impose de conserver localement les données récupérées et
de limiter les requêtes. Les deux exigences se rejoignent dans un cache sur
disque, qui rend en plus le travail **rejouable** : une collecte peut être
relancée, débogée et rejouée des mois plus tard sans dépenser un seul appel ni
dépendre de ce que le fournisseur publie encore.

La durée de validité dépend de ce qu'on demande, pas d'un réglage global :

- un match terminé ne change plus — on le garde indéfiniment ;
- un calendrier bouge encore — quelques heures ;
- des blessures se démentent d'un jour à l'autre — une heure au plus.

C'est à l'appelant de dire lequel il veut : lui seul le sait.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

# Conservé pour toujours : un fait passé ne change plus.
TOUJOURS = -1


@dataclass
class CacheDisque:
    """Cache par (endpoint, paramètres), horodaté."""

    racine: Path

    def __post_init__(self) -> None:
        self.racine = Path(self.racine)

    def chemin(self, endpoint: str, params: dict) -> Path:
        """Emplacement d'une entrée.

        Les paramètres sont triés avant hachage : deux appels identiques dont
        les clés sont dans un ordre différent doivent partager leur entrée.
        """
        signature = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
        empreinte = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
        return self.racine / endpoint.strip("/").replace("/", "_") / f"{empreinte}.json"

    def lire(self, endpoint: str, params: dict, duree_heures: float) -> dict | None:
        """Entrée encore valable, ou ``None``.

        ``duree_heures`` à :data:`TOUJOURS` ignore l'âge.
        """
        fichier = self.chemin(endpoint, params)
        if not fichier.exists():
            return None

        try:
            enveloppe = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erreur:
            logger.warning(f"Entrée de cache illisible, ignorée : {fichier} ({erreur})")
            return None

        if duree_heures != TOUJOURS:
            age = time.time() - enveloppe.get("_ecrit_a", 0)
            if age > duree_heures * 3600:
                return None

        return enveloppe.get("reponse")

    def ecrire(self, endpoint: str, params: dict, reponse: dict) -> Path:
        """Enregistrer une réponse. L'écriture est atomique.

        Sans écriture atomique, une interruption laisse un fichier tronqué que
        la lecture suivante prendra pour du JSON invalide — ou, pire, pour une
        réponse valide amputée.
        """
        fichier = self.chemin(endpoint, params)
        fichier.parent.mkdir(parents=True, exist_ok=True)

        enveloppe = {
            "_ecrit_a": time.time(),
            "_endpoint": endpoint,
            "_params": params,
            "reponse": reponse,
        }
        temporaire = fichier.with_suffix(".json.partiel")
        temporaire.write_text(
            json.dumps(enveloppe, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        temporaire.replace(fichier)
        return fichier

    def vider(self, endpoint: str | None = None) -> int:
        """Supprimer les entrées, d'un endpoint ou de tout le cache."""
        cible = self.racine / endpoint.strip("/").replace("/", "_") if endpoint else self.racine
        if not cible.exists():
            return 0

        supprimes = 0
        for fichier in cible.rglob("*.json"):
            fichier.unlink()
            supprimes += 1
        return supprimes
