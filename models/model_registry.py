"""Registre des modèles entraînés.

Un modèle qui ne peut pas être rechargé à l'identique ne peut pas être audité :
il devient impossible de dire avec quels paramètres une prédiction datée de
l'an dernier a été produite. `PROJECT_SPEC.md` exige des « modèles versionnés »
au livrable de première année, et que chaque prédiction porte sa
``model_version``.

Le registre écrit deux choses côte à côte :

- un fichier par version, contenant les paramètres du modèle ;
- un index JSON listant les versions, leurs métriques et leur date.

Le registre précédent ne savait enregistrer que des métadonnées : il notait
qu'un modèle existait, sans jamais conserver de quoi le rejouer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


class ModelRegistry:
    """Gestionnaire de versions de modèles."""

    def __init__(self, registry_dir: str | Path = "data/models"):
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.registry_dir / "registry.json"

    # ── Écriture ─────────────────────────────────────────────────────────

    def register(
        self,
        model_name: str,
        version: str,
        metrics: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Enregistrer une version de modèle.

        Args:
            model_name: nom du modèle (``"dixon_coles"``, ``"poisson"``…).
            version: identifiant de version, unique pour ce modèle.
            metrics: métriques d'évaluation associées.
            payload: paramètres du modèle, écrits dans un fichier dédié et
                rechargeables par :meth:`load`.
            file_path: chemin d'un artefact externe, si le modèle n'est pas
                sérialisable en JSON.

        Returns:
            L'entrée d'index créée.

        Raises:
            ValueError: si cette version existe déjà pour ce modèle.
        """
        index = self._load_registry()
        if any(e["model_name"] == model_name and e["version"] == version for e in index):
            raise ValueError(
                f"La version {version!r} de {model_name!r} est déjà enregistrée. "
                "Écraser un modèle rendrait ses prédictions passées inexplicables."
            )

        chemin_payload = None
        if payload is not None:
            chemin_payload = self._payload_path(model_name, version)
            chemin_payload.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        entree = {
            "model_name": model_name,
            "version": version,
            "registered_at": datetime.now(UTC).isoformat(),
            "metrics": metrics or {},
            "payload_path": str(chemin_payload) if chemin_payload else None,
            "file_path": file_path,
        }
        index.append(entree)
        self._save_registry(index)
        logger.info(f"Modèle enregistré : {model_name} v{version}")
        return entree

    # ── Lecture ──────────────────────────────────────────────────────────

    def get_latest(self, model_name: str) -> dict[str, Any] | None:
        """Dernière version enregistrée d'un modèle, ou None."""
        versions = [e for e in self._load_registry() if e["model_name"] == model_name]
        if not versions:
            return None
        return sorted(versions, key=lambda e: e["registered_at"])[-1]

    def get(self, model_name: str, version: str) -> dict[str, Any] | None:
        """Entrée d'index d'une version précise, ou None."""
        for entree in self._load_registry():
            if entree["model_name"] == model_name and entree["version"] == version:
                return entree
        return None

    def load(self, model_name: str, version: str | None = None) -> dict[str, Any] | None:
        """Recharger les paramètres d'un modèle.

        Sans ``version``, la dernière enregistrée est utilisée. Retourne None si
        le modèle est inconnu ou n'a pas de paramètres stockés.
        """
        entree = self.get(model_name, version) if version else self.get_latest(model_name)
        if entree is None or not entree.get("payload_path"):
            return None

        chemin = Path(entree["payload_path"])
        if not chemin.exists():
            logger.warning(f"Paramètres introuvables pour {model_name} v{entree['version']}")
            return None
        return json.loads(chemin.read_text(encoding="utf-8"))

    def versions(self, model_name: str | None = None) -> list[dict[str, Any]]:
        """Versions enregistrées, filtrées par modèle et triées du plus ancien."""
        index = self._load_registry()
        if model_name is not None:
            index = [e for e in index if e["model_name"] == model_name]
        return sorted(index, key=lambda e: e["registered_at"])

    # ── Stockage ─────────────────────────────────────────────────────────

    def _payload_path(self, model_name: str, version: str) -> Path:
        sur = "".join(c if c.isalnum() or c in "-._" else "_" for c in f"{model_name}-{version}")
        return self.registry_dir / f"{sur}.json"

    def _load_registry(self) -> list[dict[str, Any]]:
        if not self.registry_file.exists():
            return []
        contenu = self.registry_file.read_text(encoding="utf-8").strip()
        return json.loads(contenu) if contenu else []

    def _save_registry(self, index: list[dict[str, Any]]) -> None:
        # Écriture atomique : un index tronqué ferait perdre la trace de toutes
        # les versions, y compris celles dont les fichiers existent encore.
        temporaire = self.registry_file.with_suffix(".json.partiel")
        temporaire.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        temporaire.replace(self.registry_file)
