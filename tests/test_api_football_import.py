"""Tests de l'écriture en base des matchs et cotes API-Football.

Quatre risques dominent, et aucun ne se signale par une erreur :

1. **Dupliquer une équipe.** Un second « Brest » sans historique, et le modèle
   prédit un club qui n'a jamais joué.
2. **Écraser un résultat.** 17 251 matchs viennent de Football-Data et font
   autorité ; D-10 interdit de les réécrire hors migration.
3. **Dupliquer à la relance.** Le réseau de cette machine coupe ; un import
   non rejouable est un import inutilisable.
4. **Prendre un relevé pré-match pour une cote de clôture.** Tout le rendement
   du projet est mesuré contre la clôture.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.database import SessionLocal
from app.models import Competition, Match, OddsSnapshot, Season, Team
from collectors.api_football.parsers import CoteNormalisee, MatchNormalise
from pipelines.api_football_import import (
    Rapport,
    _ecrire_cotes,
    _ecrire_match,
    importer_cotes,
    importer_matchs,
)


@pytest.fixture
def session():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def premier_league(session):
    competition = Competition(
        provider_code="E0", name="Premier League", country="England", active=True
    )
    session.add(competition)
    session.flush()
    return competition


def _equipe(session, nom: str) -> Team:
    equipe = Team(canonical_name=nom, country="England", provider="football_data", active=True)
    session.add(equipe)
    session.flush()
    return equipe


def _normalise(
    identifiant="af_1",
    domicile="Arsenal",
    exterieur="Chelsea",
    statut="completed",
    buts=(2, 1),
    mi_temps=(1, 0),
    date=datetime(2026, 9, 18, 19, 0),
):
    return MatchNormalise(
        provider_match_id=identifiant,
        code_ligue="E0",
        saison="2627",
        date=date,
        domicile=domicile,
        exterieur=exterieur,
        statut=statut,
        buts_domicile=buts[0],
        buts_exterieur=buts[1],
        buts_mt_domicile=mi_temps[0],
        buts_mt_exterieur=mi_temps[1],
        arbitre="Andrew Madley",
    )


class TestEcritureDesMatchs:
    def test_un_match_joue_entre_avec_son_score(self, session, premier_league):
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")
        rapport = Rapport()

        _ecrire_match(session, _normalise(), rapport)

        match = session.query(Match).one()
        assert (match.home_goals, match.away_goals) == (2, 1)
        assert (match.home_ht_goals, match.away_ht_goals) == (1, 0)
        assert match.status == "completed"
        assert match.provider == "api_football"
        assert rapport.matchs_crees == 1

    def test_un_match_a_venir_entre_sans_score(self, session, premier_league):
        """La règle anti-fuite exige qu'un match non joué n'ait aucun résultat."""
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")

        _ecrire_match(
            session,
            _normalise(statut="scheduled", buts=(None, None), mi_temps=(None, None)),
            Rapport(),
        )

        match = session.query(Match).one()
        assert match.home_goals is None
        assert match.status == "scheduled"

    def test_la_saison_manquante_est_creee(self, session, premier_league):
        """2026/27 n'existe dans aucune base d'hier."""
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")

        _ecrire_match(session, _normalise(), Rapport())

        saison = session.query(Season).one()
        assert saison.season_name == "2627"
        assert saison.status == "in_progress"

    def test_une_equipe_existante_est_reutilisee_quel_que_soit_son_fournisseur(
        self, session, premier_league
    ):
        """Le nom canonique est l'identité partagée : filtrer sur `provider`
        créerait un second Brest, sans ses douze saisons."""
        arsenal = _equipe(session, "Arsenal")
        chelsea = _equipe(session, "Chelsea")
        rapport = Rapport()

        _ecrire_match(session, _normalise(), rapport)

        match = session.query(Match).one()
        assert match.home_team_id == arsenal.id
        assert match.away_team_id == chelsea.id
        assert session.query(Team).count() == 2
        assert rapport.equipes_creees == []

    def test_un_promu_inconnu_est_cree_et_signale(self, session, premier_league):
        """Créer est permis ; le faire en silence ne l'est pas : Dixon-Coles
        estimera mal un club sans historique."""
        _equipe(session, "Arsenal")
        rapport = Rapport()

        _ecrire_match(session, _normalise(exterieur="Coventry"), rapport)

        assert rapport.equipes_creees == ["Coventry"]
        assert session.query(Team).filter_by(canonical_name="Coventry").one()


class TestNonRegression:
    def test_relancer_l_import_ne_duplique_rien(self, session, premier_league):
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")
        rapport = Rapport()

        _ecrire_match(session, _normalise(), rapport)
        _ecrire_match(session, _normalise(), rapport)

        assert session.query(Match).count() == 1
        assert rapport.matchs_crees == 1
        assert rapport.matchs_inchanges == 1

    def test_un_match_deja_importe_par_football_data_n_est_pas_duplique(
        self, session, premier_league
    ):
        """Les deux sources ne se recouvrent pas aujourd'hui ; rien ne garantit
        qu'elles ne se recouvriront jamais."""
        arsenal = _equipe(session, "Arsenal")
        chelsea = _equipe(session, "Chelsea")
        session.add(
            Match(
                provider="football_data",
                provider_match_id="fd_E0_2627_abc",
                competition_id=premier_league.id,
                match_date=datetime(2026, 9, 18),
                home_team_id=arsenal.id,
                away_team_id=chelsea.id,
                status="completed",
                home_goals=2,
                away_goals=1,
            )
        )
        session.flush()

        _ecrire_match(session, _normalise(), Rapport())

        assert session.query(Match).count() == 1

    def test_un_resultat_deja_en_base_n_est_jamais_reecrit(self, session, premier_league):
        """D-10 : personne ne modifie un chiffre, l'import pas davantage."""
        arsenal = _equipe(session, "Arsenal")
        chelsea = _equipe(session, "Chelsea")
        session.add(
            Match(
                provider="football_data",
                provider_match_id="fd_E0_2627_abc",
                competition_id=premier_league.id,
                match_date=datetime(2026, 9, 18),
                home_team_id=arsenal.id,
                away_team_id=chelsea.id,
                status="completed",
                home_goals=2,
                away_goals=1,
            )
        )
        session.flush()

        _ecrire_match(session, _normalise(buts=(5, 0)), Rapport())

        match = session.query(Match).one()
        assert (match.home_goals, match.away_goals) == (2, 1)

    def test_un_match_a_venir_recoit_son_score_une_fois_joue(self, session, premier_league):
        """C'est la seule mise à jour de score permise : la case était vide."""
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")
        rapport = Rapport()
        _ecrire_match(
            session,
            _normalise(statut="scheduled", buts=(None, None), mi_temps=(None, None)),
            rapport,
        )

        _ecrire_match(session, _normalise(), rapport)

        match = session.query(Match).one()
        assert (match.home_goals, match.away_goals) == (2, 1)
        assert match.status == "completed"
        assert rapport.matchs_mis_a_jour == 1


