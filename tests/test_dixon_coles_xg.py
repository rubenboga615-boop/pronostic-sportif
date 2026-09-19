"""Tests du Dixon-Coles ajusté sur les buts attendus.

Le critère est le même que pour l'ajustement sur les buts : récupérer des
paramètres connus. Les xG sont simulés autour de lambdas fixés d'avance, par
tirage Gamma — continu, sur-dispersé, comme un vrai xG — et l'ajustement doit
retrouver l'avantage du terrain et les forces d'équipe.

Un test porte spécifiquement sur la raison d'être du module : la réussite
devant le but ne doit **pas** déplacer les forces estimées. Une équipe à qui
l'on offre trois buts par match voit son attaque grimper dans l'ajustement sur
les buts, et ne bouge pas dans celui sur les xG.
"""

import numpy as np
import pandas as pd
import pytest

from models.dixon_coles import DixonColesModel, fit_dixon_coles, score_matrix_from_lambdas
from models.dixon_coles_xg import fit_dixon_coles_xg

AVANTAGE_TERRAIN = 0.28
RHO = -0.12
# Forme de la loi Gamma des xG autour de leur moyenne. Plus elle est grande,
# moins le xG d'un match s'écarte de la force sous-jacente.
FORME_GAMMA = 4.0


def _simuler_xg(
    n_teams=10,
    tours=10,
    graine=11,
    home_adv=AVANTAGE_TERRAIN,
    rho=RHO,
    competition_id=1,
    depart="2020-01-01",
):
    """Simuler un championnat : xG tirés autour de lambda, buts tirés du xG.

    C'est la chaîne causale que le module suppose — la force produit des
    occasions, les occasions produisent des buts — et non l'inverse.
    """
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
                home_xg = float(rng.gamma(FORME_GAMMA, lam / FORME_GAMMA))
                away_xg = float(rng.gamma(FORME_GAMMA, mu / FORME_GAMMA))
                matrice = score_matrix_from_lambdas(home_xg, away_xg, rho, max_goals=10)
                tirage = rng.choice(matrice.size, p=matrice.ravel() / matrice.sum())
                hg, ag = divmod(int(tirage), matrice.shape[1])
                lignes.append(
                    {
                        "id": mid,
                        "competition_id": competition_id,
                        "match_date": pd.Timestamp(depart) + pd.Timedelta(days=mid // 5),
                        "home_team_id": i,
                        "away_team_id": j,
                        "home_xg": home_xg,
                        "away_xg": away_xg,
                        "home_goals": hg,
                        "away_goals": ag,
                    }
                )
                mid += 1

    return pd.DataFrame(lignes), attack, defense


class TestRecuperationDesParametres:
    """L'ajustement retrouve-t-il les forces qui ont engendré les xG ?"""

    def test_avantage_du_terrain_retrouve(self):
        matchs, _, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        assert modele.home_advantage == pytest.approx(AVANTAGE_TERRAIN, abs=0.06)

    def test_forces_dattaque_retrouvees(self):
        matchs, attack, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        estimees = np.array([modele.attack[i] for i in range(len(attack))])
        assert np.corrcoef(estimees, attack)[0, 1] > 0.95
        assert np.max(np.abs(estimees - attack)) < 0.15

    def test_forces_de_defense_retrouvees(self):
        matchs, _, defense = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        estimees = np.array([modele.defense[i] for i in range(len(defense))])
        # La défense n'est identifiée qu'à une constante près, absorbée par
        # l'attaque : seule sa structure relative a un sens.
        assert np.corrcoef(estimees, defense)[0, 1] > 0.95

    def test_convergence(self):
        matchs, _, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        assert modele.converged
        assert modele.n_matches == len(matchs)


class TestInsensibiliteALaReussite:
    """La raison d'être du module : ignorer le bruit de conversion."""

    def test_trois_buts_offerts_ne_deplacent_pas_lattaque_estimee(self):
        matchs, _, _ = _simuler_xg()
        chanceuse = 3

        truques = matchs.copy()
        a_domicile = truques["home_team_id"] == chanceuse
        a_lexterieur = truques["away_team_id"] == chanceuse
        truques.loc[a_domicile, "home_goals"] += 3
        truques.loc[a_lexterieur, "away_goals"] += 3

        sur_buts = fit_dixon_coles(matchs, xi=0.0)
        sur_buts_truques = fit_dixon_coles(truques, xi=0.0)
        sur_xg = fit_dixon_coles_xg(matchs, xi=0.0)
        sur_xg_truques = fit_dixon_coles_xg(truques, xi=0.0)

        derive_buts = abs(sur_buts_truques.attack[chanceuse] - sur_buts.attack[chanceuse])
        derive_xg = abs(sur_xg_truques.attack[chanceuse] - sur_xg.attack[chanceuse])

        assert derive_buts > 0.5, "les buts offerts devraient gonfler l'attaque estimée"
        assert derive_xg < 1e-9, "les xG n'ont pas changé : l'attaque ne doit pas bouger"


class TestRhoAjusteSurLesButs:
    """Rho porte sur les scores serrés : il n'a de sens que sur des entiers."""

    def test_rho_negatif_retrouve(self):
        matchs, _, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        assert modele.rho == pytest.approx(RHO, abs=0.10)

    def test_sans_buts_rho_reste_nul(self):
        matchs, _, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs.drop(columns=["home_goals", "away_goals"]), xi=0.0)
        assert modele.rho == 0.0
        assert modele.metadata["n_matchs_rho"] == 0

    def test_les_buts_manquants_sont_ignores_par_rho_seul(self):
        matchs, _, _ = _simuler_xg()
        ampute = matchs.copy()
        ampute.loc[ampute.index[:200], ["home_goals", "away_goals"]] = np.nan

        modele = fit_dixon_coles_xg(ampute, xi=0.0)
        # Les 200 matchs sans score gardent leurs xG : ils comptent pour les
        # forces, et seulement pas pour rho.
        assert modele.n_matches == len(matchs)
        assert modele.metadata["n_matchs_rho"] == len(matchs) - 200


