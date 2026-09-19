"""Tests de la journée type.

Ce pipeline porte une responsabilité que les autres n'ont pas : les cotes ne
sont pas archivées par le fournisseur, donc ce qu'il ne relève pas aujourd'hui
n'existera plus demain. Trois risques en découlent, et aucun ne se manifeste
par une erreur :

1. **Un relevé de la veille étiqueté « clôture »** rendrait tout rendement
   futur incomparable aux 3 504 matchs déjà mesurés contre la clôture.
2. **Une étape en échec qui arrête les suivantes** perdrait le règlement des
   matchs joués — qui, lui, ne demande aucun réseau.
3. **Prédire avant d'avoir importé les résultats** calculerait les probabilités
   du jour sur la forme de l'avant-veille.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from pipelines import daily_update
from pipelines.daily_update import RapportJournalier, _saison_courante, run_daily_update


class ClientMuet:
    """Ne parle à personne. Le réseau n'a pas sa place dans un test."""

    async def get(self, endpoint, params=None, **_):
        return {"response": [], "paging": {"total": 1}}


@pytest.fixture
def journal(monkeypatch):
    """Remplacer chaque étape par un témoin, pour observer l'orchestration."""
    appels: list[str] = []

    def temoin(nom, echoue=False):
        def _etape(*_args, **_kwargs):
            appels.append(nom)
            if echoue:
                raise RuntimeError(f"{nom} indisponible")

        return _etape

    monkeypatch.setattr(daily_update, "etape_matchs", temoin("matchs"))
    monkeypatch.setattr(daily_update, "etape_blessures", temoin("blessures"))
    monkeypatch.setattr(daily_update, "etape_features", temoin("features"))
    monkeypatch.setattr(daily_update, "etape_reglement", temoin("reglement"))
    monkeypatch.setattr(daily_update, "etape_cotes", temoin("cotes"))
    monkeypatch.setattr(daily_update, "etape_predictions", temoin("predictions"))
    monkeypatch.setattr(daily_update, "etape_sauvegarde", temoin("sauvegarde"))
    return appels


class TestOrdreDesEtapes:
    def test_les_sept_etapes_s_enchainent(self, journal, tmp_path):
        run_daily_update(client=ClientMuet(), session=object(), repertoire_rapports=str(tmp_path))

        assert journal == [
            "matchs",
            "blessures",
            "features",
            "reglement",
            "cotes",
            "predictions",
            "sauvegarde",
        ]

    def test_les_resultats_entrent_avant_que_l_on_predise(self, journal, tmp_path):
        """Prédire avant d'importer calculerait sur la forme de l'avant-veille."""
        run_daily_update(client=ClientMuet(), session=object(), repertoire_rapports=str(tmp_path))

        assert journal.index("matchs") < journal.index("features")
        assert journal.index("features") < journal.index("predictions")

    def test_la_sauvegarde_ferme_la_marche(self, journal, tmp_path):
        """Elle doit capturer le résultat du jour, pas son état de départ."""
        run_daily_update(client=ClientMuet(), session=object(), repertoire_rapports=str(tmp_path))

        assert journal[-1] == "sauvegarde"


class TestPassageDeCloture:
    def test_il_ne_fait_que_relever_les_cotes(self, journal, tmp_path):
        """Il tourne dans l'heure précédant les coups d'envoi : tout le reste
        attendra le lendemain."""
        run_daily_update(
            client=ClientMuet(),
            session=object(),
            cloture=True,
            repertoire_rapports=str(tmp_path),
        )

        assert journal == ["cotes"]

    def test_le_rapport_dit_que_c_etait_une_cloture(self, journal, tmp_path):
        rapport = run_daily_update(
            client=ClientMuet(),
            session=object(),
            cloture=True,
            repertoire_rapports=str(tmp_path),
        )

        assert rapport.en_dict()["cloture"] is True


class TestToleranceAuxPannes:
    def test_une_etape_en_echec_n_arrete_pas_les_suivantes(self, monkeypatch, tmp_path):
        """Le réseau tombe par intermittence ; le règlement, lui, n'en a pas besoin."""
        appels: list[str] = []

        def temoin(nom):
            def _etape(*_a, **_k):
                appels.append(nom)

            return _etape

        def tombe(*_a, **_k):
            appels.append("matchs")
            raise RuntimeError("réseau indisponible")

        monkeypatch.setattr(daily_update, "etape_matchs", tombe)
        monkeypatch.setattr(daily_update, "etape_blessures", temoin("blessures"))
        monkeypatch.setattr(daily_update, "etape_features", temoin("features"))
        monkeypatch.setattr(daily_update, "etape_reglement", temoin("reglement"))
        monkeypatch.setattr(daily_update, "etape_cotes", temoin("cotes"))
        monkeypatch.setattr(daily_update, "etape_predictions", temoin("predictions"))
        monkeypatch.setattr(daily_update, "etape_sauvegarde", temoin("sauvegarde"))

        rapport = run_daily_update(
            client=ClientMuet(), session=object(), repertoire_rapports=str(tmp_path)
        )

        assert "reglement" in appels
        assert appels[-1] == "sauvegarde"
        assert rapport.echecs[0]["etape"] == "matchs"

    def test_l_echec_est_consigne_pas_avale(self, monkeypatch, tmp_path):
        def tombe(*_a, **_k):
            raise RuntimeError("quota épuisé")

        for nom in (
            "matchs",
            "blessures",
            "features",
            "reglement",
            "cotes",
            "predictions",
            "sauvegarde",
        ):
            monkeypatch.setattr(daily_update, f"etape_{nom}", tombe)

        rapport = run_daily_update(
            client=ClientMuet(), session=object(), repertoire_rapports=str(tmp_path)
        )

        assert len(rapport.echecs) == 7
        assert all("quota épuisé" in e["erreur"] for e in rapport.echecs)


class TestRapport:
    def test_un_rapport_est_ecrit(self, journal, tmp_path):
        run_daily_update(client=ClientMuet(), session=object(), repertoire_rapports=str(tmp_path))

        assert list(tmp_path.glob("journee_*.json"))

    def test_sans_repertoire_aucun_fichier(self, journal, tmp_path):
        run_daily_update(client=ClientMuet(), session=object(), repertoire_rapports="")

        assert not list(tmp_path.iterdir())

    def test_le_rapport_distingue_reussites_et_echecs(self):
        rapport = RapportJournalier()
        rapport.reussite("cotes", {"inserees": 12})
        rapport.echec("matchs", RuntimeError("réseau"))

        contenu = rapport.en_dict()

        assert contenu["etapes"]["cotes"] == {"inserees": 12}
        assert contenu["echecs"] == [{"etape": "matchs", "erreur": "réseau"}]


class TestSaisonCourante:
    @pytest.mark.parametrize(
        ("date", "attendue"),
        [
            (datetime(2026, 9, 19), 2026),
            (datetime(2026, 7, 1), 2026),
            (datetime(2027, 5, 30), 2026),
            (datetime(2027, 6, 30), 2026),
            (datetime(2027, 7, 1), 2027),
        ],
    )
    def test_une_saison_bascule_en_juillet(self, date, attendue):
        """Janvier ne change pas de saison : un match de mai 2027 appartient
        encore à 2026/27."""
        assert _saison_courante(date) == attendue
