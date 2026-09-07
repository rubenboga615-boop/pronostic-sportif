"""Backtest chronologique du modèle de pronostic.

Trois défauts rendaient le backtest précédent inexploitable :

- le rendement était calculé contre la **cote équitable du modèle**. Parier à
  sa propre cote ne peut structurellement rien rapporter : le ROI obtenu était
  une tautologie, pas une mesure ;
- l'accuracy portait sur **toutes les sélections** d'un marché, sans retenir la
  plus probable. Sur un 1N2, elle valait mécaniquement un tiers ;
- rien n'était ventilé par championnat, par saison ni par tranche de cote,
  alors que le cahier des charges l'exige explicitement.

Le découpage reste chronologique : jamais de tirage aléatoire, et la saison en
cours n'est pas utilisée pour déclarer une rentabilité.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from loguru import logger

from evaluation.metrics import (
    accuracy,
    auc,
    brier_score,
    calibration_curve,
    erreur_de_calibration,
    log_loss,
    roi_simulation,
)
from models.market_assembly import GROUPES_EXCLUSIFS

# Tranches de cote, pour vérifier que la performance ne tient pas à un seul
# segment — un modèle rentable uniquement sur les gros outsiders est fragile.
TRANCHES_DE_COTE: tuple[tuple[str, float, float], ...] = (
    ("1.00-1.50", 1.0, 1.5),
    ("1.50-2.00", 1.5, 2.0),
    ("2.00-3.00", 2.0, 3.0),
    ("3.00-5.00", 3.0, 5.0),
    ("5.00+", 5.0, float("inf")),
)

REQUETE_EVALUATION = """
    SELECT p.match_id,
           p.model_version,
           p.market,
           p.selection,
           p.probability,
           p.fair_odds,
           p.offered_odds,
           p.edge,
           r.actual_outcome,
           m.match_date,
           m.competition_id,
           m.season_id
      FROM predictions p
      JOIN actual_results r
        ON r.match_id = p.match_id
       AND r.market = p.market
       AND r.selection = p.selection
      JOIN matches m
        ON m.id = p.match_id
"""


def chronological_split(
    matches_df: pd.DataFrame,
    train_end: str = "2022-06-30",
    val_end: str = "2023-06-30",
    test_end: str = "2024-06-30",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Découpage chronologique : entraînement, validation, test, test récent."""
    dates = pd.to_datetime(matches_df["match_date"])
    train = matches_df[dates <= train_end]
    validation = matches_df[(dates > train_end) & (dates <= val_end)]
    test = matches_df[(dates > val_end) & (dates <= test_end)]
    test_recent = matches_df[dates > test_end]

    logger.info(
        f"Split chronologique : train={len(train)}, val={len(validation)}, "
        f"test={len(test)}, test_recent={len(test_recent)}"
    )
    return train, validation, test, test_recent


def charger_evaluation(session, model_version: str | None = None) -> pd.DataFrame:
    """Joindre prédictions et résultats réglés, un pour un.

    La jointure porte sur ``(match_id, marché, sélection)`` : c'est la clé
    logique commune, et la seule qui associe chaque prédiction à son issue.
    """
    requete = REQUETE_EVALUATION
    params: dict[str, Any] = {}
    if model_version is not None:
        requete += " WHERE p.model_version = :model_version"
        params["model_version"] = model_version

    df = pd.read_sql_query(requete, session.get_bind(), params=params)
    if not df.empty:
        df["match_date"] = pd.to_datetime(df["match_date"])
        df["gagnant"] = (df["actual_outcome"] == "won").astype(int)
    return df


