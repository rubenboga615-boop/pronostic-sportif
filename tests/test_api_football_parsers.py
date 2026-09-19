"""Tests des traductions API-Football -> structures de la base.

Les échantillons reproduisent la forme réelle des réponses, relevée le
19/09/2026 sur le compte Pro : c'est elle qui fait foi, pas la documentation.
"""

from datetime import datetime

import pytest

from collectors.api_football.parsers import (
    CoteNormalisee,
    date_sans_fuseau,
    parser_cotes,
    parser_fixture,
    parser_fixtures,
    saison_football_data,
    statut_normalise,
    traduire_equipe,
)


def fixture_brute(
    identifiant=1557408,
    statut="FT",
    buts=(3, 0),
    mi_temps=(0, 0),
    domicile="Brentford",
    exterieur="Chelsea",
    date="2026-09-18T19:00:00+00:00",
    saison=2026,
):
    return {
        "fixture": {
            "id": identifiant,
            "referee": "Andrew Madley",
            "date": date,
            "status": {"long": "Match Finished", "short": statut, "elapsed": 90},
        },
        "league": {"id": 39, "name": "Premier League", "season": saison},
        "teams": {"home": {"id": 55, "name": domicile}, "away": {"id": 49, "name": exterieur}},
        "goals": {"home": buts[0], "away": buts[1]},
        "score": {
            "halftime": {"home": mi_temps[0], "away": mi_temps[1]},
            "fulltime": {"home": buts[0], "away": buts[1]},
        },
    }


class TestConversions:
    def test_saison_api_vers_football_data(self):
        assert saison_football_data(2026) == "2627"
        assert saison_football_data(2019) == "1920"

    def test_passage_de_siecle(self):
        """1999/2000 s'écrit 9900 chez Football-Data, pas 99100."""
        assert saison_football_data(1999) == "9900"

    def test_la_date_perd_son_fuseau_mais_pas_son_instant(self):
        """Un décalage horaire ne doit pas déplacer le match d'une heure."""
        assert date_sans_fuseau("2026-09-18T21:00:00+02:00") == datetime(2026, 9, 18, 19, 0)
        assert date_sans_fuseau("2026-09-18T19:00:00+00:00") == datetime(2026, 9, 18, 19, 0)

    def test_la_date_rendue_est_naive(self):
        """Une date avec fuseau en base casserait toute comparaison SQLite."""
        assert date_sans_fuseau("2026-09-18T19:00:00+00:00").tzinfo is None

    @pytest.mark.parametrize(
        ("api", "attendu"),
        [("FT", "completed"), ("AET", "completed"), ("NS", "scheduled"), ("1H", "in_play")],
    )
    def test_statuts_traduits(self, api, attendu):
        assert statut_normalise(api) == attendu

    @pytest.mark.parametrize("api", ["PST", "CANC", "ABD", "WO"])
    def test_statuts_sans_resultat_refuses(self, api):
        """Un match reporté ou annulé n'a rien à faire en base."""
        assert statut_normalise(api) is None


class TestTraductionDesEquipes:
    def test_le_registre_traduit(self):
        assert traduire_equipe("Stade Brestois 29", {"Stade Brestois 29": "Brest"}) == "Brest"

    def test_un_nom_absent_passe_tel_quel(self):
        """Le registre ne consigne que les écarts : « Arsenal » n'y figure pas."""
        assert traduire_equipe("Arsenal", {"Stade Brestois 29": "Brest"}) == "Arsenal"


class TestParserFixture:
    def test_match_joue(self):
        match = parser_fixture(fixture_brute(), {}, "E0")
        assert match.provider_match_id == "af_1557408"
        assert (match.buts_domicile, match.buts_exterieur) == (3, 0)
        assert (match.buts_mt_domicile, match.buts_mt_exterieur) == (0, 0)
        assert match.saison == "2627"
        assert match.statut == "completed"
        assert match.joue is True
        assert match.arbitre == "Andrew Madley"

    def test_match_a_venir_sans_score(self):
        brut = fixture_brute(statut="NS", buts=(None, None), mi_temps=(None, None))
        match = parser_fixture(brut, {}, "E0")
        assert match.statut == "scheduled"
        assert match.buts_domicile is None
        assert match.joue is False

    def test_les_noms_sont_traduits(self):
        brut = fixture_brute(domicile="Stade Brestois 29", exterieur="Estac Troyes")
        match = parser_fixture(brut, {"Stade Brestois 29": "Brest", "Estac Troyes": "Troyes"}, "F1")
        assert (match.domicile, match.exterieur) == ("Brest", "Troyes")

    def test_statut_non_importable_refuse(self):
        with pytest.raises(ValueError, match="statut non importable"):
            parser_fixture(fixture_brute(statut="PST"), {}, "E0")


