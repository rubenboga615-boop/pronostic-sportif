"""Tests de la sonde API-Football, sur réponses simulées.

La sonde sera lancée une fois, sur un quota réel, avant d'écrire le moindre
collecteur. Elle doit donc fonctionner du premier coup — et surtout ne pas
s'arrêter à la première mesure qui échoue : le but d'une sonde est de continuer
et de rapporter ce qu'elle a pu établir.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import sonde_api_football as sonde_module

from collectors.api_football.erreurs import TransitoireError
from collectors.api_football.ligues import LIGUES, saison_api


class ClientSimule:
    """Rejoue des enveloppes par endpoint, et compte les appels."""

    def __init__(self, reponses: dict, echecs: set[str] | None = None):
        self.reponses = reponses
        self.echecs = echecs or set()
        self.appels: list[tuple[str, dict]] = []

    async def get(self, endpoint, params=None, **kwargs):
        self.appels.append((endpoint, params or {}))
        if endpoint in self.echecs:
            raise TransitoireError(f"{endpoint} indisponible (simulation)")
        return self.reponses.get(endpoint, {"errors": [], "response": []})

    def etat_quota(self):
        return {"consommes": len(self.appels), "restant": 7400, "limite": 7500}


def _reponses_completes():
    return {
        "status": {
            "response": {
                "subscription": {"plan": "Pro", "active": True, "end": "2027-09-01"},
                "requests": {"current": 12, "limit_day": 7500},
            }
        },
        "leagues": {
            "response": [
                {
                    "league": {"id": 39, "name": "Premier League"},
                    "country": {"name": "England"},
                    "seasons": [
                        {
                            "year": 2025,
                            "coverage": {
                                "odds": True,
                                "injuries": True,
                                "fixtures": {"lineups": True, "statistics_fixtures": True},
                            },
                        }
                    ],
                }
            ]
        },
        "teams": {
            "response": [
                {"team": {"name": "Manchester United"}},
                {"team": {"name": "Arsenal"}},
            ]
        },
        "fixtures": {
            "response": [
                {
                    "fixture": {"id": 12345, "date": "2026-09-12T14:00:00+00:00"},
                    "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
                }
            ]
        },
        "odds": {
            "results": 340,
            "paging": {"total": 17},
            "response": [
                {
                    "bookmakers": [
                        {
                            "name": "Bet365",
                            "bets": [
                                {"name": "Match Winner"},
                                {"name": "Goals Over/Under"},
                                {"name": "Both Teams Score"},
                            ],
                        },
                        {"name": "Pinnacle", "bets": [{"name": "Match Winner"}]},
                    ]
                }
            ],
        },
        "injuries": {
            "response": [
                {"fixture": {"date": "2026-09-01T00:00:00+00:00"}},
                {"fixture": {"date": "2026-09-06T00:00:00+00:00"}},
            ]
        },
    }


@pytest.fixture
def sonde():
    return sonde_module.Sonde(ClientSimule(_reponses_completes()), "2526")


class TestMesures:
    @pytest.mark.asyncio
    async def test_le_statut_est_releve(self, sonde):
        await sonde.statut()

        assert sonde.rapport["statut"]["plan"] == "Pro"
        assert sonde.rapport["statut"]["quota_journalier"] == 7500

    @pytest.mark.asyncio
    async def test_un_identifiant_correct_est_confirme(self, sonde):
        await sonde.ligues()

        assert sonde.rapport["ligues"]["E0"]["identifiant_confirme"] is True
        assert sonde.rapport["ligues"]["E0"]["couverture"]["odds"] is True

    @pytest.mark.asyncio
    async def test_un_identifiant_faux_est_signale(self):
        """Le pire scénario silencieux : importer sous la mauvaise compétition."""
        reponses = _reponses_completes()
        reponses["leagues"]["response"][0]["league"]["name"] = "Championship"

        sonde = sonde_module.Sonde(ClientSimule(reponses), "2526")
        await sonde.ligues()

        assert sonde.rapport["ligues"]["E0"]["identifiant_confirme"] is False

    @pytest.mark.asyncio
    async def test_les_noms_d_equipes_sont_collectes_et_tries(self, sonde):
        await sonde.noms_d_equipes()

        assert sonde.equipes["E0"] == ["Arsenal", "Manchester United"]

    @pytest.mark.asyncio
    async def test_le_calendrier_retient_le_prochain_match(self, sonde):
        await sonde.calendrier()

        prochain = sonde.rapport["calendrier"]["prochain"]
        assert prochain["domicile"] == "Arsenal"
        assert prochain["identifiant"] == 12345

    @pytest.mark.asyncio
    async def test_les_marches_utiles_sont_isoles(self, sonde):
        await sonde.calendrier()
        await sonde.cotes()

        cotes = sonde.rapport["cotes"]
        assert cotes["bookmakers"] == 2
        assert "Match Winner" in cotes["marches_utiles"]
        assert "Both Teams Score" in cotes["marches_utiles"]

    @pytest.mark.asyncio
    async def test_la_profondeur_des_cotes_est_mesuree_sur_deux_saisons(self, sonde):
        await sonde.profondeur_des_cotes()

        mesures = sonde.rapport["profondeur_des_cotes"]
        assert set(mesures) == {"2223", "2425"}
        assert mesures["2223"]["matchs_avec_cotes"] == 340

    @pytest.mark.asyncio
    async def test_les_blessures_rappellent_la_regle(self, sonde):
        await sonde.blessures()

        blessures = sonde.rapport["blessures"]
        assert blessures["entrees"] == 2
        assert "jamais devenir un injury_impact de 0" in blessures["rappel"]


class TestRobustesse:
    @pytest.mark.asyncio
    async def test_une_mesure_qui_echoue_n_arrete_pas_les_autres(self):
        """Le but d'une sonde est de rapporter ce qu'elle a pu établir."""
        client = ClientSimule(_reponses_completes(), echecs={"status", "injuries"})
        sonde = sonde_module.Sonde(client, "2526")

        await sonde.statut()
        await sonde.ligues()
        await sonde.blessures()

        assert "erreur" in sonde.rapport["statut"]
        assert "erreur" in sonde.rapport["blessures"]
        assert sonde.rapport["ligues"]["E0"]["identifiant_confirme"] is True

    @pytest.mark.asyncio
    async def test_sans_match_a_venir_les_cotes_ne_plantent_pas(self):
        reponses = _reponses_completes()
        reponses["fixtures"] = {"response": []}

        sonde = sonde_module.Sonde(ClientSimule(reponses), "2526")
        await sonde.calendrier()
        await sonde.cotes()

        assert sonde.rapport["calendrier"]["matchs_a_venir"] == 0
        assert "erreur" in sonde.rapport["cotes"]

    @pytest.mark.asyncio
    async def test_une_saison_sans_donnee_est_signalee_sans_planter(self):
        reponses = _reponses_completes()
        reponses["leagues"] = {"response": []}

        sonde = sonde_module.Sonde(ClientSimule(reponses), "2526")
        await sonde.ligues()

        assert "erreur" in sonde.rapport["ligues"]["E0"]


class TestBudget:
    @pytest.mark.asyncio
    async def test_la_sonde_tient_dans_son_plafond(self):
        """Sa promesse : une vingtaine d'appels, jamais davantage."""
        client = ClientSimule(_reponses_completes())
        sonde = sonde_module.Sonde(client, "2526")

        await sonde.statut()
        await sonde.ligues()
        await sonde.noms_d_equipes()
        await sonde.calendrier()
        await sonde.cotes()
        await sonde.profondeur_des_cotes()
        await sonde.blessures()

        assert len(client.appels) <= sonde_module.PLAFOND_APPELS
        assert len(client.appels) == 1 + len(LIGUES) * 2 + 1 + 1 + 2 + 1