def _cote(selection="home", cote=2.0, releve=datetime(2026, 9, 18, 21, 51, 33), bookmaker="Bet365"):
    return CoteNormalisee(
        provider_match_id="af_1",
        bookmaker=bookmaker,
        marche="1N2",
        selection=selection,
        cote=cote,
        releve_le=releve,
        cloture=False,
    )


class TestEcritureDesCotes:
    @pytest.fixture
    def match_en_base(self, session, premier_league):
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")
        _ecrire_match(
            session,
            _normalise(statut="scheduled", buts=(None, None), mi_temps=(None, None)),
            Rapport(),
        )
        return session.query(Match).one()

    def test_les_releves_sont_ecrits(self, session, match_en_base):
        rapport = Rapport()

        _ecrire_cotes(session, [_cote("home"), _cote("draw", 3.5)], rapport)

        assert rapport.cotes_inserees == 2
        assert session.query(OddsSnapshot).count() == 2

    def test_un_releve_pre_match_n_est_pas_une_cloture(self, session, match_en_base):
        """Tout le rendement du projet est mesuré contre la cote de clôture."""
        _ecrire_cotes(session, [_cote()], Rapport())

        assert session.query(OddsSnapshot).one().is_closing is False

    def test_la_source_est_tracee(self, session, match_en_base):
        _ecrire_cotes(session, [_cote()], Rapport())

        assert session.query(OddsSnapshot).one().source == "api_football"

    def test_le_meme_releve_n_est_pas_insere_deux_fois(self, session, match_en_base):
        rapport = Rapport()

        _ecrire_cotes(session, [_cote()], rapport)
        _ecrire_cotes(session, [_cote()], rapport)

        assert session.query(OddsSnapshot).count() == 1
        assert rapport.cotes_deja_presentes == 1

    def test_un_releve_plus_tardif_s_ajoute(self, session, match_en_base):
        """Deux points dans le temps, c'est le mouvement de cote que le projet
        attend depuis le premier jour."""
        rapport = Rapport()

        _ecrire_cotes(session, [_cote(releve=datetime(2026, 9, 18, 21, 0))], rapport)
        _ecrire_cotes(session, [_cote(releve=datetime(2026, 9, 19, 10, 0))], rapport)

        assert session.query(OddsSnapshot).count() == 2

    def test_une_cote_sans_match_en_base_est_signalee_pas_ecrite(self, session, premier_league):
        rapport = Rapport()

        _ecrire_cotes(session, [_cote()], rapport)

        assert session.query(OddsSnapshot).count() == 0
        assert rapport.ignores[0]["motif"] == "cote sans match en base"


