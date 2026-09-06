"""Tests du modèle Dixon-Coles.

La version précédente n'entraînait rien : elle retournait les moyennes de buts
à domicile et à l'extérieur de tout le jeu de données, identiques pour toutes
les équipes, et n'appelait jamais la log-vraisemblance qu'elle définissait.

Le critère retenu ici est la récupération de paramètres connus : on simule des
matchs depuis un modèle dont on fixe l'avantage du terrain, le rho et les
forces d'équipe, puis on vérifie que l'ajustement les retrouve. Un test qui se
contenterait de constater qu'une valeur est retournée n'aurait rien détecté du
défaut précédent.
"""

import numpy as np
import pandas as pd
import pytest

from models.dixon_coles import (
    RHO_MAX,
    DixonColesModel,
    fit_dixon_coles,
    fit_par_competition,
    score_matrix_from_lambdas,
    tau,
)

AVANTAGE_TERRAIN = 0.28
RHO = -0.12


def _simuler(
    n_teams=10,
    tours=12,
    graine=7,
    home_adv=AVANTAGE_TERRAIN,
    rho=RHO,
    competition_id=1,
    depart="2020-01-01",
):
    """Simuler un championnat depuis un modèle Dixon-Coles de paramètres connus."""
    rng = np.random.default_rng(graine)
    attack = rng.normal(0, 0.30, n_teams)
    attack -= attack.mean()
    defense = rng.normal(0, 0.25, n_teams)

    lignes = []
    mid = 0
    for _ in range(tours):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                lam = float(np.exp(home_adv + attack[i] - defense[j]))
                mu = float(np.exp(attack[j] - defense[i]))
                matrice = score_matrix_from_lambdas(lam, mu, rho, max_goals=10)
                tirage = rng.choice(matrice.size, p=matrice.ravel() / matrice.sum())
                hg, ag = divmod(int(tirage), matrice.shape[1])
                lignes.append(
                    {
                        "id": mid,
                        "competition_id": competition_id,
                        "season_id": 1,
                        "match_date": pd.Timestamp(depart) + pd.Timedelta(days=mid // 5),
                        "home_team_id": i,
                        "away_team_id": j,
                        "home_goals": hg,
                        "away_goals": ag,
                    }
                )
                mid += 1
    return pd.DataFrame(lignes), attack, defense


@pytest.fixture(scope="module")
def simulation():
    return _simuler()


class TestRecuperationDesParametres:
    """Le modèle doit retrouver les paramètres qui ont engendré les données."""

    def test_avantage_du_terrain(self, simulation):
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        assert modele.converged
        assert modele.home_advantage == pytest.approx(AVANTAGE_TERRAIN, abs=0.08)

    def test_rho(self, simulation):
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        assert modele.rho == pytest.approx(RHO, abs=0.08)
        assert modele.rho < 0  # signe attendu sur des données de football

    def test_forces_d_equipe(self, simulation):
        df, attack, defense = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        estimees_a = np.array([modele.attack[i] for i in range(len(attack))])
        estimees_d = np.array([modele.defense[i] for i in range(len(defense))])

        assert np.corrcoef(estimees_a, attack)[0, 1] > 0.85
        assert np.corrcoef(estimees_d, defense)[0, 1] > 0.85

    def test_les_forces_ne_sont_pas_toutes_identiques(self, simulation):
        """C'était le défaut de la version précédente : un seul lambda pour tous."""
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        assert np.std(list(modele.attack.values())) > 0.1

    def test_somme_des_attaques_nulle(self, simulation):
        """Contrainte d'identifiabilité, sans laquelle les forces n'ont pas de sens."""
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        assert sum(modele.attack.values()) == pytest.approx(0.0, abs=1e-6)


class TestPredictions:
    def test_la_meilleure_attaque_produit_plus_de_buts(self, simulation):
        df, attack, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)
        meilleure = int(np.argmax(attack))
        pire = int(np.argmin(attack))
        adversaire = int(np.argsort(attack)[len(attack) // 2])

        lam_forte, _ = modele.lambdas(meilleure, adversaire)
        lam_faible, _ = modele.lambdas(pire, adversaire)

        assert lam_forte > lam_faible

    def test_l_avantage_du_terrain_joue(self, simulation):
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        lam_dom, mu_ext = modele.lambdas(0, 1)
        lam_inverse, mu_inverse = modele.lambdas(1, 0)

        # La même affiche inversée doit favoriser l'autre équipe.
        assert lam_dom > mu_inverse
        assert lam_inverse > mu_ext

    def test_equipe_inconnue_traitee_comme_moyenne(self, simulation):
        """Une promue absente de l'entraînement ne doit pas faire échouer la prédiction."""
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        lam, mu = modele.lambdas(9999, 0)

        assert lam > 0 and mu > 0
        assert np.isfinite(lam) and np.isfinite(mu)

    def test_matrice_de_scores_normalisee(self, simulation):
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        matrice = modele.score_matrix(0, 1, max_goals=8)

        assert matrice.sum() == pytest.approx(1.0, abs=1e-12)
        assert (matrice >= 0).all()


class TestCorrectionDesScoresSerres:
    def test_tau_ne_touche_que_les_quatre_scores_serres(self):
        rho = -0.15
        for x in range(4):
            for y in range(4):
                correction = float(tau(x, y, 1.4, 1.1, rho))
                if (x, y) in {(0, 0), (0, 1), (1, 0), (1, 1)}:
                    assert correction != 1.0
                else:
                    assert correction == 1.0

    def test_rho_negatif_augmente_le_nul_serre(self):
        """Un rho négatif rehausse le 1-1, que le Poisson indépendant sous-estime."""
        sans = score_matrix_from_lambdas(1.4, 1.1, 0.0, max_goals=8)
        avec = score_matrix_from_lambdas(1.4, 1.1, -0.15, max_goals=8)

        assert avec[1][1] > sans[1][1]

    def test_rho_nul_redonne_le_poisson_independant(self):
        from models.poisson import compute_score_matrix

        dixon = score_matrix_from_lambdas(1.6, 1.2, 0.0, max_goals=8)
        poisson_seul = compute_score_matrix(1.6, 1.2, max_goals=8)

        np.testing.assert_allclose(dixon, poisson_seul, atol=1e-12)

    def test_rho_reste_dans_ses_bornes(self, simulation):
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        assert -RHO_MAX <= modele.rho <= RHO_MAX


class TestPonderationTemporelle:
    def test_les_matchs_recents_pesent_davantage(self):
        """Une équipe transformée en cours de route doit être jugée sur sa forme récente."""
        lignes = []
        for i in range(200):
            ancien = i < 100
            lignes.append(
                {
                    "id": i,
                    "competition_id": 1,
                    "match_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i * 7),
                    "home_team_id": 0 if ancien else 1,
                    "away_team_id": 1 if ancien else 0,
                    # Équipe 0 dominante au début, dominée ensuite.
                    "home_goals": 4 if ancien else 4,
                    "away_goals": 0,
                }
            )
        df = pd.DataFrame(lignes)

        sans_ponderation = fit_dixon_coles(df, xi=0.0)
        avec_ponderation = fit_dixon_coles(df, xi=0.01)

        # Avec pondération, l'équipe 1 — dominante récemment — passe devant.
        ecart_sans = sans_ponderation.attack[0] - sans_ponderation.attack[1]
        ecart_avec = avec_ponderation.attack[0] - avec_ponderation.attack[1]
        assert ecart_avec < ecart_sans

    def test_date_de_reference_explicite(self, simulation):
        """L'ajustement ne doit pas dépendre du moment où il est lancé."""
        df, _, _ = simulation
        reference = pd.Timestamp("2021-06-30")

        premier = fit_dixon_coles(df, xi=0.002, reference_date=reference)
        second = fit_dixon_coles(df, xi=0.002, reference_date=reference)

        assert premier.home_advantage == pytest.approx(second.home_advantage)
        assert premier.rho == pytest.approx(second.rho)


class TestQualiteDAjustement:
    def test_meilleure_vraisemblance_que_le_poisson_sans_forces(self, simulation):
        """Le modèle ajusté doit expliquer les données mieux qu'un lambda unique."""
        from scipy.stats import poisson as loi_poisson

        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        lam_moyen = df["home_goals"].mean()
        mu_moyen = df["away_goals"].mean()
        ll_naif = float(
            np.sum(loi_poisson.logpmf(df["home_goals"], lam_moyen))
            + np.sum(loi_poisson.logpmf(df["away_goals"], mu_moyen))
        )

        assert modele.log_likelihood > ll_naif


class TestSerialisation:
    def test_aller_retour(self, simulation):
        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0, competition_id=1)

        rejoue = DixonColesModel.from_dict(modele.to_dict())

        assert rejoue.home_advantage == pytest.approx(modele.home_advantage)
        assert rejoue.rho == pytest.approx(modele.rho)
        assert rejoue.attack == pytest.approx(modele.attack)
        assert rejoue.lambdas(0, 1) == pytest.approx(modele.lambdas(0, 1))

    def test_serialisable_en_json(self, simulation):
        import json

        df, _, _ = simulation
        modele = fit_dixon_coles(df, xi=0.0)

        assert json.loads(json.dumps(modele.to_dict()))["rho"] == pytest.approx(modele.rho)


class TestAjustementParCompetition:
    def test_un_modele_par_competition(self):
        premier, _, _ = _simuler(n_teams=6, tours=6, graine=1, competition_id=1)
        second, _, _ = _simuler(n_teams=6, tours=6, graine=2, competition_id=2)
        second["home_team_id"] += 100
        second["away_team_id"] += 100
        df = pd.concat([premier, second], ignore_index=True)

        modeles = fit_par_competition(df, xi=0.0)

        assert set(modeles) == {1, 2}
        assert set(modeles[1].teams).isdisjoint(modeles[2].teams)

    def test_une_competition_inexploitable_est_ignoree(self):
        premier, _, _ = _simuler(n_teams=6, tours=4, graine=1, competition_id=1)
        vide = premier.head(1).copy()
        vide["competition_id"] = 2
        vide[["home_goals", "away_goals"]] = None
        df = pd.concat([premier, vide], ignore_index=True)

        modeles = fit_par_competition(df, xi=0.0)

        assert set(modeles) == {1}


class TestEntreesInvalides:
    def test_colonnes_manquantes(self):
        with pytest.raises(ValueError, match="Colonnes absentes"):
            fit_dixon_coles(pd.DataFrame({"home_team_id": [1]}))

    def test_aucun_match_note(self):
        df = pd.DataFrame(
            {
                "home_team_id": [0, 1],
                "away_team_id": [1, 0],
                "home_goals": [None, None],
                "away_goals": [None, None],
            }
        )
        with pytest.raises(ValueError, match="Aucun match avec score"):
            fit_dixon_coles(df)

    def test_une_seule_equipe(self):
        df = pd.DataFrame(
            {
                "home_team_id": [0],
                "away_team_id": [0],
                "home_goals": [1],
                "away_goals": [1],
            }
        )
        with pytest.raises(ValueError, match="deux équipes"):
            fit_dixon_coles(df)