def evaluer_marche(df: pd.DataFrame, marche: str) -> dict[str, Any]:
    """Calculer toutes les métriques d'un marché.

    L'accuracy retient, pour chaque match, la **sélection la plus probable** —
    c'est ce que « prédire » veut dire. Les métriques probabilistes, elles,
    portent sur toutes les sélections, chacune traitée comme un événement
    binaire.

    **Une AUC ne se compare pas d'un marché à l'autre.** C'est le principal
    enseignement du diagnostic mené sur le BTTS, et il change la lecture des
    résultats.

    L'AUC d'un événement binaire dépend fortement de sa fréquence de
    réalisation : plus elle s'éloigne de 50 %, plus il est facile de bien
    classer. Mesuré par simulation depuis un modèle **parfaitement spécifié**
    — les matchs sont tirés depuis lui, l'AUC obtenue est donc le plafond
    atteignable, aucun modèle ne peut faire mieux :

    ====================================  ==========  ================
    Marché                                Plafond     Fréquence
    ====================================  ==========  ================
    Over/Under 0,5                          0,930     over 91 %
    Over/Under 1,5                          0,774     over 72 %
    Over/Under 2,5                          0,635     over 47 %
    Over/Under 3,5                          0,789     over 27 %
    Over/Under, 8 sélections confondues     0,819     —
    Over/Under, moyenne par ligne           0,782     —
    BTTS                                    0,606     ~52 %
    ====================================  ==========  ================

    D'où la conclusion, contre-intuitive : le **0,805 mesuré en over/under
    n'était pas un bon résultat**, il frôlait le plafond d'une métrique
    flatteuse ; et le **0,537 du BTTS n'a rien d'anormal** face à son propre
    plafond de 0,606. Le BTTS est simplement le marché le plus dur des trois,
    parce que sa fréquence est proche de 50 % et qu'il dépend de l'équilibre
    entre les deux λ — ce que le modèle estime le moins bien.

    Trois valeurs sont donc publiées :

    - ``auc`` — moyenne pondérée **par groupe exclusif**, comparable dans le
      temps sur un même marché ;
    - ``auc_par_groupe`` — le détail ligne par ligne, seul réellement
      interprétable ;
    - ``auc_toutes_selections`` — la valeur groupée, conservée pour la
      continuité des rapports antérieurs. **À ne jamais comparer entre marchés
      de nombres de groupes différents.**
    """
    lignes = df[df["market"] == marche]
    if lignes.empty:
        return {"marche": marche, "n_selections": 0, "erreur": "aucune donnée"}

    y_true_binaire = lignes["gagnant"].tolist()
    y_prob = lignes["probability"].tolist()

    resultat: dict[str, Any] = {
        "marche": marche,
        "n_matchs": int(lignes["match_id"].nunique()),
        "n_selections": int(len(lignes)),
        "accuracy": _accuracy_par_groupe(lignes, marche),
        "log_loss": log_loss(y_true_binaire, y_prob),
        "brier": brier_score(y_true_binaire, y_prob),
        "auc": _auc_moyenne_par_groupe(lignes, marche),
        "auc_par_groupe": _auc_par_groupe(lignes, marche),
        "auc_toutes_selections": auc(y_true_binaire, y_prob),
        "erreur_de_calibration": erreur_de_calibration(y_true_binaire, y_prob),
        "courbe_de_calibration": [
            {"annoncee": p, "observee": o, "effectif": n}
            for p, o, n in calibration_curve(y_true_binaire, y_prob)
        ],
    }
    resultat.update(_rendements(lignes))
    return resultat


