"""Correspondance entre les codes Football-Data et les identifiants API-Football.

Football-Data désigne la Premier League par ``E0``, API-Football par ``39``. La
table ci-dessous fait le pont pour les cinq championnats du périmètre.

Ces identifiants sont ceux publiés par le fournisseur et ils sont stables depuis
des années — mais ils restent une donnée extérieure, pas une constante du
projet. La sonde (:mod:`scripts.sonde_api_football`) les **vérifie** en
demandant à l'API le nom et le pays de chaque identifiant, et signale tout
écart. Mieux vaut une vérification de cinq appels qu'un import silencieusement
rangé sous la mauvaise compétition.
"""

from __future__ import annotations

# code Football-Data -> (identifiant API-Football, nom attendu, pays attendu)
LIGUES: dict[str, tuple[int, str, str]] = {
    "E0": (39, "Premier League", "England"),
    "SP1": (140, "La Liga", "Spain"),
    "I1": (135, "Serie A", "Italy"),
    "D1": (78, "Bundesliga", "Germany"),
    "F1": (61, "Ligue 1", "France"),
}


def identifiant(code: str) -> int:
    """Identifiant API-Football d'un code Football-Data."""
    if code not in LIGUES:
        raise KeyError(f"Championnat hors périmètre : {code!r}. Attendu : {sorted(LIGUES)}")
    return LIGUES[code][0]


def code_football_data(identifiant_api: int) -> str | None:
    """Chemin inverse, ou ``None`` si la ligue est hors périmètre."""
    for code, (ident, _, _) in LIGUES.items():
        if ident == identifiant_api:
            return code
    return None


def saison_api(saison_football_data: str) -> int:
    """``"2526"`` -> ``2025``.

    API-Football désigne une saison par son année de début. Football-Data la
    désigne par les deux années accolées. Les saisons antérieures à 2000 ne
    sont pas dans le périmètre : la conversion n'a pas à les gérer.
    """
    if len(saison_football_data) != 4 or not saison_football_data.isdigit():
        raise ValueError(
            f"Saison Football-Data attendue au format 'AABB' : {saison_football_data!r}"
        )
    return 2000 + int(saison_football_data[:2])