class TestSortie:
    @pytest.mark.asyncio
    async def test_les_noms_sont_ecrits_au_format_du_generateur(self, sonde, tmp_path):
        """Le fichier doit être consommable tel quel par
        scripts/generer_correspondances.py, sans retouche."""
        await sonde.noms_d_equipes()
        sonde.ecrire(tmp_path)

        fichier = tmp_path / "noms_api_football_E0.json"
        donnees = json.loads(fichier.read_text(encoding="utf-8"))

        assert donnees["noms"] == ["Arsenal", "Manchester United"]

        from collectors.mapping.candidats import proposer

        propositions = proposer("api_football", "E0", donnees["noms"])
        assert {p.decision for p in propositions} == {"resolu", "candidat"}

    @pytest.mark.asyncio
    async def test_le_rapport_porte_le_cout_reel(self, sonde, tmp_path):
        await sonde.statut()
        chemin = sonde.ecrire(tmp_path)

        rapport = json.loads(chemin.read_text(encoding="utf-8"))
        assert rapport["quota"]["consommes"] == 1
        assert rapport["saison_testee"]["api_football"] == saison_api("2526")

    @pytest.mark.asyncio
    async def test_le_resume_s_affiche_sans_erreur(self, sonde, capsys):
        await sonde.statut()
        await sonde.ligues()
        await sonde.noms_d_equipes()
        await sonde.calendrier()
        await sonde.cotes()
        await sonde.profondeur_des_cotes()
        await sonde.blessures()
        sonde.rapport["quota"] = sonde.client.etat_quota()

        sonde_module.resumer(sonde.rapport)

        sortie = capsys.readouterr().out
        assert "Abonnement" in sortie
        assert "Premier League" in sortie
