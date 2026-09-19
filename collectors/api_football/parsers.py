"""Traduire les réponses d'API-Football en structures que la base sait écrire.

Ce module ne touche ni au réseau ni à la base : il transforme du JSON en
dataclasses, et c'est tout. C'est ce qui le rend testable sur des échantillons
figés, sans clé ni quota.

Trois traductions valent d'être explicitées, parce qu'elles sont le lieu où un
import se trompe sans rien signaler.

**Les noms d'équipes passent par le registre.** API-Football écrit « Stade
Brestois 29 » là où la base dit « Brest ». Le registre ne consigne que les
écarts : un nom absent n'est donc pas une erreur, c'est le cas ordinaire. Savoir
si l'équipe existe vraiment demande la base, et cette vérification appartient
donc au pipeline d'écriture, pas ici.

**Les dates arrivent en UTC avec fuseau, la base les stocke sans.** Mélanger
des `datetime` avec et sans fuseau dans une colonne SQLite produit des
comparaisons fausses — et le pipeline de features comme le backtest comparent
des dates en permanence. La conversion est donc faite ici, une fois.

**Un match à venir n'a pas de cote de clôture.** `is_closing` reste faux pour
tout relevé pré-match : la cote de clôture est celle du coup d'envoi, et elle
ne peut être connue qu'en relevant à nouveau juste avant. Prétendre le
contraire fausserait tout rendement futur, que le projet mesure justement
contre les cotes de clôture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# Statuts du fournisseur, rangés par ce qu'ils signifient pour la base.
# https://www.api-football.com/documentation-v3#tag/Fixtures
STATUTS_JOUES = {"FT", "AET", "PEN"}
STATUTS_A_VENIR = {"TBD", "NS"}
STATUTS_EN_COURS = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"}
STATUTS_SANS_RESULTAT = {"PST", "CANC", "ABD", "AWD", "WO"}

# Les huit marchés de la Phase 1, et la traduction de leurs sélections vers les
# codes que le moteur écrit dans `predictions`.
#
# Ces huit-là sont calculés depuis la matrice de scores depuis le premier jour,
# et six n'avaient jamais été confrontés à un prix : Football-Data ne publie que
# le 1N2 et l'Over/Under 2,5. Ce n'était pas une limite du modèle, c'était une
# limite de la source — et elle tombe ici, le fournisseur livrant les huit chez
# un même bookmaker. Le marché le mieux classé par le moteur, l'Over/Under de
# première mi-temps à 0,770 d'AUC, n'avait ainsi jamais été mesuré en rendement.
#
# Les codes de sélection ne s'inventent pas : ils doivent être exactement ceux
# de `models/market_derivation.py`, sans quoi la valorisation ne rapproche rien
# et l'edge reste nul sans qu'aucune erreur ne soit levée.
_1N2 = {"Home": "home", "Draw": "draw", "Away": "away"}
_DOUBLE_CHANCE = {
    "Home/Draw": "home_or_draw",
    "Home/Away": "home_or_away",
    "Draw/Away": "draw_or_away",
}
_OVER_UNDER = {
    f"{sens} {ligne}": f"{sens.lower()}_{ligne}"
    for ligne in ("0.5", "1.5", "2.5", "3.5")
    for sens in ("Over", "Under")
}
_BTTS = {"Yes": "yes", "No": "no"}
_MI_TEMPS_PROLIFIQUE = {"1st Half": "first_half", "2nd Half": "second_half", "Draw": "equal"}

# Marché du fournisseur -> (marché en base, traduction des sélections).
MARCHES = {
    "Match Winner": ("1N2", _1N2),
    "Double Chance": ("double_chance", _DOUBLE_CHANCE),
    "Goals Over/Under": ("over_under", _OVER_UNDER),
    "Both Teams Score": ("BTTS", _BTTS),
    "Highest Scoring Half": ("most_productive_half", _MI_TEMPS_PROLIFIQUE),
    "First Half Winner": ("1N2_1H", _1N2),
    "Double Chance - First Half": ("double_chance_1H", _DOUBLE_CHANCE),
    "Goals Over/Under First Half": ("over_under_1H", _OVER_UNDER),
}

# Un Over/Under n'est complet qu'à la ligne : « Over 2.5 » sans « Under 2.5 »
# ne permet pas de calculer la marge du bookmaker, alors que « Over 1.5 » ne
# manque à personne. Les séries de ces marchés se vérifient donc par paires,
# pas sur le nombre total de sélections.
MARCHES_PAR_LIGNE = {"over_under", "over_under_1H"}


@dataclass
class MatchNormalise:
    """Un match, prêt à être écrit dans `matches`."""

    provider_match_id: str
    code_ligue: str
    saison: str
    date: datetime
    domicile: str
    exterieur: str
    statut: str
    buts_domicile: int | None = None
    buts_exterieur: int | None = None
    buts_mt_domicile: int | None = None
    buts_mt_exterieur: int | None = None
    arbitre: str | None = None

    @property
    def joue(self) -> bool:
        return self.statut == "completed"


@dataclass
class CoteNormalisee:
    """Un relevé de cote, prêt à être écrit dans `odds_snapshots`."""

    provider_match_id: str
    bookmaker: str
    marche: str
    selection: str
    cote: float
    releve_le: datetime | None = None
    cloture: bool = False


@dataclass
class ResultatParsage:
    """Ce qu'un lot de fixtures a donné, succès et rejets ensemble."""

    matchs: list[MatchNormalise] = field(default_factory=list)
    ignores: list[dict] = field(default_factory=list)

    def ignorer(self, motif: str, **details) -> None:
        self.ignores.append({"motif": motif, **details})


