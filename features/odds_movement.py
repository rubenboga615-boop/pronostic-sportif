"""Calcul du mouvement de cote, strictement avant la date de coupure.

Le mouvement d'une cote est une variable prédictive légitime — le marché
intègre de l'information au fil des jours — **à condition de n'observer que des
cotes disponibles au moment de prédire**.

La cote de clôture ne l'est jamais : elle est relevée au coup d'envoi, une fois
la composition connue et les paris placés. `PROJECT_SPEC.md` l'exclut
explicitement des variables prédictives. Sur les données réelles, un
`odds_movement` calculé depuis la clôture porte la trace du résultat : la cote
du futur vainqueur a baissé.

Ce module rend la fuite impossible par construction : la date de coupure est
obligatoire, les relevés de clôture sont écartés, et un relevé dont l'instant de
capture est inconnu est traité comme inutilisable — jamais comme antérieur.

Conséquence assumée avec Football-Data.co.uk, qui ne publie que deux cotes par
match (ouverture, sans horodatage, et clôture) : la fonction retourne ``None``.
Le mouvement redeviendra calculable dès qu'une source fournira plusieurs relevés
pré-match horodatés, sans qu'une ligne de ce module change.
"""

import pandas as pd


def calculate_odds_movement(
    odds_data: pd.DataFrame,
    match_id: int,
    market: str = "1N2",
    selection: str = "home",
    *,
    cutoff,
    bookmaker: str | None = None,
) -> dict:
    """Calculer le mouvement de cote d'une sélection avant la date de coupure.

    Compare le premier et le dernier relevé **strictement antérieurs** à
    ``cutoff``, chez un même bookmaker — comparer deux bookmakers mesurerait
    l'écart de leurs marges, pas un mouvement.

    Args:
        odds_data: relevés de cotes (colonnes ``match_id``, ``market``,
            ``selection``, ``bookmaker``, ``odds``, ``captured_at``,
            ``is_closing``).
        match_id: match concerné.
        market: marché, tel que stocké en base (``"1N2"`` par défaut).
        selection: sélection (``"home"``, ``"draw"``, ``"away"``).
        cutoff: date de coupure, obligatoire. Seuls les relevés capturés
            strictement avant sont pris en compte.
        bookmaker: bookmaker à suivre. Par défaut, celui qui offre le plus de
            relevés exploitables (départage par ordre alphabétique, pour un
            résultat déterministe).

    Returns:
        ``{"odds_movement": float}`` — variation relative entre le premier et le
        dernier relevé retenu — ou ``{"odds_movement": None}`` si moins de deux
        relevés exploitables existent avant la coupure.

    Raises:
        ValueError: si ``cutoff`` est ``None``.
    """
    if cutoff is None:
        raise ValueError(
            "cutoff est obligatoire : sans date de coupure, le calcul peut "
            "intégrer des cotes indisponibles au moment de prédire"
        )

    if odds_data is None or odds_data.empty:
        return {"odds_movement": None}

    usable = _usable_snapshots(odds_data, match_id, market, selection, cutoff)
    if usable.empty:
        return {"odds_movement": None}

    if bookmaker is None:
        bookmaker = _busiest_bookmaker(usable)
    series = usable[usable["bookmaker"] == bookmaker].sort_values("captured_at")

    if len(series) < 2:
        return {"odds_movement": None}

    first = float(series.iloc[0]["odds"])
    last = float(series.iloc[-1]["odds"])
    if first <= 0:
        return {"odds_movement": None}

    return {"odds_movement": (last - first) / first}


def _usable_snapshots(
    odds_data: pd.DataFrame,
    match_id: int,
    market: str,
    selection: str,
    cutoff,
) -> pd.DataFrame:
    """Relevés exploitables : bon match, bon marché, pré-coupure, hors clôture."""
    rows = odds_data[
        (odds_data["match_id"] == match_id)
        & (odds_data["market"] == market)
        & (odds_data["selection"] == selection)
    ]
    if rows.empty:
        return rows

    # Un relevé de clôture n'est jamais disponible avant le match.
    if "is_closing" in rows.columns:
        rows = rows[~rows["is_closing"].astype(bool)]
        if rows.empty:
            return rows

    # Un instant de capture inconnu ne peut pas être supposé antérieur.
    if "captured_at" not in rows.columns:
        return rows.iloc[0:0]
    captured = pd.to_datetime(rows["captured_at"], errors="coerce")
    garde = (
        captured.notna()
        & (captured < pd.Timestamp(cutoff))
        & rows["odds"].notna()
        & (rows["odds"] > 0)
    )
    return rows.loc[garde].assign(captured_at=captured[garde])


def _busiest_bookmaker(usable: pd.DataFrame) -> str:
    """Bookmaker offrant le plus de relevés, départagé par ordre alphabétique."""
    counts = usable.groupby("bookmaker").size()
    best = counts.max()
    return sorted(counts[counts == best].index)[0]
