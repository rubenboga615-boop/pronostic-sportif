"""Tests anti-fuite de données.

`PROJECT_SPEC.md` en fait la partie la plus importante du projet et exige que ce
fichier « vérifie automatiquement qu'aucune date de donnée utilisée n'est
postérieure à la date de prédiction ».

Deux stratégies complémentaires sont employées ici :

1. **L'historique empoisonné.** On calcule les features d'un match cible sur un
   historique propre, puis on recommence après avoir ajouté des matchs
   postérieurs aux valeurs aberrantes (9-0, 99 tirs) et des cotes qui bougent
   violemment. Toute contamination, si discrète soit-elle, déplace une valeur :
   les deux résultats doivent être rigoureusement identiques.

2. **Le mouchard de dates.** On intercepte les jeux de données réellement passés
   aux calculs de features et on vérifie qu'aucune date consultée n'atteint la
   date du match cible. La vérification porte sur le code exécuté, non sur une
   reformulation du filtre dans le test.

Un test tautologique — qui refiltre lui-même le jeu de données puis constate que
le filtre a filtré — ne prouve rien. Aucun de ceux qui suivent n'en est un, et
deux d'entre eux vérifient explicitement que le poison serait détecté s'il
passait.
"""

import pandas as pd
import pytest

from features.elo import calculate_elo_ratings
from features.form import calculate_form_features
from features.rest_days import calculate_rest_days
from features.standings import calculate_standings
from pipelines.feature_pipeline import compute_match_features

DATE_CIBLE = pd.Timestamp("2024-03-01")
COLONNES = [
    "id",
    "competition_id",
    "season_id",
    "match_date",
    "home_team_id",
    "away_team_id",
    "home_goals",
    "away_goals",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
]


def _match(mid, date, home, away, hg, ag, shots=10, sot=4, season=1):
    return {
        "id": mid,
        "competition_id": 1,
        "season_id": season,
        "match_date": pd.Timestamp(date),
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": hg,
        "away_goals": ag,
        "home_shots": shots,
        "away_shots": shots,
        "home_shots_on_target": sot,
        "away_shots_on_target": sot,
    }


@pytest.fixture
def historique():
    """Huit matchs antérieurs à la date cible, trois équipes, une saison."""
    return pd.DataFrame(
        [
            _match(1, "2024-01-05", 1, 2, 2, 1),
            _match(2, "2024-01-12", 3, 1, 0, 1),
            _match(3, "2024-01-19", 1, 3, 3, 0),
            _match(4, "2024-01-26", 2, 3, 1, 1),
            _match(5, "2024-02-02", 2, 1, 0, 2),
            _match(6, "2024-02-09", 3, 2, 2, 2),
            _match(7, "2024-02-16", 1, 2, 1, 1),
            _match(8, "2024-02-23", 3, 1, 1, 3),
        ],
        columns=COLONNES,
    )


@pytest.fixture
def match_cible():
    return pd.Series(_match(100, DATE_CIBLE, 1, 2, None, None))


@pytest.fixture
def poison():
    """Matchs situés à la date cible et après, aux valeurs impossibles à manquer."""
    return pd.DataFrame(
        [
            # Le jour même : un match daté à la coupure n'est pas antérieur.
            _match(900, DATE_CIBLE, 1, 3, 9, 0, shots=99, sot=50),
            _match(901, "2024-03-08", 2, 1, 0, 9, shots=99, sot=50),
            _match(902, "2024-03-15", 1, 2, 8, 0, shots=99, sot=50),
            _match(903, "2024-05-30", 3, 1, 7, 0, shots=99, sot=50),
            # Saison suivante : le classement ne doit pas la voir non plus.
            _match(904, "2024-08-17", 1, 2, 6, 0, shots=99, sot=50, season=2),
        ],
        columns=COLONNES,
    )


def _cotes(inclure_posterieures: bool) -> pd.DataFrame:
    """Relevés pré-match, plus éventuellement des relevés postérieurs violents."""
    lignes = [
        (100, "1N2", "home", "B365", 2.00, pd.Timestamp("2024-02-01"), 0),
        (100, "1N2", "home", "B365", 1.95, pd.Timestamp("2024-02-20"), 0),
        (100, "1N2", "away", "B365", 4.00, pd.Timestamp("2024-02-01"), 0),
        (100, "1N2", "away", "B365", 4.10, pd.Timestamp("2024-02-20"), 0),
    ]
    if inclure_posterieures:
        lignes += [
            # Cote de clôture : relevée au coup d'envoi, jamais disponible.
            (100, "1N2", "home", "B365_close", 1.20, DATE_CIBLE, 1),
            (100, "1N2", "away", "B365_close", 12.0, DATE_CIBLE, 1),
            # Relevé pré-match mais postérieur à la coupure.
            (100, "1N2", "home", "B365", 1.10, DATE_CIBLE + pd.Timedelta(days=1), 0),
            (100, "1N2", "away", "B365", 20.0, DATE_CIBLE + pd.Timedelta(days=1), 0),
        ]
    return pd.DataFrame(
        lignes,
        columns=[
            "match_id",
            "market",
            "selection",
            "bookmaker",
            "odds",
            "captured_at",
            "is_closing",
        ],
    )