def _accuracy_par_groupe(lignes: pd.DataFrame, marche: str) -> float | None:
    """Accuracy calculée sur chaque groupe de sélections exclusives.

    Retourne ``None`` pour un marché sans partition — la double chance, où
    deux sélections sur trois gagnent à chaque match : y mesurer une accuracy
    n'aurait pas de sens.
    """
    groupes = GROUPES_EXCLUSIFS.get(marche, ())
    if not groupes:
        return None

    attendus: list[str] = []
    predits: list[str] = []
    for groupe in groupes:
        sous_ensemble = lignes[lignes["selection"].isin(groupe)]
        if sous_ensemble.empty:
            continue
        favorites = sous_ensemble.loc[sous_ensemble.groupby("match_id")["probability"].idxmax()]
        gagnantes = sous_ensemble[sous_ensemble["actual_outcome"] == "won"]
        reel = dict(zip(gagnantes["match_id"], gagnantes["selection"], strict=False))
        predit = dict(zip(favorites["match_id"], favorites["selection"], strict=False))
        for match_id in sorted(set(reel) & set(predit)):
            attendus.append(reel[match_id])
            predits.append(predit[match_id])

    return accuracy(attendus, predits) if attendus else None


def _auc_par_groupe(lignes: pd.DataFrame, marche: str) -> dict[str, float] | None:
    """AUC de chaque groupe de sélections exclusives, séparément.

    Un groupe — une ligne over/under, le triplet 1N2 — partage une même
    fréquence de réalisation. L'AUC y mesure un pouvoir de classement réel, et
    non l'écart de fréquence entre deux lignes.

    Retourne ``None`` pour un marché sans partition, la double chance, comme
    :func:`_accuracy_par_groupe`.
    """
    groupes = GROUPES_EXCLUSIFS.get(marche, ())
    if not groupes:
        return None

    resultats: dict[str, float] = {}
    for groupe in groupes:
        sous_ensemble = lignes[lignes["selection"].isin(groupe)]
        if sous_ensemble.empty:
            continue
        issues = sous_ensemble["gagnant"].tolist()
        if len(set(issues)) < 2:
            continue  # une seule issue observée : l'AUC n'est pas définie
        resultats[" / ".join(groupe)] = auc(issues, sous_ensemble["probability"].tolist())

    return resultats or None


def _auc_moyenne_par_groupe(lignes: pd.DataFrame, marche: str) -> float | None:
    """Moyenne des AUC par groupe, pondérée par l'effectif de chaque groupe."""
    par_groupe = _auc_par_groupe(lignes, marche)
    if not par_groupe:
        return None

    total = 0.0
    effectif = 0
    for groupe in GROUPES_EXCLUSIFS.get(marche, ()):
        cle = " / ".join(groupe)
        if cle not in par_groupe:
            continue
        n = len(lignes[lignes["selection"].isin(groupe)])
        total += par_groupe[cle] * n
        effectif += n

    return total / effectif if effectif else None


def _rendements(lignes: pd.DataFrame, edge_minimal: float = 0.0) -> dict[str, Any]:
    """Rendement du marché, et sa ventilation par tranche de cote."""
    pariables = lignes[lignes["offered_odds"].notna() & (lignes["offered_odds"] > 1.0)]
    if edge_minimal:
        pariables = pariables[pariables["edge"].notna() & (pariables["edge"] >= edge_minimal)]

    if pariables.empty:
        return {"rendement": None, "rendement_par_tranche_de_cote": {}}

    global_ = roi_simulation(pariables["actual_outcome"], pariables["offered_odds"])

    par_tranche = {}
    for libelle, borne_basse, borne_haute in TRANCHES_DE_COTE:
        tranche = pariables[
            (pariables["offered_odds"] >= borne_basse) & (pariables["offered_odds"] < borne_haute)
        ]
        if not tranche.empty:
            par_tranche[libelle] = roi_simulation(
                tranche["actual_outcome"], tranche["offered_odds"]
            )

    return {"rendement": global_, "rendement_par_tranche_de_cote": par_tranche}


