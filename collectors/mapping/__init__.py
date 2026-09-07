"""Correspondance des noms d'équipes entre fournisseurs."""

from collectors.mapping.registre import (
    NomInconnuError,
    RegistreCorrespondances,
    charger_registre,
)

__all__ = ["NomInconnuError", "RegistreCorrespondances", "charger_registre"]
