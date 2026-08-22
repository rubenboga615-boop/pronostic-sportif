"""Registre des modèles entraînés."""

import json
from datetime import datetime
from pathlib import Path

from loguru import logger


class ModelRegistry:
    """Gestionnaire de versions de modèles."""

    def __init__(self, registry_dir: str = "data/models"):
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.registry_dir / "registry.json"

    def register(
        self,
        model_name: str,
        version: str,
        metrics: dict,
        file_path: str | None = None,
    ) -> None:
        """Enregistrer un modèle."""
        registry = self._load_registry()
        entry = {
            "model_name": model_name,
            "version": version,
            "registered_at": datetime.now().isoformat(),
            "metrics": metrics,
            "file_path": file_path,
        }
        registry.append(entry)
        self._save_registry(registry)
        logger.info(f"Modèle enregistré : {model_name} v{version}")

    def get_latest(self, model_name: str) -> dict | None:
        """Obtenir la dernière version d'un modèle."""
        registry = self._load_registry()
        model_versions = [r for r in registry if r["model_name"] == model_name]
        if not model_versions:
            return None
        return sorted(model_versions, key=lambda x: x["registered_at"])[-1]

    def _load_registry(self) -> list:
        if self.registry_file.exists():
            return json.loads(self.registry_file.read_text())
        return []

    def _save_registry(self, registry: list) -> None:
        self.registry_file.write_text(json.dumps(registry, indent=2))