class TestInterchangeabiliteEnAval:
    """Le modèle doit s'utiliser partout où l'autre s'utilise."""

    def test_cible_signalee_dans_les_metadonnees(self):
        matchs, _, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        assert modele.metadata["cible"] == "xg"
        assert modele.metadata["rho_ajuste_sur"] == "buts"

    def test_aller_retour_par_le_registre(self):
        matchs, _, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        recharge = DixonColesModel.from_dict(modele.to_dict())
        assert recharge.attack == modele.attack
        assert recharge.rho == pytest.approx(modele.rho)
        assert recharge.metadata["cible"] == "xg"

    def test_matrice_de_scores_normalisee(self):
        matchs, _, _ = _simuler_xg()
        modele = fit_dixon_coles_xg(matchs, xi=0.0)
        matrice = modele.score_matrix(0, 1)
        assert matrice.sum() == pytest.approx(1.0)
        assert (matrice >= 0).all()


class TestPonderationTemporelle:
    def test_la_ponderation_change_lajustement(self):
        matchs, _, _ = _simuler_xg()
        sans = fit_dixon_coles_xg(matchs, xi=0.0)
        avec = fit_dixon_coles_xg(matchs, xi=0.0018)
        assert sans.home_advantage != avec.home_advantage

    def test_reference_explicite_reproductible(self):
        matchs, _, _ = _simuler_xg()
        reference = pd.Timestamp("2021-01-01")
        premier = fit_dixon_coles_xg(matchs, xi=0.0018, reference_date=reference)
        second = fit_dixon_coles_xg(matchs, xi=0.0018, reference_date=reference)
        assert premier.home_advantage == pytest.approx(second.home_advantage)


class TestRefus:
    def test_colonnes_de_xg_absentes(self):
        matchs, _, _ = _simuler_xg()
        with pytest.raises(ValueError, match="Colonnes absentes"):
            fit_dixon_coles_xg(matchs.drop(columns=["home_xg"]))

    def test_aucun_xg_renseigne(self):
        matchs, _, _ = _simuler_xg()
        matchs[["home_xg", "away_xg"]] = np.nan
        with pytest.raises(ValueError, match="Aucun match avec xG"):
            fit_dixon_coles_xg(matchs)

    def test_une_seule_equipe(self):
        matchs, _, _ = _simuler_xg()
        solitaire = matchs[(matchs["home_team_id"] == 0) & (matchs["away_team_id"] == 0)]
        with pytest.raises(ValueError):
            fit_dixon_coles_xg(solitaire)
