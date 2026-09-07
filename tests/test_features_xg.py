"""Tests des features xG.

Le défaut corrigé ici (repère `M6` de la feuille de route) était silencieux
dans les deux sens : le filtre comparait `retrieved_at`, la date de collecte,
à la date du match cible. Une collecte faite aujourd'hui écartait donc tout
l'historique — les colonnes restaient vides alors que la source existait — et
une collecte ancienne aurait au contraire laissé entrer les xG d'un match
postérieur, c'est-à-dire le résultat qu'on cherche à prédire.
"""

from __future__ import annotations

import pandas as pd
import pytest

# Importé ici, et non dans les tests : le conftest crée les tables depuis
# `Base.metadata`, qui doit connaître tous les modèles avant son premier
# `create_all`. Un import tardif ferait échouer le nettoyage de fin de test.
import pipelines.feature_pipeline as pipeline
from features.xg import calculate_xg_features


def _xg(lignes: list[tuple[int, str, float, float, float]], saison: int = 1) -> pd.DataFrame:
    """(team_id, date du match, xg, xga, npxg) -> tableau prêt à filtrer."""
    return pd.DataFrame(
        [
            {
                "match_id": i,
                "team_id": t,
                "match_date": pd.Timestamp(d),
                "xg": g,
                "xga": a,
                "npxg": n,
                "season_id": saison,
            }
            for i, (t, d, g, a, n) in enumerate(lignes, start=1)
        ]
    )


class TestAntiFuite:
    def test_les_matchs_posterieurs_sont_exclus(self):
        """Le coeur du correctif : jamais de xG postérieur à la cible."""
        donnees = _xg(
            [
                (1, "2024-01-01", 1.0, 0.5, 1.0),
                (1, "2024-01-08", 1.0, 0.5, 1.0),
                (1, "2024-02-01", 9.0, 9.0, 9.0),  # après la cible
            ]
        )

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2024-01-15"))

        assert resultat["xg_avg_5"] == 1.0, "un match postérieur a été utilisé"

    def test_un_match_le_jour_meme_est_exclu(self):
        """« Strictement antérieur » : le match à prédire ne se décrit pas
        lui-même, et deux matchs du même jour ne s'informent pas."""
        donnees = _xg(
            [
                (1, "2024-01-01", 1.0, 1.0, 1.0),
                (1, "2024-01-08", 1.0, 1.0, 1.0),
                (1, "2024-01-15", 5.0, 5.0, 5.0),
            ]
        )

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2024-01-15"))

        assert resultat["xg_avg_5"] == 1.0

    def test_la_date_de_collecte_n_est_plus_consultee(self):
        """Une collecte postérieure à tous les matchs — le cas réel d'un
        import fait aujourd'hui — ne doit plus vider le résultat."""
        donnees = _xg([(1, "2023-08-12", 2.0, 1.0, 2.0), (1, "2023-08-19", 3.0, 1.0, 3.0)])
        donnees["retrieved_at"] = pd.Timestamp("2026-09-07")

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2023-09-01"))

        assert resultat["xg_avg_5"] == 2.5

    def test_l_absence_de_date_de_match_leve(self):
        """Sans `match_date`, le filtre ne peut pas être correct : il vaut
        mieux échouer que retomber sur la date de collecte."""
        donnees = pd.DataFrame(
            [{"team_id": 1, "retrieved_at": pd.Timestamp("2024-01-01"), "xg": 1.0, "xga": 1.0}]
        )

        with pytest.raises(KeyError):
            calculate_xg_features(donnees, 1, pd.Timestamp("2024-02-01"))


def _joues(dates: list[str], saison: int = 1, depart: int = 1) -> pd.DataFrame:
    """Matchs réellement joués par l'équipe : (id, date, saison)."""
    return pd.DataFrame(
        [
            {"id": i, "match_date": pd.Timestamp(d), "season_id": saison}
            for i, d in enumerate(dates, start=depart)
        ]
    )


