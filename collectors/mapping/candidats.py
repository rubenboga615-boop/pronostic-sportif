"""Appariement approximatif des noms d'équipes — **hors ligne uniquement**.

Ce module propose des correspondances ; il n'en applique aucune. Sa sortie est
destinée à être relue par un humain, corrigée, puis commitée dans
`equipes.json`. La résolution au runtime, elle, est strictement exacte
(:mod:`collectors.mapping.registre`).

Cette séparation n'est pas de la prudence décorative. Les noms d'équipes de
football sont un piège particulier : « Real Sociedad » et « Real Madrid »
partagent la moitié de leurs caractères sans avoir le moindre rapport, tandis
que « Wolves » et « Wolverhampton Wanderers » n'en partagent presque aucun tout
en désignant le même club. Aucun seuil ne sépare correctement ces deux cas. Un
humain, oui — en quelques minutes, une fois pour toutes.

Le générateur sert donc à réduire le travail de relecture, pas à le supprimer :
il range les noms en quatre tas, dont un seul demande une vraie décision.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from collectors.football_data.team_normalizer import TEAM_ALIASES
from collectors.mapping.registre import RegistreCorrespondances, normaliser

# Au-dessus, la ressemblance est forte ET nettement détachée de la suivante :
# le candidat est proposé d'emblée. En dessous, l'humain tranche.
SEUIL_CANDIDAT = 0.85

# Écart minimal avec le deuxième candidat. Sans lui, « Real Madrid » à 0,88 et
# « Real Sociedad » à 0,87 seraient tous deux « évidents ».
ECART_MINIMAL = 0.08

# En dessous, le meilleur score ne vaut pas d'être regardé : le nom ne
# correspond à rien de cette ligue. « Paris Saint Germain » comparé aux clubs
# anglais atteint 0,47 sur « Queens Park Rangers » — ce n'est pas une ambiguïté
# à trancher, c'est une équipe qui n'y est pas.
SEUIL_PLANCHER = 0.60

DECISIONS = ("resolu", "candidat", "ambigu", "aucun")


@dataclass
class Proposition:
    """Une ligne de la proposition soumise à relecture."""

    nom: str
    decision: str
    canonique: str | None = None
    score: float = 0.0
    autres: list[tuple[str, float]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.autres is None:
            self.autres = []


def ressemblance(a: str, b: str) -> float:
    """Score entre 0 et 1, sur les formes normalisées.

    Combine deux vues :

    - la similarité de séquence, qui capte les variantes typographiques et les
      troncatures (« Nottm Forest » / « Nottingham Forest ») ;
    - le recouvrement de mots, qui capte les suffixes ajoutés ou retirés
      (« Milan » / « AC Milan »).

    Le maximum des deux est retenu : chacune rattrape les angles morts de
    l'autre. Aucune ne suffit seule, et les deux réunies ne suffisent pas non
    plus — d'où la relecture.
    """
    na, nb = normaliser(a), normaliser(b)
    if not na or not nb:
        return 0.0

    sequence = SequenceMatcher(None, na, nb).ratio()

    mots_a, mots_b = set(na.split()), set(nb.split())
    communs = mots_a & mots_b
    recouvrement = len(communs) / min(len(mots_a), len(mots_b)) if communs else 0.0

    return max(sequence, recouvrement)


def proposer(
    fournisseur: str,
    ligue: str,
    noms: list[str],
    registre: RegistreCorrespondances | None = None,
) -> list[Proposition]:
    """Ranger les noms d'un fournisseur en quatre tas.

    Args:
        fournisseur: ``"api_football"`` ou ``"understat"``.
        ligue: code Football-Data (``"E0"``, ``"SP1"``…).
        noms: noms tels que le fournisseur les écrit.
        registre: registre déjà commité, pour ne pas reproposer l'acquis.

    Returns:
        Une proposition par nom, avec sa décision :

        - ``resolu`` — déjà résoluble, rien à faire ;
        - ``candidat`` — un rapprochement net, **à confirmer** ;
        - ``ambigu`` — plusieurs candidats proches, à trancher ;
        - ``aucun`` — rien de ressemblant au-dessus du plancher ; équipe
          absente de cette ligue, ou nom canonique à créer.
    """
    registre = registre or RegistreCorrespondances()
    canoniques = sorted(set(TEAM_ALIASES.get(ligue, {}).values()))

    propositions: list[Proposition] = []
    for nom in noms:
        if registre.connait(fournisseur, ligue, nom):
            propositions.append(Proposition(nom=nom, decision="resolu"))
            continue

        scores = sorted(
            ((c, ressemblance(nom, c)) for c in canoniques),
            key=lambda paire: (-paire[1], paire[0]),
        )
        if not scores or scores[0][1] < SEUIL_PLANCHER:
            propositions.append(Proposition(nom=nom, decision="aucun"))
            continue

        meilleur, score = scores[0]
        second = scores[1][1] if len(scores) > 1 else 0.0
        net = score >= SEUIL_CANDIDAT and (score - second) >= ECART_MINIMAL

        propositions.append(
            Proposition(
                nom=nom,
                decision="candidat" if net else "ambigu",
                canonique=meilleur,
                score=round(score, 3),
                autres=[(c, round(s, 3)) for c, s in scores[1:4] if s > 0],
            )
        )

    return propositions


def resume(propositions: list[Proposition]) -> dict[str, int]:
    """Compte par décision — de quoi savoir combien de relecture reste."""
    return {
        decision: sum(1 for p in propositions if p.decision == decision) for decision in DECISIONS
    }
