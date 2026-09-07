"""Tests du registre de correspondance des noms d'équipes.

Le risque que ce registre écarte est particulier : il ne provoque pas d'erreur.
Sans lui, chaque fournisseur crée sa propre « Manchester United » à côté du
« Manchester Utd » de Football-Data, l'import réussit, et l'historique du club
se scinde en deux moitiés dont aucune ne suffit à entraîner quoi que ce soit.

D'où la règle testée ici avant tout : **un nom inconnu lève**. Jamais de
rapprochement automatique, jamais de création silencieuse.
"""

import json

import pytest

from collectors.mapping.candidats import proposer, ressemblance, resume
from collectors.mapping.registre import (
    NomInconnuError,
    RegistreCorrespondances,
    charger_registre,
    normaliser,
)


class TestResolutionStricte:
    def test_un_nom_canonique_se_resout_a_lui_meme(self):
        registre = RegistreCorrespondances()

        assert registre.canonique("understat", "E0", "Arsenal") == "Arsenal"

    def test_une_correspondance_explicite_est_appliquee(self):
        registre = RegistreCorrespondances(
            {"understat": {"E0": {"Manchester United": "Manchester Utd"}}}
        )

        assert registre.canonique("understat", "E0", "Manchester United") == "Manchester Utd"

    def test_les_differences_typographiques_sont_absorbees(self):
        """« Atlético Madrid » et « Atletico Madrid » sont le même club.

        C'est le seul rapprochement automatique autorisé : après suppression des
        accents, de la casse et de la ponctuation, les deux chaînes sont
        identiques. Aucune ressemblance partielle n'est jamais acceptée.
        """
        registre = RegistreCorrespondances()

        assert registre.canonique("understat", "SP1", "Atlético Madrid") == "Atletico Madrid"

    def test_un_nom_inconnu_leve(self):
        """Le cœur du dispositif : refuser plutôt que deviner."""
        registre = RegistreCorrespondances()

        with pytest.raises(NomInconnuError):
            registre.canonique("understat", "E0", "Manchester United")

    def test_un_nom_ressemblant_ne_suffit_pas(self):
        """« Man Utd » ressemble beaucoup à « Manchester Utd ». Insuffisant.

        Si la ressemblance suffisait, « Real Sociedad » se résoudrait un jour en
        « Real Madrid » sans que personne ne le voie passer.
        """
        registre = RegistreCorrespondances()

        with pytest.raises(NomInconnuError):
            registre.canonique("understat", "E0", "Man Utd")

    def test_l_erreur_porte_de_quoi_corriger(self):
        registre = RegistreCorrespondances()

        with pytest.raises(NomInconnuError) as excinfo:
            registre.canonique("api_football", "E0", "Manchester United")

        erreur = excinfo.value
        assert erreur.fournisseur == "api_football"
        assert erreur.ligue == "E0"
        assert erreur.nom == "Manchester United"
        assert "Manchester Utd" in erreur.suggestions
        assert "equipes.json" in str(erreur)

    def test_les_suggestions_ne_sont_jamais_appliquees(self):
        """Elles éclairent l'humain ; elles ne résolvent rien."""
        registre = RegistreCorrespondances()

        with pytest.raises(NomInconnuError) as excinfo:
            registre.canonique("api_football", "E0", "Manchester United")

        assert excinfo.value.suggestions  # il y en a
        assert not registre.connait("api_football", "E0", "Manchester United")


class TestInventaireAvantImport:
    def test_tous_les_noms_manquants_sont_listes_d_un_coup(self):
        """Mieux vaut vingt noms manquants annoncés qu'échouer vingt fois."""
        registre = RegistreCorrespondances({"understat": {"E0": {"Spurs": "Tottenham"}}})

        manquants = registre.noms_non_resolus(
            "understat", "E0", ["Arsenal", "Manchester United", "Spurs", "Wolves"]
        )

        assert manquants == ["Manchester United", "Wolves"]

    def test_les_doublons_ne_sont_signales_qu_une_fois(self):
        registre = RegistreCorrespondances()

        manquants = registre.noms_non_resolus(
            "understat", "E0", ["Manchester United", "Manchester United"]
        )

        assert manquants == ["Manchester United"]


