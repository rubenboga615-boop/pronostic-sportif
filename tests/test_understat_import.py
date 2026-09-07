"""Tests du collecteur Understat et de son import vers `xg_match_stats`.

Deux risques dominent ici, et aucun ne se manifeste par une erreur :

1. **Un mauvais rattachement.** L'export n'a pas d'identifiant de match ; si la
   date ou l'équipe est mal résolue, le xG d'un match s'écrit sur un autre. Le
   contrôle de score est le seul filet, et il est testé en premier.

2. **Un import non idempotent.** Relancé après un ajout de matchs, il
   doublerait les xG de tout l'historique déjà traité.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.models import Base, Match, Team, XgMatchStats
from collectors.mapping.registre import NomInconnuError, RegistreCorrespondances
from collectors.understat.game_stats import (
    ExportIllisibleError,
    lire_game_stats,
    noms_non_resolus,
)

ENTETE = "league,date,club_name,home_away,xG,xGA,npxG,scored,missed"


def _export(tmp_path: Path, lignes: list[str], nom: str = "game_stats.csv") -> Path:
    chemin = tmp_path / nom
    chemin.write_text("\n".join([ENTETE, *lignes]) + "\n", encoding="utf-8")
    return chemin


@pytest.fixture
def registre():
    """Registre minimal : Arsenal et Chelsea, en Premier League."""
    return RegistreCorrespondances(
        {"understat": {"E0": {"Arsenal": "Arsenal", "Chelsea": "Chelsea"}}}
    )


class TestLecture:
    def test_une_ligne_est_lue_et_resolue(self, tmp_path, registre):
        chemin = _export(tmp_path, ["EPL,2023-08-12 15:00:00,Arsenal,h,2.1,0.8,1.9,2,1"])

        lignes, rapport = lire_game_stats(chemin, registre=registre)

        assert len(lignes) == 1
        ligne = lignes[0]
        assert ligne.ligue == "E0"
        assert ligne.equipe == "Arsenal"
        assert ligne.domicile is True
        assert ligne.xg == 2.1
        assert ligne.npxg == 1.9
        assert ligne.buts_marques == 2
        assert rapport["lignes_retenues"] == 1

    def test_l_heure_est_ecartee_au_profit_du_jour(self, tmp_path, registre):
        """Football-Data ne publie pas d'heure : comparer les horodatages
        complets ne rattacherait jamais rien."""
        chemin = _export(tmp_path, ["EPL,2023-08-12 19:45:00,Arsenal,h,1,1,1,0,0"])

        lignes, _ = lire_game_stats(chemin, registre=registre)

        assert lignes[0].jour == datetime(2023, 8, 12).date()

    def test_la_rfpl_est_ignoree(self, tmp_path, registre):
        """Le championnat russe n'est pas dans le périmètre du projet."""
        chemin = _export(
            tmp_path,
            [
                "RFPL,2023-08-12 15:00:00,Zenit,h,1.5,0.5,1.5,2,0",
                "EPL,2023-08-12 15:00:00,Arsenal,h,2.1,0.8,1.9,2,1",
            ],
        )

        lignes, rapport = lire_game_stats(chemin, registre=registre)

        assert len(lignes) == 1
        assert rapport["ligues_ignorees"] == {"RFPL": 1}

    def test_un_nom_inconnu_leve(self, tmp_path, registre):
        """Jamais de rapprochement approximatif : l'import doit s'arrêter."""
        chemin = _export(tmp_path, ["EPL,2023-08-12 15:00:00,Inconnu FC,h,1,1,1,0,0"])

        with pytest.raises(NomInconnuError):
            lire_game_stats(chemin, registre=registre)

    def test_un_export_sans_les_colonnes_attendues_leve(self, tmp_path, registre):
        chemin = tmp_path / "autre.csv"
        chemin.write_text("league,date,club_name\nEPL,2023-08-12,Arsenal\n", encoding="utf-8")

        with pytest.raises(ExportIllisibleError):
            lire_game_stats(chemin, registre=registre)

    def test_une_date_illisible_est_comptee_pas_devinee(self, tmp_path, registre):
        chemin = _export(tmp_path, ["EPL,pas une date,Arsenal,h,1,1,1,0,0"])

        lignes, rapport = lire_game_stats(chemin, registre=registre)

        assert lignes == []
        assert rapport["dates_illisibles"] == 1

    def test_les_valeurs_vides_restent_nulles(self, tmp_path, registre):
        """Une valeur absente ne doit jamais devenir 0.0 : la différence
        compte pour une moyenne de xG."""
        chemin = _export(tmp_path, ["EPL,2023-08-12 15:00:00,Arsenal,h,,,,,"])

        lignes, _ = lire_game_stats(chemin, registre=registre)

        assert lignes[0].xg is None
        assert lignes[0].buts_marques is None

    def test_l_inventaire_des_noms_manquants_precede_l_import(self, tmp_path, registre):
        chemin = _export(
            tmp_path,
            [
                "EPL,2023-08-12 15:00:00,Arsenal,h,1,1,1,0,0",
                "EPL,2023-08-12 15:00:00,Inconnu FC,a,1,1,1,0,0",
            ],
        )

        assert noms_non_resolus(chemin, registre=registre) == {"E0": ["Inconnu FC"]}


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base de test avec un match Arsenal 2-1 Chelsea, et rien d'autre."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import pipelines.understat_import as pipeline

    moteur = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(moteur)
    fabrique = sessionmaker(bind=moteur)
    monkeypatch.setattr(pipeline, "SessionLocal", fabrique)

    session = fabrique()
    arsenal = Team(canonical_name="Arsenal", provider="football_data")
    chelsea = Team(canonical_name="Chelsea", provider="football_data")
    session.add_all([arsenal, chelsea])
    session.flush()
    session.add(
        Match(
            provider="football_data",
            match_date=datetime(2023, 8, 12),
            home_team_id=arsenal.id,
            away_team_id=chelsea.id,
            home_goals=2,
            away_goals=1,
        )
    )
    session.commit()
    session.close()
    return fabrique