class TestFenetreSurLesMatchsJoues:
    """La fenêtre porte sur les matchs joués, pas sur ceux qui ont un xG.

    Mesuré le 07/09/2026 : la source s'arrêtant au 29/09/2024, un match de
    mai 2025 recevait la moyenne des cinq premières journées de la saison —
    108 jours d'ancienneté médiane, 72 % des lignes au-delà de 60 jours.
    """

    def test_une_couverture_trop_ancienne_ne_produit_rien(self):
        """Le cas réel : deux matchs couverts en août, dix joués depuis."""
        xg = _xg([(1, "2024-08-17", 2.0, 1.0, 2.0), (1, "2024-08-24", 3.0, 1.0, 3.0)])
        joues = _joues(
            [
                "2024-08-17",
                "2024-08-24",
                "2024-09-14",
                "2024-09-21",
                "2024-09-28",
                "2024-10-05",
                "2025-05-01",
            ]
        )

        resultat = calculate_xg_features(
            xg, 1, pd.Timestamp("2025-05-10"), season_id=1, matchs_joues=joues
        )

        assert resultat["xg_avg_5"] is None

    def test_une_couverture_a_jour_produit_la_valeur(self):
        """Même source, mais les matchs couverts SONT les derniers joués."""
        xg = _xg([(1, "2024-08-17", 2.0, 1.0, 2.0), (1, "2024-08-24", 4.0, 1.0, 4.0)])
        joues = _joues(["2024-08-17", "2024-08-24"])

        resultat = calculate_xg_features(
            xg, 1, pd.Timestamp("2024-08-31"), season_id=1, matchs_joues=joues
        )

        assert resultat["xg_avg_5"] == 3.0

    def test_un_match_joue_non_couvert_consomme_une_place(self):
        """Trois joués, deux couverts : la fenêtre de 3 en retient deux, ce qui
        atteint tout juste le minimum."""
        xg = _xg([(1, "2024-09-01", 1.0, 1.0, 1.0), (1, "2024-09-15", 3.0, 1.0, 3.0)])
        joues = _joues(["2024-09-01", "2024-09-08", "2024-09-15"])

        resultat = calculate_xg_features(
            xg, 1, pd.Timestamp("2024-09-22"), season_id=1, window=3, matchs_joues=joues
        )

        assert resultat["xg_avg_5"] == 2.0

    def test_un_seul_couvert_dans_la_fenetre_ne_suffit_pas(self):
        xg = _xg([(1, "2024-09-01", 1.0, 1.0, 1.0), (1, "2024-09-15", 3.0, 1.0, 3.0)])
        joues = _joues(["2024-09-15", "2024-09-22", "2024-09-29"], depart=2)

        resultat = calculate_xg_features(
            xg, 1, pd.Timestamp("2024-10-06"), season_id=1, window=3, matchs_joues=joues
        )

        assert resultat["xg_avg_5"] is None

    def test_l_anti_fuite_tient_toujours(self):
        """La fenêtre ne doit pas rouvrir la porte aux matchs postérieurs."""
        xg = _xg(
            [
                (1, "2024-09-01", 1.0, 1.0, 1.0),
                (1, "2024-09-08", 1.0, 1.0, 1.0),
                (1, "2024-10-01", 9.0, 9.0, 9.0),
            ]
        )
        joues = _joues(["2024-09-01", "2024-09-08", "2024-10-01"])

        resultat = calculate_xg_features(
            xg, 1, pd.Timestamp("2024-09-15"), season_id=1, matchs_joues=joues
        )

        assert resultat["xg_avg_5"] == 1.0

    def test_sans_historique_le_comportement_precedent_demeure(self):
        """Rétrocompatibilité : sans `matchs_joues`, on retombe sur les
        derniers xG connus — ce qui ne convient qu'à une source complète."""
        xg = _xg([(1, "2024-09-01", 2.0, 1.0, 2.0), (1, "2024-09-08", 4.0, 1.0, 4.0)])

        assert calculate_xg_features(xg, 1, pd.Timestamp("2025-05-01"))["xg_avg_5"] == 3.0


class TestBornageALaSaison:
    """Constaté le 07/09/2026 sur les données réelles : un match du 24 mai 2026
    recevait un « xG moyen sur cinq matchs » calculé sur des rencontres de
    septembre 2024, dernier point couvert par la source. Ce n'est pas une fuite
    — ces matchs sont antérieurs — mais la feature annonce une forme récente et
    livre le vestige d'une saison révolue."""

    def test_la_saison_precedente_est_exclue(self):
        donnees = pd.concat(
            [
                _xg(
                    [(1, "2024-09-01", 5.0, 5.0, 5.0), (1, "2024-09-15", 5.0, 5.0, 5.0)],
                    saison=1,
                ),
                _xg(
                    [(1, "2026-05-01", 1.0, 1.0, 1.0), (1, "2026-05-10", 2.0, 2.0, 2.0)],
                    saison=2,
                ),
            ]
        )

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2026-05-24"), season_id=2)

        assert resultat["xg_avg_5"] == 1.5, "des matchs d'une autre saison sont entrés"

    def test_sans_historique_dans_la_saison_le_resultat_est_nul(self):
        """Mieux vaut une colonne vide qu'une moyenne vieille de vingt mois."""
        donnees = _xg(
            [(1, "2024-09-01", 5.0, 5.0, 5.0), (1, "2024-09-15", 5.0, 5.0, 5.0)], saison=1
        )

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2026-05-24"), season_id=2)

        assert resultat["xg_avg_5"] is None

    def test_sans_saison_fournie_le_comportement_est_inchange(self):
        """Le bornage est optionnel : les appels sans saison restent valides."""
        donnees = _xg([(1, "2024-01-01", 2.0, 1.0, 2.0), (1, "2024-01-08", 4.0, 1.0, 4.0)])

        assert calculate_xg_features(donnees, 1, pd.Timestamp("2024-02-01"))["xg_avg_5"] == 3.0


