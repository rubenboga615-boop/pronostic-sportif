"""Correspondance des noms d'équipes entre fournisseurs.

Football-Data écrit « Man United », Understat « Manchester United »,
API-Football « Manchester United » aussi mais « Wolverhampton Wanderers » là où
Football-Data écrit « Wolves ». Sans table de correspondance, chaque fournisseur
crée sa propre équipe et l'historique d'un club se scinde en autant de morceaux
qu'il y a de sources. Douze saisons de données deviennent inutilisables sans
qu'aucune erreur ne soit levée.

C'est le vrai travail des étapes 7 et 8 — pas les clients HTTP.

Deux principes, et le second est le plus important
--------------------------------------------------

**1. Les noms canoniques sont ceux de Football-Data.** C'est la source de
l'historique ; tout le reste s'y rattache. `collectors/football_data/
team_normalizer.py` en tient la liste, ligue par ligue.

**2. La résolution au runtime est stricte.** Un nom inconnu lève
:class:`NomInconnuError`. Il n'est **jamais** rapproché par ressemblance, et
aucune équipe n'est créée en silence.

Ce second point mérite qu'on s'y arrête, car il est contre-intuitif : un
appariement approximatif rendrait l'import plus confortable et c'est exactement
pour cela qu'il est interdit ici. « Real Sociedad » et « Real Madrid » se
ressemblent beaucoup ; « Nottingham Forest » et « Nottm Forest » aussi, mais
« Athletic Club » et « Atlético Madrid » également. Une seule confusion
contamine silencieusement des années d'historique, et rien ne la signale.

L'appariement approximatif existe donc, mais **hors ligne uniquement**
(:mod:`collectors.mapping.candidats`) : il propose, un humain dispose, et le
résultat est relu puis commité. Le fichier `equipes.json` est cette décision
figée.

Un import qui rencontre un nom absent du registre doit s'arrêter. C'est
volontaire : mieux vaut un import qui refuse de démarrer qu'un import qui
réussit en dupliquant Manchester United.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from collectors.football_data.team_normalizer import TEAM_ALIASES

FICHIER_PAR_DEFAUT = Path(__file__).parent / "equipes.json"

FOURNISSEURS = ("api_football", "understat")


class NomInconnuError(LookupError):
    """Un nom de fournisseur n'a pas de correspondance connue.

    Porte de quoi corriger : le fournisseur, la ligue, le nom rencontré, et les
    noms canoniques les plus proches — à titre indicatif seulement, jamais
    appliqués automatiquement.
    """

    def __init__(self, fournisseur: str, ligue: str, nom: str, suggestions: list[str]):
        self.fournisseur = fournisseur
        self.ligue = ligue
        self.nom = nom
        self.suggestions = suggestions

        piste = f" Proches : {', '.join(suggestions)}." if suggestions else ""
        super().__init__(
            f"Équipe inconnue chez {fournisseur} en {ligue} : {nom!r}.{piste}\n"
            f"Ajoutez la correspondance dans {FICHIER_PAR_DEFAUT.name}, "
            f"après vérification. Aucun rapprochement automatique n'est fait : "
            f"une confusion contaminerait l'historique en silence."
        )


def normaliser(nom: str) -> str:
    """Forme comparable d'un nom : sans accent, sans casse, sans ponctuation.

    Sert **uniquement** aux correspondances exactes après nettoyage — « Atlético
    Madrid » et « Atletico Madrid » désignent la même équipe, la différence est
    typographique. Elle ne rapproche jamais deux noms réellement distincts.
    """
    sans_accent = unicodedata.normalize("NFKD", nom)
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    garde = [c.lower() if c.isalnum() else " " for c in sans_accent]
    return " ".join("".join(garde).split())


@dataclass
class RegistreCorrespondances:
    """Table fournisseur → ligue → nom du fournisseur → nom canonique."""

    correspondances: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)

    # ── Résolution ───────────────────────────────────────────────────────

    def canonique(self, fournisseur: str, ligue: str, nom: str) -> str:
        """Nom canonique d'une équipe, ou lever.

        Trois chemins, dans cet ordre, et aucun quatrième :

        1. le registre porte une correspondance explicite ;
        2. le nom est déjà un nom canonique de cette ligue ;
        3. le nom, une fois normalisé, égale un nom canonique normalisé —
           différence d'accent ou de ponctuation seulement.

        Sinon : :class:`NomInconnuError`.

        Raises:
            NomInconnuError: le nom n'a pas de correspondance connue.
        """
        table = self.correspondances.get(fournisseur, {}).get(ligue, {})
        if nom in table:
            return table[nom]

        canoniques = self._canoniques(ligue)
        if nom in canoniques:
            return nom

        cible = normaliser(nom)
        for canonique in canoniques:
            if normaliser(canonique) == cible:
                return canonique

        raise NomInconnuError(fournisseur, ligue, nom, self._proches(ligue, nom))

    def connait(self, fournisseur: str, ligue: str, nom: str) -> bool:
        """Le nom est-il résoluble ? Sans lever."""
        try:
            self.canonique(fournisseur, ligue, nom)
        except NomInconnuError:
            return False
        return True

    def noms_non_resolus(self, fournisseur: str, ligue: str, noms) -> list[str]:
        """Les noms qu'un import échouerait à résoudre, dans l'ordre reçu.

        À appeler **avant** un import : il vaut mieux connaître d'un coup les
        vingt noms manquants que d'échouer vingt fois de suite.
        """
        vus: dict[str, None] = {}
        for nom in noms:
            if not self.connait(fournisseur, ligue, nom):
                vus.setdefault(nom, None)
        return list(vus)

    # ── Cohérence ────────────────────────────────────────────────────────

    def verifier(self) -> list[str]:
        """Anomalies du registre, sous forme de messages lisibles.

        Une correspondance qui pointe vers un nom canonique inexistant est pire
        qu'une correspondance absente : elle passe les contrôles et écrit une
        équipe fantôme.
        """
        anomalies: list[str] = []
        for fournisseur, ligues in self.correspondances.items():
            if fournisseur not in FOURNISSEURS:
                anomalies.append(f"Fournisseur inattendu : {fournisseur!r}")
            for ligue, table in ligues.items():
                if ligue not in TEAM_ALIASES:
                    anomalies.append(f"{fournisseur} : ligue inconnue {ligue!r}")
                    continue
                canoniques = self._canoniques(ligue)
                for nom, cible in table.items():
                    if cible not in canoniques:
                        anomalies.append(
                            f"{fournisseur}/{ligue} : {nom!r} pointe vers {cible!r}, "
                            f"qui n'est pas un nom canonique de cette ligue"
                        )
        return anomalies

    # ── Interne ──────────────────────────────────────────────────────────

    def _canoniques(self, ligue: str) -> set[str]:
        return set(TEAM_ALIASES.get(ligue, {}).values())

    def _proches(self, ligue: str, nom: str, n: int = 3) -> list[str]:
        """Noms canoniques les plus ressemblants — pour le message d'erreur seul."""
        from difflib import get_close_matches

        return get_close_matches(normaliser(nom), sorted(self._canoniques(ligue)), n=n, cutoff=0.6)


def charger_registre(chemin: Path | None = None) -> RegistreCorrespondances:
    """Charger le registre commité, ou un registre vide s'il n'existe pas encore.

    Un registre vide est un état de départ valable : la résolution stricte
    fonctionne déjà sur les noms qui coïncident avec les noms canoniques, et
    tout le reste lève — ce qui est le comportement voulu.
    """
    chemin = chemin or FICHIER_PAR_DEFAUT
    if not chemin.exists():
        logger.info(f"Aucun registre de correspondances en {chemin} : registre vide")
        return RegistreCorrespondances()

    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    registre = RegistreCorrespondances(correspondances=donnees.get("correspondances", {}))

    anomalies = registre.verifier()
    if anomalies:
        raise ValueError("Registre de correspondances incohérent :\n  " + "\n  ".join(anomalies))

    total = sum(len(t) for ligues in registre.correspondances.values() for t in ligues.values())
    logger.info(f"Registre chargé : {total} correspondances")
    return registre