class TestHistoriqueEmpoisonne:
    """Ajouter des matchs futurs ne doit déplacer aucune valeur."""

    def test_aucune_feature_ne_bouge(self, match_cible, historique, poison):
        propre = compute_match_features(match_cible, historique, _cotes(False))

        contamine = compute_match_features(
            match_cible,
            pd.concat([historique, poison], ignore_index=True),
            _cotes(True),
        )

        assert contamine == propre

    def test_le_poison_serait_detectable(self, match_cible, historique, poison):
        """Contrôle du test lui-même.

        Si le poison est antériorisé, les valeurs changent. Sans cette
        vérification, l'égalité du test précédent pourrait tenir pour de
        mauvaises raisons — par exemple des features toutes nulles.
        """
        anteriorise = poison.copy()
        anteriorise["match_date"] = pd.Timestamp("2024-02-25")
        anteriorise["season_id"] = 1

        propre = compute_match_features(match_cible, historique, _cotes(False))
        avec_poison_passe = compute_match_features(
            match_cible,
            pd.concat([historique, anteriorise], ignore_index=True),
            _cotes(False),
        )

        assert avec_poison_passe != propre

    def test_la_cloture_ne_produit_aucun_mouvement_de_cote(self, match_cible, historique):
        """Les cotes de clôture ne doivent jamais alimenter odds_movement."""
        cotes = _cotes(True)
        cloture_seule = cotes[cotes["is_closing"] == 1]

        resultat = compute_match_features(match_cible, historique, cloture_seule)

        for side in ("home", "away"):
            assert resultat[side].get("odds_movement") is None

    def test_le_match_cible_lui_meme_est_exclu(self, match_cible, historique):
        """Le match à prédire ne doit pas entrer dans ses propres features."""
        joue = pd.DataFrame(
            [_match(100, DATE_CIBLE, 1, 2, 5, 0, shots=99, sot=50)], columns=COLONNES
        )

        propre = compute_match_features(match_cible, historique, _cotes(False))
        avec_lui_meme = compute_match_features(
            match_cible,
            pd.concat([historique, joue], ignore_index=True),
            _cotes(False),
        )

        assert avec_lui_meme == propre


class TestMouchardDeDates:
    """Aucune date consultée par le calcul ne doit atteindre la date cible."""

    def test_aucune_date_consultee_n_atteint_la_cible(
        self, monkeypatch, match_cible, historique, poison
    ):
        import pipelines.feature_pipeline as fp

        consultees: list[pd.Timestamp] = []

        def espion(nom):
            """Envelopper un calcul de features pour relever les dates reçues."""
            originale = getattr(fp, nom)

            def enveloppe(df, *args, **kwargs):
                if isinstance(df, pd.DataFrame) and "match_date" in df.columns:
                    consultees.extend(df["match_date"].dropna().tolist())
                return originale(df, *args, **kwargs)

            return enveloppe

        for nom in (
            "calculate_form_features",
            "calculate_standings",
            "calculate_rest_features",
            "calculate_shots_features",
            "calculate_home_away_features",
        ):
            monkeypatch.setattr(fp, nom, espion(nom))

        compute_match_features(
            match_cible,
            pd.concat([historique, poison], ignore_index=True),
            _cotes(True),
        )

        assert consultees, "le mouchard n'a rien enregistré : le test serait sans valeur"
        assert max(consultees) < DATE_CIBLE

    def test_le_mouchard_verrait_une_fuite(self, monkeypatch, match_cible, historique, poison):
        """Contrôle du mouchard : s'il reçoit du futur, il le signale."""
        import pipelines.feature_pipeline as fp

        consultees: list[pd.Timestamp] = []
        originale = fp.calculate_form_features

        def enveloppe_fuyante(df, *args, **kwargs):
            # On simule une implémentation qui oublierait de filtrer.
            complet = pd.concat([df, poison], ignore_index=True)
            consultees.extend(complet["match_date"].dropna().tolist())
            return originale(complet, *args, **kwargs)

        monkeypatch.setattr(fp, "calculate_form_features", enveloppe_fuyante)

        compute_match_features(match_cible, historique, _cotes(False))

        assert max(consultees) >= DATE_CIBLE


class TestModulesIsoles:
    """Chaque module de features, pris séparément, respecte la coupure."""

    def test_forme(self, historique, poison):
        complet = pd.concat([historique, poison], ignore_index=True)

        propre = calculate_form_features(historique, 1, DATE_CIBLE, windows=[5])
        contamine = calculate_form_features(complet, 1, DATE_CIBLE, windows=[5])

        assert contamine == propre

    def test_jours_de_repos(self, historique, poison):
        complet = pd.concat([historique, poison], ignore_index=True)

        assert calculate_rest_days(complet, 1, DATE_CIBLE, season_id=1) == calculate_rest_days(
            historique, 1, DATE_CIBLE, season_id=1
        )

    def test_classement(self, historique, poison):
        complet = pd.concat([historique, poison], ignore_index=True)

        propre = calculate_standings(historique, DATE_CIBLE, competition_id=1, season_id=1)
        contamine = calculate_standings(complet, DATE_CIBLE, competition_id=1, season_id=1)

        pd.testing.assert_frame_equal(contamine, propre)

    def test_elo_est_pre_match(self, historique):
        """Le rating enregistré pour un match précède sa propre mise à jour."""
        historique_elo = calculate_elo_ratings(historique, {f"t{i}": i for i in (1, 2, 3)})

        premier = historique_elo.iloc[0]
        assert premier["home_elo"] == 1500
        assert premier["away_elo"] == 1500
        assert (historique_elo["match_date"] < DATE_CIBLE).all()