def saison_football_data(saison_api: int) -> str:
    """``2026`` -> ``"2627"``. L'API désigne une saison par son année de début."""
    debut = int(saison_api) % 100
    return f"{debut:02d}{(debut + 1) % 100:02d}"


def date_sans_fuseau(iso: str) -> datetime:
    """Convertir une date ISO du fournisseur en UTC, puis retirer le fuseau.

    Le fournisseur répond en UTC lorsqu'aucun fuseau n'est demandé, mais il
    horodate avec l'offset explicite. La base, elle, contient 17 251 dates sans
    fuseau : en insérer avec ferait échouer toute comparaison SQLite entre les
    deux familles, silencieusement et dans les deux sens.
    """
    horodatage = datetime.fromisoformat(iso)
    if horodatage.tzinfo is not None:
        horodatage = horodatage.astimezone(UTC).replace(tzinfo=None)
    return horodatage


def statut_normalise(statut_api: str) -> str | None:
    """Traduire un statut du fournisseur, ou ``None`` s'il n'est pas importable."""
    if statut_api in STATUTS_JOUES:
        return "completed"
    if statut_api in STATUTS_A_VENIR:
        return "scheduled"
    if statut_api in STATUTS_EN_COURS:
        return "in_play"
    return None


def traduire_equipe(nom: str, table: dict[str, str]) -> str:
    """Nom du fournisseur -> nom canonique. Sans correspondance, le nom passe tel quel.

    Beaucoup de noms sont déjà identiques des deux côtés — « Arsenal »,
    « Liverpool », « Napoli ». Le registre ne consigne que les écarts, et
    l'absence d'entrée n'est donc pas une erreur : c'est le cas le plus
    fréquent. La vérification qu'une équipe existe bien en base a lieu à
    l'écriture, là où la base est disponible.
    """
    return table.get(nom, nom)


def parser_fixture(fixture: dict, table_equipes: dict[str, str], code_ligue: str) -> MatchNormalise:
    """Traduire un élément de la réponse ``fixtures``.

    Raises:
        ValueError: statut non importable (match reporté, annulé, sur tapis).
    """
    infos = fixture["fixture"]
    statut_api = infos["status"]["short"]
    statut = statut_normalise(statut_api)
    if statut is None:
        raise ValueError(f"statut non importable : {statut_api}")

    buts = fixture.get("goals") or {}
    mi_temps = (fixture.get("score") or {}).get("halftime") or {}

    return MatchNormalise(
        provider_match_id=f"af_{infos['id']}",
        code_ligue=code_ligue,
        saison=saison_football_data(fixture["league"]["season"]),
        date=date_sans_fuseau(infos["date"]),
        domicile=traduire_equipe(fixture["teams"]["home"]["name"], table_equipes),
        exterieur=traduire_equipe(fixture["teams"]["away"]["name"], table_equipes),
        statut=statut,
        buts_domicile=buts.get("home"),
        buts_exterieur=buts.get("away"),
        buts_mt_domicile=mi_temps.get("home"),
        buts_mt_exterieur=mi_temps.get("away"),
        arbitre=infos.get("referee"),
    )


