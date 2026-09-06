"""Tests du registre des modèles.

Le registre ne savait qu'enregistrer des métadonnées : il notait qu'un modèle
existait, sans jamais conserver de quoi le rejouer. Une prédiction datée
devenait donc inexplicable dès que le modèle était réentraîné.
"""

import json

import pandas as pd
import pytest

from models.dixon_coles import DixonColesModel, fit_dixon_coles
from models.model_registry import ModelRegistry


@pytest.fixture
def registre(tmp_path):
    return ModelRegistry(tmp_path / "models")


@pytest.fixture(scope="module")
def modele_ajuste():
    lignes = []
    for tour in range(6):
        for i in range(6):
            for j in range(6):
                if i == j:
                    continue
                lignes.append(
                    {
                        "id": len(lignes),
                        "competition_id": 1,
                        "match_date": pd.Timestamp("2023-08-01") + pd.Timedelta(days=len(lignes)),
                        "home_team_id": i,
                        "away_team_id": j,
                        "home_goals": (i + tour) % 4,
                        "away_goals": (j + 1) % 3,
                    }
                )
    return fit_dixon_coles(pd.DataFrame(lignes), xi=0.0, competition_id=1)


class TestEnregistrement:
    def test_une_version_est_retrouvee(self, registre):
        registre.register("dixon_coles", "v1", metrics={"log_loss": 0.98})

        entree = registre.get("dixon_coles", "v1")

        assert entree is not None
        assert entree["metrics"]["log_loss"] == 0.98

    def test_deux_enregistrements_de_la_meme_version_sont_refuses(self, registre):
        """Écraser un modèle rendrait ses prédictions passées inexplicables."""
        registre.register("dixon_coles", "v1")

        with pytest.raises(ValueError, match="déjà enregistrée"):
            registre.register("dixon_coles", "v1")

    def test_la_derniere_version_est_la_plus_recente(self, registre):
        registre.register("dixon_coles", "v1")
        registre.register("dixon_coles", "v2")
        registre.register("poisson", "v1")

        assert registre.get_latest("dixon_coles")["version"] == "v2"
        assert registre.get_latest("poisson")["version"] == "v1"

    def test_modele_inconnu(self, registre):
        assert registre.get_latest("inexistant") is None
        assert registre.load("inexistant") is None


class TestRechargement:
    def test_un_modele_ajuste_survit_a_un_aller_retour(self, registre, modele_ajuste):
        """Le critère qui compte : retrouver les mêmes prédictions."""
        registre.register("dixon_coles", "2024-06", payload=modele_ajuste.to_dict())

        recharge = DixonColesModel.from_dict(registre.load("dixon_coles"))

        assert recharge.lambdas(0, 1) == pytest.approx(modele_ajuste.lambdas(0, 1))
        assert recharge.rho == pytest.approx(modele_ajuste.rho)
        assert recharge.home_advantage == pytest.approx(modele_ajuste.home_advantage)

    def test_une_version_precise_est_rechargeable(self, registre, modele_ajuste):
        registre.register("dixon_coles", "v1", payload=modele_ajuste.to_dict())
        autre = DixonColesModel(
            attack={0: 1.0}, defense={0: 0.0}, home_advantage=0.5, rho=0.0, n_matches=1
        )
        registre.register("dixon_coles", "v2", payload=autre.to_dict())

        ancien = DixonColesModel.from_dict(registre.load("dixon_coles", "v1"))

        assert ancien.rho == pytest.approx(modele_ajuste.rho)
        assert registre.load("dixon_coles")["home_advantage"] == pytest.approx(0.5)

    def test_sans_parametres_le_rechargement_est_vide(self, registre):
        registre.register("dixon_coles", "v1", metrics={"brier": 0.2})

        assert registre.load("dixon_coles") is None

    def test_parametres_effaces_du_disque(self, registre, modele_ajuste, tmp_path):
        registre.register("dixon_coles", "v1", payload=modele_ajuste.to_dict())
        chemin = registre.get("dixon_coles", "v1")["payload_path"]
        __import__("pathlib").Path(chemin).unlink()

        assert registre.load("dixon_coles") is None


class TestPersistanceSurDisque:
    def test_un_nouveau_registre_relit_l_index(self, tmp_path, modele_ajuste):
        premier = ModelRegistry(tmp_path / "models")
        premier.register("dixon_coles", "v1", payload=modele_ajuste.to_dict())

        second = ModelRegistry(tmp_path / "models")

        assert second.get_latest("dixon_coles")["version"] == "v1"
        assert second.load("dixon_coles") is not None

    def test_l_index_est_un_json_lisible(self, registre):
        registre.register("dixon_coles", "v1", metrics={"log_loss": 1.0})

        contenu = json.loads(registre.registry_file.read_text(encoding="utf-8"))

        assert contenu[0]["model_name"] == "dixon_coles"

    def test_aucun_fichier_partiel_ne_subsiste(self, registre):
        registre.register("dixon_coles", "v1")

        assert list(registre.registry_dir.glob("*.partiel")) == []

    def test_versions_listees_dans_l_ordre(self, registre):
        for v in ("v1", "v2", "v3"):
            registre.register("dixon_coles", v)

        assert [e["version"] for e in registre.versions("dixon_coles")] == ["v1", "v2", "v3"]

    def test_un_registre_vide_ne_casse_pas(self, tmp_path):
        registre = ModelRegistry(tmp_path / "models")
        registre.registry_file.write_text("", encoding="utf-8")

        assert registre.versions() == []