class TestImport:
    def _importer(self, chemin, monkeypatch, registre, **kwargs):
        import collectors.understat.game_stats as lecteur
        import pipelines.understat_import as pipeline

        monkeypatch.setattr(lecteur, "charger_registre", lambda *a, **k: registre)
        return pipeline.importer_xg(chemin, **kwargs)

    def test_les_deux_camps_sont_rattaches_au_bon_match(
        self, tmp_path, base, monkeypatch, registre
    ):
        chemin = _export(
            tmp_path,
            [
                "EPL,2023-08-12 15:00:00,Arsenal,h,2.4,1.1,2.4,2,1",
                "EPL,2023-08-12 15:00:00,Chelsea,a,1.1,2.4,1.1,1,2",
            ],
        )

        rapport = self._importer(chemin, monkeypatch, registre)

        assert rapport["inserees"] == 2
        assert rapport["sans_match"] == 0

        session = base()
        stats = session.query(XgMatchStats).all()
        assert {round(s.xg, 1) for s in stats} == {2.4, 1.1}
        assert len({s.match_id for s in stats}) == 1
        session.close()

    def test_un_score_discordant_est_refuse(self, tmp_path, base, monkeypatch, registre):
        """Le seul garde-fou contre un rattachement faux mais plausible."""
        chemin = _export(tmp_path, ["EPL,2023-08-12 15:00:00,Arsenal,h,2.4,1.1,2.4,5,0"])

        rapport = self._importer(chemin, monkeypatch, registre)

        assert rapport["scores_discordants"] == 1
        assert rapport["inserees"] == 0

        session = base()
        assert session.query(XgMatchStats).count() == 0
        session.close()

    def test_une_ligne_sans_match_en_base_n_insere_rien(
        self, tmp_path, base, monkeypatch, registre
    ):
        """Understat couvre des saisons que la base n'a pas : c'est normal,
        et ces lignes doivent être comptées, pas insérées de force."""
        chemin = _export(tmp_path, ["EPL,2019-05-01 15:00:00,Arsenal,h,1.0,1.0,1.0,0,0"])

        rapport = self._importer(chemin, monkeypatch, registre)

        assert rapport["sans_match"] == 1
        assert rapport["inserees"] == 0

    def test_l_import_est_idempotent(self, tmp_path, base, monkeypatch, registre):
        chemin = _export(
            tmp_path,
            [
                "EPL,2023-08-12 15:00:00,Arsenal,h,2.4,1.1,2.4,2,1",
                "EPL,2023-08-12 15:00:00,Chelsea,a,1.1,2.4,1.1,1,2",
            ],
        )

        premier = self._importer(chemin, monkeypatch, registre)
        second = self._importer(chemin, monkeypatch, registre)

        assert premier["inserees"] == 2
        assert second["inserees"] == 0
        assert second["mises_a_jour"] == 2

        session = base()
        assert session.query(XgMatchStats).count() == 2
        session.close()

    def test_la_simulation_n_ecrit_rien(self, tmp_path, base, monkeypatch, registre):
        chemin = _export(tmp_path, ["EPL,2023-08-12 15:00:00,Arsenal,h,2.4,1.1,2.4,2,1"])

        rapport = self._importer(chemin, monkeypatch, registre, simuler=True)

        assert rapport["inserees"] == 1
        assert rapport["simule"] is True

        session = base()
        assert session.query(XgMatchStats).count() == 0
        session.close()

    def test_le_rapport_rend_compte_de_chaque_ligne(self, tmp_path, base, monkeypatch, registre):
        """Invariant : aucune ligne retenue ne disparaît sans être comptée."""
        chemin = _export(
            tmp_path,
            [
                "EPL,2023-08-12 15:00:00,Arsenal,h,2.4,1.1,2.4,2,1",  # insérée
                "EPL,2019-05-01 15:00:00,Chelsea,a,1.0,1.0,1.0,0,0",  # sans match
                "EPL,2023-08-12 15:00:00,Chelsea,a,1.1,2.4,1.1,9,9",  # discordante
            ],
        )

        r = self._importer(chemin, monkeypatch, registre)

        assert r["lignes_retenues"] == (
            r["inserees"]
            + r["mises_a_jour"]
            + r["sans_match"]
            + r["equipes_inconnues"]
            + r["scores_discordants"]
        )