def parser_fixtures(
    reponse: list[dict], table_equipes: dict[str, str], code_ligue: str
) -> ResultatParsage:
    """Traduire un lot de fixtures, en consignant ce qui a été écarté."""
    resultat = ResultatParsage()
    for fixture in reponse:
        try:
            match = parser_fixture(fixture, table_equipes, code_ligue)
        except (ValueError, KeyError, TypeError) as erreur:
            resultat.ignorer(
                str(erreur),
                fixture_id=(fixture.get("fixture") or {}).get("id"),
                ligue=code_ligue,
            )
            continue
        if match.statut == "completed" and match.buts_domicile is None:
            resultat.ignorer(
                "match donné pour joué, sans score",
                fixture_id=match.provider_match_id,
                ligue=code_ligue,
            )
            continue
        resultat.matchs.append(match)
    return resultat


def _valeur_numerique(brut: str | float | None) -> float | None:
    """Une cote du fournisseur arrive en chaîne. Refuser tout ce qui n'est pas pariable."""
    if brut is None:
        return None
    try:
        cote = float(brut)
    except (TypeError, ValueError):
        return None
    return cote if cote > 1.0 else None


def _series_completes(marche: str, serie: dict[str, float], traduction: dict) -> dict[str, float]:
    """Ne garder que ce qui est valorisable, et rien d'autre.

    Une série incomplète n'est pas exploitable : sans toutes les issues, la
    marge du bookmaker n'est pas calculable, et `evaluation/pricing.py` écarte
    de toute façon le bookmaker au marché incomplet.

    Les Over/Under font exception au découpage : chaque ligne est un marché à
    part entière. Une ligne 2,5 complète reste bonne même si le bookmaker ne
    cote pas la 3,5 — les rejeter ensemble perdrait la ligne la plus liquide
    du football pour une ligne marginale.
    """
    if marche not in MARCHES_PAR_LIGNE:
        return serie if len(serie) == len(traduction) else {}

    retenues: dict[str, float] = {}
    for selection, cote in serie.items():
        sens, ligne = selection.split("_", 1)
        oppose = f"{'under' if sens == 'over' else 'over'}_{ligne}"
        if oppose in serie:
            retenues[selection] = cote
    return retenues


def parser_cotes(entree: dict) -> list[CoteNormalisee]:
    """Traduire une entrée de la réponse ``odds`` en relevés.

    Les huit marchés de la Phase 1 sont retenus (voir :data:`MARCHES`). Le
    fournisseur en livre 183 ; les autres appartiennent à la Phase 2, désactivée
    par `knowledge.md`, ou à des marchés hors périmètre.
    """
    identifiant = f"af_{entree['fixture']['id']}"
    releve_le = date_sans_fuseau(entree["update"]) if entree.get("update") else None

    releves: list[CoteNormalisee] = []
    for bookmaker in entree.get("bookmakers") or []:
        nom = bookmaker.get("name")
        if not nom:
            continue
        for pari in bookmaker.get("bets") or []:
            correspondance = MARCHES.get(pari.get("name"))
            if correspondance is None:
                continue
            marche, traduction = correspondance

            brute: dict[str, float] = {}
            for valeur in pari.get("values") or []:
                selection = traduction.get(str(valeur.get("value")))
                cote = _valeur_numerique(valeur.get("odd"))
                if selection and cote:
                    brute[selection] = cote

            serie = _series_completes(marche, brute, traduction)
            if not serie:
                continue

            releves.extend(
                CoteNormalisee(
                    provider_match_id=identifiant,
                    bookmaker=nom,
                    marche=marche,
                    selection=selection,
                    cote=cote,
                    releve_le=releve_le,
                    cloture=False,
                )
                for selection, cote in serie.items()
            )
    return releves