class TestParserLot:
    def test_les_rejets_sont_consignes_et_le_reste_passe(self):
        lot = [
            fixture_brute(identifiant=1),
            fixture_brute(identifiant=2, statut="CANC"),
            fixture_brute(identifiant=3, statut="NS", buts=(None, None), mi_temps=(None, None)),
        ]
        resultat = parser_fixtures(lot, {}, "E0")
        assert [m.provider_match_id for m in resultat.matchs] == ["af_1", "af_3"]
        assert len(resultat.ignores) == 1
        assert resultat.ignores[0]["fixture_id"] == 2

    def test_match_pretendu_joue_sans_score_est_ecarte(self):
        """Un « FT » sans buts est une donnée fausse, pas un match à importer."""
        lot = [fixture_brute(identifiant=7, statut="FT", buts=(None, None))]
        resultat = parser_fixtures(lot, {}, "E0")
        assert resultat.matchs == []
        assert "sans score" in resultat.ignores[0]["motif"]


def _bet(nom, values):
    return {"id": 0, "name": nom, "values": values}


def entree_huit_marches(bookmaker="Bet365"):
    """Les huit marchés de la Phase 1, tels que le fournisseur les livre."""
    trois = [
        {"value": v, "odd": o} for v, o in (("Home", "2.00"), ("Draw", "3.50"), ("Away", "3.60"))
    ]
    dc = [
        {"value": v, "odd": o}
        for v, o in (("Home/Draw", "1.30"), ("Home/Away", "1.25"), ("Draw/Away", "1.70"))
    ]
    ou = [
        {"value": f"{sens} {ligne}", "odd": "1.80"}
        for ligne in ("0.5", "1.5", "2.5", "3.5")
        for sens in ("Over", "Under")
    ]
    return {
        "league": {"id": 39},
        "fixture": {"id": 1557416},
        "update": "2026-09-18T21:51:33+00:00",
        "bookmakers": [
            {
                "id": 8,
                "name": bookmaker,
                "bets": [
                    _bet("Match Winner", trois),
                    _bet("Double Chance", dc),
                    _bet("Goals Over/Under", ou),
                    _bet(
                        "Both Teams Score",
                        [{"value": "Yes", "odd": "1.90"}, {"value": "No", "odd": "1.90"}],
                    ),
                    _bet(
                        "Highest Scoring Half",
                        [
                            {"value": "1st Half", "odd": "2.80"},
                            {"value": "2nd Half", "odd": "2.00"},
                            {"value": "Draw", "odd": "3.60"},
                        ],
                    ),
                    _bet("First Half Winner", trois),
                    _bet("Double Chance - First Half", dc),
                    _bet("Goals Over/Under First Half", ou),
                    _bet("Exact Score", [{"value": "1:0", "odd": "7.5"}]),
                ],
            }
        ],
    }


def entree_cotes(values_1n2=None, values_ou=None, bookmaker="Bet365"):
    values_1n2 = (
        values_1n2
        if values_1n2 is not None
        else [
            {"value": "Home", "odd": "2.00"},
            {"value": "Draw", "odd": "3.50"},
            {"value": "Away", "odd": "3.60"},
        ]
    )
    values_ou = (
        values_ou
        if values_ou is not None
        else [
            {"value": "Over 1.5", "odd": "1.22"},
            {"value": "Over 2.5", "odd": "1.73"},
            {"value": "Under 2.5", "odd": "2.10"},
        ]
    )
    return {
        "league": {"id": 39},
        "fixture": {"id": 1557416},
        "update": "2026-09-18T21:51:33+00:00",
        "bookmakers": [
            {
                "id": 8,
                "name": bookmaker,
                "bets": [
                    {"id": 1, "name": "Match Winner", "values": values_1n2},
                    {"id": 5, "name": "Goals Over/Under", "values": values_ou},
                    {"id": 12, "name": "Exact Score", "values": [{"value": "1:0", "odd": "7.5"}]},
                ],
            }
        ],
    }


