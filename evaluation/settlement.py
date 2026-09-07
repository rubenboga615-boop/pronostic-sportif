"""Règlement des marchés : du score final au résultat de chaque sélection.

Sans cette étape, la table ``actual_results`` reste vide et aucune des onze
questions de la définition de réussite ne peut recevoir de réponse : on ne sait
ni si le modèle est calibré, ni s'il est rentable, ni s'il vaut mieux qu'une
stratégie naïve. Le projet produisait des prédictions sans jamais les
confronter aux résultats.

Une ligne est écrite **par sélection**, et non par marché : c'est la seule
forme qui se joigne un pour un aux prédictions, et la seule qui sache
représenter un remboursement (``push``) le jour où un marché en produira.

Les marchés de mi-temps ne sont réglés que si les scores de mi-temps sont
renseignés. Un match sans ``HTHG`` n'est pas un match nul à la pause : c'est un
match dont on ignore le score à la pause.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from app.models import ActualResult, Match
from models.market_assembly import OVER_UNDER_LINES, PUBLIC_SELECTIONS
from models.market_derivation import FIRST_HALF_LINES

GAGNE = "won"
PERDU = "lost"
REMBOURSE = "push"


def regler_match(match: Match) -> dict[tuple[str, str], str]:
    """Déterminer l'issue de chaque sélection d'un match terminé.

    Args:
        match: le match, dont les scores doivent être renseignés.

    Returns:
        ``{(marché, sélection): "won" | "lost" | "push"}``. Les marchés de
        mi-temps sont absents si les scores de mi-temps le sont.

    Raises:
        ValueError: si le score final n'est pas renseigné.
    """
    if match.home_goals is None or match.away_goals is None:
        raise ValueError(f"Match {match.id} sans score : règlement impossible")

    hg, ag = int(match.home_goals), int(match.away_goals)
    issues: dict[tuple[str, str], str] = {}

    issues.update(_regler_1n2("1N2", hg, ag))
    issues.update(_regler_double_chance("double_chance", hg, ag))
    issues.update(_regler_over_under("over_under", hg + ag, OVER_UNDER_LINES))
    issues.update(_regler_btts(hg, ag))

    if match.home_ht_goals is None or match.away_ht_goals is None:
        return issues

    h1, a1 = int(match.home_ht_goals), int(match.away_ht_goals)
    issues.update(_regler_1n2("1N2_1H", h1, a1))
    issues.update(_regler_double_chance("double_chance_1H", h1, a1))
    issues.update(_regler_over_under("over_under_1H", h1 + a1, FIRST_HALF_LINES))
    issues.update(_regler_mi_temps_prolifique(hg + ag, h1 + a1))

    return issues


def _issue(gagnante: str, selections) -> dict[str, str]:
    return {s: (GAGNE if s == gagnante else PERDU) for s in selections}


def _regler_1n2(marche: str, buts_dom: int, buts_ext: int) -> dict[tuple[str, str], str]:
    gagnante = "home" if buts_dom > buts_ext else "away" if buts_dom < buts_ext else "draw"
    return {(marche, s): issue for s, issue in _issue(gagnante, PUBLIC_SELECTIONS[marche]).items()}


def _regler_double_chance(marche: str, buts_dom: int, buts_ext: int) -> dict[tuple[str, str], str]:
    couvertures = {
        "home_or_draw": buts_dom >= buts_ext,
        "home_or_away": buts_dom != buts_ext,
        "draw_or_away": buts_dom <= buts_ext,
    }
    return {(marche, s): (GAGNE if gagne else PERDU) for s, gagne in couvertures.items()}


def _regler_over_under(marche: str, total: int, lignes) -> dict[tuple[str, str], str]:
    """Régler les lignes Over/Under.

    Les lignes sont demi-entières : le total ne peut jamais les atteindre
    exactement, il n'y a donc pas de remboursement. La comparaison stricte
    couvre malgré tout le cas d'une ligne entière, si une source en fournit
    un jour.
    """
    issues: dict[tuple[str, str], str] = {}
    for ligne in lignes:
        if total > ligne:
            issues[(marche, f"over_{ligne}")] = GAGNE
            issues[(marche, f"under_{ligne}")] = PERDU
        elif total < ligne:
            issues[(marche, f"over_{ligne}")] = PERDU
            issues[(marche, f"under_{ligne}")] = GAGNE
        else:
            issues[(marche, f"over_{ligne}")] = REMBOURSE
            issues[(marche, f"under_{ligne}")] = REMBOURSE
    return issues


def _regler_btts(buts_dom: int, buts_ext: int) -> dict[tuple[str, str], str]:
    les_deux = buts_dom > 0 and buts_ext > 0
    return {
        ("BTTS", "yes"): GAGNE if les_deux else PERDU,
        ("BTTS", "no"): PERDU if les_deux else GAGNE,
    }


def _regler_mi_temps_prolifique(
    total_match: int, total_premiere: int
) -> dict[tuple[str, str], str]:
    total_seconde = total_match - total_premiere
    if total_premiere > total_seconde:
        gagnante = "first_half"
    elif total_premiere < total_seconde:
        gagnante = "second_half"
    else:
        gagnante = "equal"
    return {
        ("most_productive_half", s): issue
        for s, issue in _issue(gagnante, PUBLIC_SELECTIONS["most_productive_half"]).items()
    }


def persister_resultats(session, match: Match) -> int:
    """Écrire ou mettre à jour les résultats réglés d'un match.

    Idempotent : deux exécutions successives laissent la base dans le même
    état. Ne commite pas ; le commit revient à l'appelant.

    Returns:
        Le nombre de lignes créées ou mises à jour.
    """
    issues = regler_match(match)
    horodatage = datetime.now(UTC)
    ecrits = 0

    existants = {
        (r.market, r.selection): r
        for r in session.query(ActualResult).filter_by(match_id=match.id).all()
    }

    for (marche, selection), issue in issues.items():
        ligne = existants.get((marche, selection))
        if ligne is None:
            session.add(
                ActualResult(
                    match_id=match.id,
                    market=marche,
                    selection=selection,
                    actual_outcome=issue,
                    settled_at=horodatage,
                )
            )
        else:
            ligne.actual_outcome = issue
            ligne.settled_at = horodatage
        ecrits += 1

    return ecrits


def regler_les_matchs_termines(session, reference_date=None) -> dict[str, Any]:
    """Régler tous les matchs joués qui ne le sont pas encore.

    Args:
        session: session SQLAlchemy.
        reference_date: si fournie, seuls les matchs antérieurs sont réglés.
            Utile pour rejouer un backtest à une date donnée.

    Returns:
        ``{"matchs_regles": int, "lignes_ecrites": int, "echecs": [...]}``
    """
    requete = session.query(Match).filter(
        Match.home_goals.isnot(None), Match.away_goals.isnot(None)
    )
    if reference_date is not None:
        requete = requete.filter(Match.match_date <= reference_date)

    matchs_regles = 0
    lignes_ecrites = 0
    echecs: list[dict[str, Any]] = []

    for match in requete.order_by(Match.match_date, Match.id).all():
        try:
            lignes_ecrites += persister_resultats(session, match)
            matchs_regles += 1
        except ValueError as erreur:
            echecs.append({"match_id": match.id, "erreur": str(erreur)})

    session.commit()
    logger.info(f"Règlement : {matchs_regles} matchs, {lignes_ecrites} lignes")
    if echecs:
        logger.warning(f"{len(echecs)} matchs non réglés")

    return {
        "matchs_regles": matchs_regles,
        "lignes_ecrites": lignes_ecrites,
        "echecs": echecs,
    }