class TestCalcul:
    def test_la_moyenne_porte_sur_la_fenetre(self):
        donnees = _xg(
            [
                (1, "2024-01-01", 1.0, 1.0, 1.0),
                (1, "2024-01-08", 2.0, 2.0, 2.0),
                (1, "2024-01-15", 3.0, 3.0, 3.0),
            ]
        )

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2024-02-01"), window=2)

        assert resultat["xg_avg_5"] == 2.5, "la fenêtre doit garder les plus récents"

    def test_les_autres_equipes_sont_ignorees(self):
        donnees = _xg(
            [
                (1, "2024-01-01", 1.0, 1.0, 1.0),
                (1, "2024-01-08", 1.0, 1.0, 1.0),
                (2, "2024-01-08", 9.0, 9.0, 9.0),
            ]
        )

        assert calculate_xg_features(donnees, 1, pd.Timestamp("2024-02-01"))["xg_avg_5"] == 1.0

    def test_un_historique_trop_court_ne_produit_pas_de_chiffre(self):
        """Une moyenne sur un seul match n'est pas une moyenne, et 0.0 se
        lirait comme une équipe sans occasion."""
        donnees = _xg([(1, "2024-01-01", 1.0, 1.0, 1.0)])

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2024-02-01"))

        assert resultat == {"xg_avg_5": None, "xga_avg_5": None, "npxg_avg_5": None}

    def test_des_donnees_vides_donnent_des_colonnes_nulles(self):
        resultat = calculate_xg_features(pd.DataFrame(), 1, pd.Timestamp("2024-01-01"))

        assert set(resultat) == {"xg_avg_5", "xga_avg_5", "npxg_avg_5"}
        assert all(v is None for v in resultat.values())

    def test_le_npxg_absent_reste_nul_sans_bloquer_le_reste(self):
        donnees = _xg([(1, "2024-01-01", 2.0, 1.0, 0.0), (1, "2024-01-08", 4.0, 1.0, 0.0)])
        donnees = donnees.drop(columns=["npxg"])

        resultat = calculate_xg_features(donnees, 1, pd.Timestamp("2024-02-01"))

        assert resultat["xg_avg_5"] == 3.0
        assert resultat["npxg_avg_5"] is None


class TestBranchementDansLePipeline:
    """Le module existait et n'était appelé nulle part : les colonnes
    restaient vides même une fois `xg_match_stats` peuplée."""

    def test_le_pipeline_appelle_bien_le_calcul(self):
        import inspect

        source = inspect.getsource(pipeline)
        assert "calculate_xg_features" in source

    def test_les_colonnes_xg_sortent_du_calcul_de_match(self):
        match = pd.Series(
            {
                "id": 10,
                "competition_id": 1,
                "season_id": 1,
                "match_date": pd.Timestamp("2024-02-01"),
                "home_team_id": 1,
                "away_team_id": 2,
                "home_goals": 1,
                "away_goals": 0,
            }
        )
        xg_par_equipe = {
            1: _xg([(1, "2024-01-01", 2.0, 1.0, 2.0), (1, "2024-01-08", 4.0, 1.0, 4.0)]),
        }

        colonnes = pipeline.compute_match_features(
            match,
            pd.DataFrame(),
            pd.DataFrame(columns=["match_id", "market", "selection", "odds", "captured_at"]),
            xg_par_equipe=xg_par_equipe,
        )

        assert colonnes["home"]["xg_avg_5"] == 3.0
        # L'équipe 2 n'a aucun xG : la colonne reste nulle, jamais 0.0.
        assert colonnes["away"]["xg_avg_5"] is None
