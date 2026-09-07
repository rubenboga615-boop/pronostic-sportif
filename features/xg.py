"""Calcul des features xG (Expected Goals).

Le xG mesure la qualité des occasions plutôt que leur issue. Sur cinq matchs,
il décrit une équipe plus fidèlement que les buts marqués, qui restent très
bruités — c'est la raison d'être des trois colonnes `xg_avg_5`, `xga_avg_5` et
`npxg_avg_5`, restées nulles depuis le premier jour faute de source.

Anti-fuite : la date qui compte est celle du **match**
-----------------------------------------------------
Ce module comparait auparavant `retrieved_at`, l'instant où la donnée a été
collectée, à la date du match cible. C'est faux dans les deux sens :

- une collecte faite aujourd'hui porte l'horodatage du jour, si bien qu'aucun
  match passé ne franchissait le filtre — les features restaient vides même une
  fois la source disponible ;
- inversement, une collecte ancienne aurait laissé passer les xG d'un match
  postérieur à la cible, c'est-à-dire une fuite pure.

Seule la date du match dit ce qui était connaissable au moment de prédire. La
colonne `match_date` est donc obligatoire dans les données reçues.

La fenêtre porte sur les matchs JOUÉS, pas sur les matchs couverts
-----------------------------------------------------------------
C'est la règle la plus importante de ce module, et celle qui manquait. Prendre
les cinq derniers matchs **pour lesquels un xG existe** revient à décrire une
équipe par ses cinq premières journées si la source s'arrête là — en présentant
le résultat comme sa forme du moment. Mesuré le 07/09/2026 : sur 2024/25, dont
la source ne couvrait que les 59 premiers matchs, l'âge médian du xG utilisé
atteignait 108 jours, et 72 % des lignes dépassaient 60 jours.

La fenêtre est donc prise sur les matchs que l'équipe a **réellement joués**,
et la valeur n'est produite que si ces matchs-là sont couverts. Une couverture
partielle donne `None` plutôt qu'un chiffre périmé.

Ce choix évite un seuil d'ancienneté arbitraire — pourquoi soixante jours et
non quarante-cinq ? — et se corrige seul : le jour où la source est complétée,
les valeurs réapparaissent sans qu'on retouche à quoi que ce soit.

Bornage à la saison
-------------------
Comme la forme et les variables de mi-temps, ces moyennes sont bornées à la
saison en cours. Sans cette borne, un match de mai 2026 recevait un « xG moyen
sur cinq matchs » calculé sur des rencontres de septembre 2024 — la source
n'allant pas plus loin. La feature annonçait une forme récente et livrait le
vestige d'une saison révolue : ce n'est pas une fuite, mais le modèle
apprendrait à lui accorder un sens qu'elle n'a pas.
"""

import pandas as pd

COLONNES_XG = ("xg_avg_5", "xga_avg_5", "npxg_avg_5")

# En dessous, une moyenne ne décrit rien : deux matchs peuvent être deux
# valeurs aberrantes. Mieux vaut None qu'un chiffre auquel on croirait.
MINIMUM_DE_MATCHS = 2


def _vide() -> dict:
    return dict.fromkeys(COLONNES_XG)


def _fenetre_jouee(
    matchs_joues: pd.DataFrame,
    match_date: pd.Timestamp,
    season_id: object,
    window: int,
) -> set:
    """Identifiants des `window` derniers matchs joués avant la cible.

    C'est cette liste qui définit la fenêtre — pas les matchs dont on possède
    le xG. Un match joué mais non couvert consomme donc une place, et fait
    baisser le nombre d'observations disponibles jusqu'à passer sous le
    minimum : c'est exactement l'effet recherché.
    """
    joues = matchs_joues[pd.to_datetime(matchs_joues["match_date"]) < pd.Timestamp(match_date)]
    if season_id is not None and "season_id" in joues.columns:
        joues = joues[joues["season_id"] == season_id]
    return set(joues.sort_values("match_date").tail(window)["id"])


def calculate_xg_features(
    xg_data: pd.DataFrame,
    team_id: int,
    match_date: pd.Timestamp,
    season_id: object = None,
    window: int = 5,
    matchs_joues: pd.DataFrame | None = None,
) -> dict:
    """Moyennes de xG d'une équipe sur ses `window` derniers matchs.

    Args:
        xg_data: lignes de `xg_match_stats` jointes à la date de leur match.
            Colonnes attendues : ``team_id``, ``match_date``, ``xg``, ``xga``,
            et ``npxg`` si disponible.
        team_id: l'équipe décrite.
        match_date: date du match à prédire. Seuls les matchs **strictement
            antérieurs** sont pris en compte.
        season_id: saison du match. Fournie, elle borne la fenêtre : une
            moyenne à cheval sur la trêve décrit un effectif qui n'existe plus.
        window: nombre de matchs retenus.
        matchs_joues: historique des matchs **joués** par l'équipe, avec les
            colonnes ``id``, ``match_date`` et ``season_id``. Fourni, il définit
            la fenêtre : seuls les xG de ces matchs-là comptent, et une
            couverture insuffisante donne ``None``. Le pipeline le fournit
            toujours ; son absence retombe sur les derniers xG connus, ce qui
            ne convient qu'à une source complète.

    Returns:
        Les trois moyennes, ou ``None`` chacune si l'historique est trop court.
        Jamais 0.0 : une absence de donnée n'est pas une performance nulle.
    """
    if xg_data is None or xg_data.empty:
        return _vide()
    if "match_date" not in xg_data.columns:
        raise KeyError(
            "xg_data doit porter une colonne 'match_date' : filtrer sur la date "
            "de collecte laisserait passer des matchs postérieurs à la cible."
        )

    dates = pd.to_datetime(xg_data["match_date"])
    equipe = xg_data[(xg_data["team_id"] == team_id) & (dates < pd.Timestamp(match_date))].assign(
        _date=dates
    )
    if season_id is not None and "season_id" in equipe.columns:
        equipe = equipe[equipe["season_id"] == season_id]

    if matchs_joues is not None and not matchs_joues.empty and "match_id" in equipe.columns:
        equipe = equipe[
            equipe["match_id"].isin(_fenetre_jouee(matchs_joues, match_date, season_id, window))
        ]
    else:
        equipe = equipe.sort_values("_date").tail(window)

    if len(equipe) < MINIMUM_DE_MATCHS:
        return _vide()

    return {
        "xg_avg_5": equipe["xg"].mean(),
        "xga_avg_5": equipe["xga"].mean(),
        "npxg_avg_5": equipe["npxg"].mean() if "npxg" in equipe.columns else None,
    }
