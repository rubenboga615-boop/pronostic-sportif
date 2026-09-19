"""Le choix de la cible d'entraînement.

`train_models.py` sait ajuster les forces depuis les buts marqués ou depuis les
buts attendus. Le reste du protocole — découpage chronologique, modèles de
mi-temps, registre — est commun aux deux, pour que les versions produites
soient comparables terme à terme.

Ces tests portent sur l'aiguillage lui-même. La qualité de chaque ajusteur est
mesurée ailleurs : `tests/test_dixon_coles.py` et `tests/test_dixon_coles_xg.py`.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

_spec = importlib.util.spec_from_file_location(
    "train_models_script", RACINE / "scripts" / "train_models.py"
)
train_models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(train_models)


class TestAiguillage:
    def test_les_deux_cibles_sont_proposees(self):
        assert set(train_models.AJUSTEURS) == {"buts", "xg"}

    def test_la_cible_par_defaut_reste_les_buts(self):
        """Changer la valeur par défaut changerait silencieusement tous les
        modèles produits par les commandes déjà documentées."""
        analyseur = train_models.argparse.ArgumentParser()
        analyseur.add_argument("--cible", choices=sorted(train_models.AJUSTEURS), default="buts")
        assert analyseur.parse_args([]).cible == "buts"

    def test_cible_inconnue_refusee_avant_toute_lecture(self):
        """Le refus doit précéder l'accès à la base : un nom mal orthographié
        ne doit pas coûter le chargement de dix-sept mille matchs."""
        with pytest.raises(ValueError, match="Cible inconnue"):
            train_models.entrainer(
                train_end="2023-06-30",
                val_end="2024-06-30",
                version="peu-importe",
                xi=0.0018,
                dry_run=True,
                cible="xG",
            )


class TestRequete:
    def test_la_requete_ramene_les_xg_des_deux_cotes(self):
        assert "home_xg" in train_models.REQUETE
        assert "away_xg" in train_models.REQUETE

    def test_les_xg_sont_joints_par_equipe_et_non_par_match_seul(self):
        """Sans la condition sur ``team_id``, chaque match ramènerait les deux
        lignes de xG dans les deux colonnes, et les forces seraient fausses."""
        assert "dom.team_id = m.home_team_id" in train_models.REQUETE
        assert "ext.team_id = m.away_team_id" in train_models.REQUETE

    def test_la_jointure_est_externe(self):
        """Un match sans xG doit rester dans le jeu : il sert à l'ajustement
        sur les buts, et à l'estimation de rho."""
        assert train_models.REQUETE.count("LEFT JOIN") == 2