class TestParserCotes:
    def test_les_deux_marches_utiles_sont_retenus(self):
        releves = parser_cotes(entree_cotes())
        assert {(r.marche, r.selection) for r in releves} == {
            ("1N2", "home"),
            ("1N2", "draw"),
            ("1N2", "away"),
            ("over_under", "over_2.5"),
            ("over_under", "under_2.5"),
        }

    def test_les_marches_hors_perimetre_sont_ignores(self):
        """Le fournisseur en livre 183 ; le backtest n'en sait valoriser que deux."""
        assert all(r.marche in ("1N2", "over_under") for r in parser_cotes(entree_cotes()))

    def test_les_codes_de_selection_sont_ceux_de_la_base(self):
        """`over_2.5` et non `Over 2.5` : sinon les cotes sont invisibles au backtest."""
        releves = parser_cotes(entree_cotes())
        over = next(r for r in releves if r.marche == "over_under" and r.cote == 1.73)
        assert over.selection == "over_2.5"

    def test_serie_1n2_incomplete_ecartee_entiere(self):
        """Sans les trois cotes, la marge du bookmaker n'est pas calculable."""
        partielle = [{"value": "Home", "odd": "2.00"}, {"value": "Draw", "odd": "3.50"}]
        releves = parser_cotes(entree_cotes(values_1n2=partielle))
        assert all(r.marche != "1N2" for r in releves)
        assert any(r.marche == "over_under" for r in releves)

    def test_cote_non_pariable_ecartee(self):
        """Une cote à 1,00 ou absente ne rapporte rien : la série entière tombe."""
        invalide = [
            {"value": "Home", "odd": "1.00"},
            {"value": "Draw", "odd": "3.50"},
            {"value": "Away", "odd": "3.60"},
        ]
        assert all(r.marche != "1N2" for r in parser_cotes(entree_cotes(values_1n2=invalide)))

    def test_horodatage_du_releve_conserve(self):
        releve = parser_cotes(entree_cotes())[0]
        assert releve.releve_le == datetime(2026, 9, 18, 21, 51, 33)

    def test_aucun_releve_n_est_une_cloture(self):
        """La cote de clôture est celle du coup d'envoi ; un relevé pré-match ne l'est pas."""
        assert all(r.cloture is False for r in parser_cotes(entree_cotes()))

    def test_le_match_est_identifie_comme_a_l_import_des_fixtures(self):
        """Les deux parseurs doivent produire la même clé, sinon les cotes sont orphelines."""
        cote: CoteNormalisee = parser_cotes(entree_cotes())[0]
        match = parser_fixture(fixture_brute(identifiant=1557416), {}, "E0")
        assert cote.provider_match_id == match.provider_match_id


class TestLesHuitMarchesDeLaPhase1:
    """Six de ces marchés n'avaient jamais eu de prix : Football-Data n'en
    publie que deux. La limite venait de la source, pas du moteur."""

    def test_les_huit_marches_sont_retenus(self):
        marches = {r.marche for r in parser_cotes(entree_huit_marches())}
        assert marches == {
            "1N2",
            "double_chance",
            "over_under",
            "BTTS",
            "most_productive_half",
            "1N2_1H",
            "double_chance_1H",
            "over_under_1H",
        }

    @pytest.mark.parametrize(
        ("marche", "selections"),
        [
            ("double_chance", {"home_or_draw", "home_or_away", "draw_or_away"}),
            ("BTTS", {"yes", "no"}),
            ("most_productive_half", {"first_half", "second_half", "equal"}),
            ("1N2_1H", {"home", "draw", "away"}),
            (
                "over_under_1H",
                {
                    "over_0.5",
                    "under_0.5",
                    "over_1.5",
                    "under_1.5",
                    "over_2.5",
                    "under_2.5",
                    "over_3.5",
                    "under_3.5",
                },
            ),
        ],
    )
    def test_les_codes_de_selection_sont_ceux_du_moteur(self, marche, selections):
        """Un code qui diverge de `market_derivation.py` laisse l'edge à zéro,
        sans qu'aucune erreur ne soit levée."""
        releves = parser_cotes(entree_huit_marches())
        assert {r.selection for r in releves if r.marche == marche} == selections

    def test_la_phase_2_reste_dehors(self):
        """`knowledge.md` la désactive : le score exact n'a rien à faire en base."""
        assert all(r.marche != "Exact Score" for r in parser_cotes(entree_huit_marches()))

    def test_une_ligne_over_under_incomplete_ne_fait_pas_tomber_les_autres(self):
        """Chaque ligne est un marché : perdre la 2,5, la plus liquide du
        football, parce que la 3,5 manque serait absurde."""
        entree = entree_huit_marches()
        pari = next(b for b in entree["bookmakers"][0]["bets"] if b["name"] == "Goals Over/Under")
        pari["values"] = [
            {"value": "Over 2.5", "odd": "1.73"},
            {"value": "Under 2.5", "odd": "2.10"},
            {"value": "Over 3.5", "odd": "2.75"},
        ]

        selections = {r.selection for r in parser_cotes(entree) if r.marche == "over_under"}

        assert selections == {"over_2.5", "under_2.5"}

    def test_une_serie_a_trois_issues_incomplete_tombe_entiere(self):
        """Sans les trois issues, la marge du bookmaker n'est pas calculable."""
        entree = entree_huit_marches()
        pari = next(b for b in entree["bookmakers"][0]["bets"] if b["name"] == "Double Chance")
        pari["values"] = [{"value": "Home/Draw", "odd": "1.30"}]

        assert all(r.marche != "double_chance" for r in parser_cotes(entree))