class TestCoherenceDuRegistre:
    def test_une_cible_inexistante_est_une_anomalie(self):
        """Pire qu'une correspondance absente : elle écrirait une équipe fantôme."""
        registre = RegistreCorrespondances(
            {"understat": {"E0": {"Manchester United": "Manchester Uni7ed"}}}
        )

        anomalies = registre.verifier()

        assert len(anomalies) == 1
        assert "Manchester Uni7ed" in anomalies[0]

    def test_une_ligue_inconnue_est_une_anomalie(self):
        registre = RegistreCorrespondances({"understat": {"XX": {"Truc": "Machin"}}})

        assert any("XX" in a for a in registre.verifier())

    def test_un_fournisseur_inattendu_est_une_anomalie(self):
        registre = RegistreCorrespondances({"betclic": {"E0": {}}})

        assert any("betclic" in a for a in registre.verifier())

    def test_un_registre_incoherent_refuse_de_se_charger(self, tmp_path):
        fichier = tmp_path / "equipes.json"
        fichier.write_text(
            json.dumps({"correspondances": {"understat": {"E0": {"X": "Inexistant"}}}}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="incohérent"):
            charger_registre(fichier)

    def test_un_registre_absent_donne_un_registre_vide(self, tmp_path):
        """État de départ valable : tout lève, ce qui est le comportement voulu."""
        registre = charger_registre(tmp_path / "inexistant.json")

        assert registre.correspondances == {}
        assert registre.canonique("understat", "E0", "Arsenal") == "Arsenal"

    def test_le_registre_commite_est_coherent(self):
        """Le fichier du dépôt lui-même, s'il existe."""
        assert charger_registre().verifier() == []


class TestNormalisation:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("Atlético Madrid", "atletico madrid"),
            ("Brighton & Hove Albion", "brighton hove albion"),
            ("  Real   Betis  ", "real betis"),
            ("1. FC Köln", "1 fc koln"),
            ("Saint-Étienne", "saint etienne"),
        ],
    )
    def test_formes_comparables(self, brut, attendu):
        assert normaliser(brut) == attendu


class TestPropositions:
    def test_un_rapprochement_net_est_propose(self):
        [proposition] = proposer("understat", "E0", ["Manchester United"])

        assert proposition.decision == "candidat"
        assert proposition.canonique == "Manchester Utd"

    def test_un_nom_deja_resoluble_n_est_pas_repropose(self):
        [proposition] = proposer("understat", "E0", ["Arsenal"])

        assert proposition.decision == "resolu"
        assert proposition.canonique is None

    def test_une_equipe_d_une_autre_ligue_n_a_pas_de_correspondance(self):
        """« Paris Saint Germain » en Premier League n'est pas ambigu : il est
        absent. Le signaler comme ambigu enverrait relire pour rien."""
        [proposition] = proposer("understat", "E0", ["Paris Saint Germain"])

        assert proposition.decision == "aucun"
        assert proposition.canonique is None

    def test_deux_candidats_trop_proches_sont_declares_ambigus(self):
        """Le piège que le seuil seul ne verrait pas.

        Sans écart minimal exigé avec le second candidat, un nom également
        proche de deux clubs serait tranché par une différence de millièmes.
        """
        propositions = proposer("understat", "SP1", ["Real"])

        assert propositions[0].decision == "ambigu"

    def test_ce_qui_est_deja_commite_n_est_pas_repropose(self):
        registre = RegistreCorrespondances(
            {"understat": {"E0": {"Manchester United": "Manchester Utd"}}}
        )

        [proposition] = proposer("understat", "E0", ["Manchester United"], registre=registre)

        assert proposition.decision == "resolu"

    def test_le_resume_compte_les_quatre_tas(self):
        propositions = proposer(
            "understat",
            "E0",
            ["Arsenal", "Manchester United", "Paris Saint Germain"],
        )

        assert resume(propositions) == {
            "resolu": 1,
            "candidat": 1,
            "ambigu": 0,
            "aucun": 1,
        }


class TestRessemblance:
    def test_les_suffixes_ajoutes_sont_captes(self):
        """« Milan » et « AC Milan » : le recouvrement de mots les rapproche."""
        assert ressemblance("Milan", "AC Milan") >= 0.85

    def test_les_troncatures_sont_captees(self):
        assert ressemblance("Nottm Forest", "Nottingham Forest") >= 0.7

    def test_deux_clubs_distincts_qui_se_ressemblent_restent_distincts(self):
        """La limite assumée de l'appariement, et la raison de la relecture.

        Le score entre deux clubs sans rapport est trompeusement élevé — c'est
        précisément pourquoi aucune décision n'est prise à partir de lui.
        """
        assert ressemblance("Real Sociedad", "Real Madrid") >= 0.5

    def test_une_faute_de_frappe_leve_malgre_la_ressemblance(self):
        """« Real Socidad » est à un caractère de « Real Sociedad ».

        Le runtime lève quand même : seule l'égalité après normalisation est
        acceptée, et une lettre manquante n'en est pas une.
        """
        assert ressemblance("Real Socidad", "Real Sociedad") > 0.9

        with pytest.raises(NomInconnuError):
            RegistreCorrespondances().canonique("understat", "SP1", "Real Socidad")