class ClientFactice:
    """Rend des réponses figées, et compte les appels. Aucun réseau."""

    def __init__(self, reponses: dict):
        self.reponses = reponses
        self.appels: list[tuple[str, dict]] = []

    async def get(self, endpoint, params=None, **_):
        self.appels.append((endpoint, dict(params or {})))
        return self.reponses.get(endpoint, {"response": []})


def _fixture_brute(identifiant=1, statut="NS", buts=(None, None)):
    return {
        "fixture": {
            "id": identifiant,
            "referee": None,
            "date": "2026-09-19T14:00:00+00:00",
            "status": {"short": statut},
        },
        "league": {"id": 39, "name": "Premier League", "season": 2026},
        "teams": {"home": {"id": 42, "name": "Arsenal"}, "away": {"id": 49, "name": "Chelsea"}},
        "goals": {"home": buts[0], "away": buts[1]},
        "score": {"halftime": {"home": None, "away": None}},
    }


class TestPipelineComplet:
    def test_import_des_matchs_d_une_ligue(self, session, premier_league):
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")
        client = ClientFactice({"fixtures": {"response": [_fixture_brute()]}})

        rapport = asyncio.run(importer_matchs(session, client, 2026, codes=["E0"]))

        assert rapport.matchs_crees == 1
        assert client.appels == [("fixtures", {"league": 39, "season": 2026})]

    def test_dry_run_n_ecrit_rien(self, session, premier_league):
        _equipe(session, "Arsenal")
        _equipe(session, "Chelsea")
        client = ClientFactice({"fixtures": {"response": [_fixture_brute()]}})

        rapport = asyncio.run(importer_matchs(session, client, 2026, codes=["E0"], dry_run=True))

        assert rapport.matchs_crees == 0
        assert session.query(Match).count() == 0

    def test_les_cotes_hors_perimetre_sont_ignorees(self, session, premier_league):
        """L'endpoint par date rend tous les championnats du monde ; le projet
        n'en suit que cinq."""
        client = ClientFactice(
            {
                "odds": {
                    "paging": {"total": 1},
                    "response": [
                        {
                            "league": {"id": 999},
                            "fixture": {"id": 7},
                            "update": "2026-09-18T21:00:00+00:00",
                            "bookmakers": [],
                        }
                    ],
                }
            }
        )

        rapport = asyncio.run(importer_cotes(session, client, ["2026-09-19"]))

        assert rapport.cotes_inserees == 0