def strategie_edge(
    df: pd.DataFrame,
    edge_minimal: float = 0.05,
    cote_minimale: float = 1.2,
    cote_maximale: float = 10.0,
) -> dict[str, Any]:
    """Rendement d'une stratégie ne pariant que sur un avantage estimé.

    C'est la seule stratégie qui puisse être rentable : parier sur tout, y
    compris quand le marché est mieux informé, ne fait que payer la marge des
    bookmakers.
    """
    retenus = df[
        df["edge"].notna()
        & (df["edge"] >= edge_minimal)
        & df["offered_odds"].notna()
        & (df["offered_odds"] >= cote_minimale)
        & (df["offered_odds"] <= cote_maximale)
    ]
    if retenus.empty:
        return {"paris": 0, "edge_minimal": edge_minimal, "rendement": None}

    return {
        "edge_minimal": edge_minimal,
        "plage_de_cotes": [cote_minimale, cote_maximale],
        "rendement": roi_simulation(retenus["actual_outcome"], retenus["offered_odds"]),
    }


def strategie_naive(df: pd.DataFrame, selection: str = "home") -> dict[str, Any]:
    """Référence naïve : parier systématiquement la même sélection en 1N2.

    Le cahier des charges demande explicitement cette comparaison. Un modèle
    qui ne bat pas « toujours le domicile » n'apporte rien.
    """
    lignes = df[(df["market"] == "1N2") & (df["selection"] == selection)]
    lignes = lignes[lignes["offered_odds"].notna() & (lignes["offered_odds"] > 1.0)]
    if lignes.empty:
        return {"selection": selection, "rendement": None}

    return {
        "selection": selection,
        "taux_de_reussite": float(lignes["gagnant"].mean()),
        "rendement": roi_simulation(lignes["actual_outcome"], lignes["offered_odds"]),
    }


def strategie_marche(df: pd.DataFrame) -> dict[str, Any]:
    """Référence de marché : suivre le favori des bookmakers en 1N2.

    Répond à la question « quelle est la performance avec le marché comme
    référence ? » : c'est la barre à franchir, pas une stratégie à imiter.
    """
    lignes = df[(df["market"] == "1N2") & df["offered_odds"].notna()]
    if lignes.empty:
        return {"rendement": None}

    favoris = lignes.loc[lignes.groupby("match_id")["offered_odds"].idxmin()]
    return {
        "taux_de_reussite": float(favoris["gagnant"].mean()),
        "rendement": roi_simulation(favoris["actual_outcome"], favoris["offered_odds"]),
    }


def run_backtest(df: pd.DataFrame, marches: list[str] | None = None) -> dict[str, Any]:
    """Backtest complet, ventilé comme le demande le cahier des charges.

    Args:
        df: sortie de :func:`charger_evaluation`.
        marches: marchés à évaluer ; tous ceux présents par défaut.

    Returns:
        Métriques par marché, par championnat, par saison, plus les stratégies
        de référence.
    """
    if df.empty:
        return {"erreur": "aucune prédiction réglée à évaluer"}

    marches = marches or sorted(df["market"].unique())

    rapport: dict[str, Any] = {
        "periode": {
            "debut": str(df["match_date"].min().date()),
            "fin": str(df["match_date"].max().date()),
        },
        "n_matchs": int(df["match_id"].nunique()),
        "n_selections": int(len(df)),
        "par_marche": {marche: evaluer_marche(df, marche) for marche in marches},
        "par_championnat": {},
        "par_saison": {},
        "strategies": {
            "edge_5pct": strategie_edge(df, edge_minimal=0.05),
            "edge_2pct": strategie_edge(df, edge_minimal=0.02),
            "naive_domicile": strategie_naive(df, "home"),
            "favori_du_marche": strategie_marche(df),
        },
    }

    for competition_id, groupe in df.groupby("competition_id"):
        rapport["par_championnat"][str(competition_id)] = {
            "n_matchs": int(groupe["match_id"].nunique()),
            "1N2": evaluer_marche(groupe, "1N2"),
        }
    for season_id, groupe in df.groupby("season_id"):
        rapport["par_saison"][str(season_id)] = {
            "n_matchs": int(groupe["match_id"].nunique()),
            "1N2": evaluer_marche(groupe, "1N2"),
        }

    return rapport
