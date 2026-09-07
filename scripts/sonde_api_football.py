#!/usr/bin/env python3
"""Mesurer ce que l'abonnement API-Football livre réellement.

À lancer **avant** d'écrire le moindre collecteur. Une vingtaine d'appels sur
les 7 500 quotidiens, pour répondre à des questions dont dépend toute la suite :

- les identifiants de ligue du dépôt sont-ils les bons ?
- quels endpoints sont couverts pour chaque championnat et chaque saison ?
- combien de bookmakers, et sur quels marchés ?
- jusqu'où remonte l'historique des cotes ?
- les blessures sont-elles renseignées, et à quelle fraîcheur ?
- combien de requêtes le fournisseur décompte-t-il vraiment ?

Sans cette mesure, on construit trois jours durant sur des suppositions. Avec,
on sait — et le coût est de 0,3 % du quota d'une journée.

**Effet de bord utile** : la sonde écrit les listes de noms d'équipes de chaque
championnat, au format attendu par `scripts/generer_correspondances.py`. C'est
la matière première du registre de correspondances, sans laquelle aucun
collecteur ne peut écrire en base.

Usage :
    python scripts/sonde_api_football.py
    python scripts/sonde_api_football.py --saison 2526 --sortie rapports/
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from collectors.api_football.client import ClientApiFootball
from collectors.api_football.erreurs import ApiFootballError, CleManquanteError
from collectors.api_football.ligues import LIGUES, saison_api
from collectors.api_football.quota import SuiviQuota

# La sonde ne doit jamais déraper : ce plafond est sa promesse.
PLAFOND_APPELS = 25


class Sonde:
    """Enchaîne les mesures et accumule un rapport."""

    def __init__(self, client: ClientApiFootball, saison: str) -> None:
        self.client = client
        self.saison_fd = saison
        self.saison = saison_api(saison)
        self.rapport: dict = {
            "_horodatage": datetime.now(UTC).isoformat(),
            "saison_testee": {"football_data": saison, "api_football": self.saison},
        }
        self.equipes: dict[str, list[str]] = {}

    async def _appel(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Un appel, en laissant passer les échecs : une mesure ratée n'arrête
        pas les autres. C'est le but d'une sonde de continuer et de rapporter."""
        try:
            return await self.client.get(endpoint, params or {}, duree_cache_heures=1)
        except ApiFootballError as erreur:
            logger.warning(f"{endpoint} {params or ''} → {type(erreur).__name__}: {erreur}")
            return None

    # ── Mesures ──────────────────────────────────────────────────────────

    async def statut(self) -> None:
        """Plan souscrit, quota du jour, échéance de l'abonnement."""
        enveloppe = await self._appel("status")
        if not enveloppe:
            self.rapport["statut"] = {"erreur": "endpoint /status injoignable"}
            return

        contenu = enveloppe.get("response") or {}
        abonnement = contenu.get("subscription") or {}
        requetes = contenu.get("requests") or {}
        self.rapport["statut"] = {
            "plan": abonnement.get("plan"),
            "actif": abonnement.get("active"),
            "fin": abonnement.get("end"),
            "requetes_du_jour": requetes.get("current"),
            "quota_journalier": requetes.get("limit_day"),
        }

    async def ligues(self) -> None:
        """Vérifier chaque identifiant, et relever la couverture par endpoint.

        La couverture est l'information la plus précieuse de toute la sonde :
        le fournisseur y déclare, saison par saison, quels endpoints portent
        réellement des données. Un `odds: false` sur une saison ancienne règle
        d'avance la question de la profondeur historique.
        """
        resultats = {}
        for code, (ident, nom_attendu, pays_attendu) in LIGUES.items():
            enveloppe = await self._appel("leagues", {"id": ident, "season": self.saison})
            if not enveloppe:
                resultats[code] = {"erreur": "injoignable"}
                continue

            reponses = ClientApiFootball.reponses(enveloppe)
            if not reponses:
                resultats[code] = {"erreur": "aucune donnée pour cette saison"}
                continue

            bloc = reponses[0]
            ligue = bloc.get("league") or {}
            pays = bloc.get("country") or {}
            saisons = bloc.get("seasons") or [{}]
            couverture = saisons[0].get("coverage") or {}

            nom, pays_nom = ligue.get("name"), pays.get("name")
            concorde = nom == nom_attendu and pays_nom == pays_attendu

            resultats[code] = {
                "identifiant": ident,
                "nom": nom,
                "pays": pays_nom,
                "identifiant_confirme": concorde,
                "couverture": couverture,
            }
            if not concorde:
                logger.error(
                    f"{code} : l'identifiant {ident} désigne {nom!r} ({pays_nom}), "
                    f"et non {nom_attendu!r} ({pays_attendu}). "
                    f"Corrigez collectors/api_football/ligues.py AVANT tout import."
                )
        self.rapport["ligues"] = resultats

    async def noms_d_equipes(self) -> None:
        """Récupérer les noms tels qu'API-Football les écrit.

        C'est la matière première du registre de correspondances. Sans elle,
        aucun collecteur ne peut écrire en base sans risquer de dupliquer les
        équipes et de scinder douze saisons d'historique.
        """
        for code, (ident, _, _) in LIGUES.items():
            enveloppe = await self._appel("teams", {"league": ident, "season": self.saison})
            if not enveloppe:
                continue
            noms = [
                (bloc.get("team") or {}).get("name")
                for bloc in ClientApiFootball.reponses(enveloppe)
            ]
            self.equipes[code] = sorted(n for n in noms if n)

        self.rapport["equipes"] = {
            code: {"nombre": len(noms), "extrait": noms[:5]} for code, noms in self.equipes.items()
        }

    async def calendrier(self) -> None:
        """Y a-t-il des matchs à venir ? C'est la raison d'être de l'abonnement."""
        enveloppe = await self._appel("fixtures", {"league": LIGUES["E0"][0], "next": 10})
        if not enveloppe:
            self.rapport["calendrier"] = {"erreur": "injoignable"}
            return

        matchs = ClientApiFootball.reponses(enveloppe)
        self.rapport["calendrier"] = {
            "matchs_a_venir": len(matchs),
            "prochain": (
                {
                    "date": ((matchs[0].get("fixture") or {}).get("date")),
                    "domicile": ((matchs[0].get("teams") or {}).get("home") or {}).get("name"),
                    "exterieur": ((matchs[0].get("teams") or {}).get("away") or {}).get("name"),
                    "identifiant": ((matchs[0].get("fixture") or {}).get("id")),
                }
                if matchs
                else None
            ),
        }
        self._prochain_match = ((matchs[0].get("fixture") or {}).get("id")) if matchs else None

    async def cotes(self) -> None:
        """Bookmakers et marchés disponibles sur un match à venir."""
        identifiant_match = getattr(self, "_prochain_match", None)
        if not identifiant_match:
            self.rapport["cotes"] = {"erreur": "aucun match à venir pour tester"}
            return

        enveloppe = await self._appel("odds", {"fixture": identifiant_match})
        if not enveloppe:
            self.rapport["cotes"] = {"erreur": "injoignable"}
            return

        reponses = ClientApiFootball.reponses(enveloppe)
        if not reponses:
            self.rapport["cotes"] = {
                "bookmakers": 0,
                "note": "aucune cote sur ce match — trop tôt, ou hors couverture",
            }
            return

        bookmakers = reponses[0].get("bookmakers") or []
        marches = {
            (pari.get("name") or "?")
            for bookmaker in bookmakers
            for pari in (bookmaker.get("bets") or [])
        }
        self.rapport["cotes"] = {
            "bookmakers": len(bookmakers),
            "noms_bookmakers": sorted({(b.get("name") or "?") for b in bookmakers})[:12],
            "marches_distincts": len(marches),
            "marches_utiles": sorted(
                m
                for m in marches
                if any(
                    mot in m.lower()
                    for mot in ("match winner", "goals over", "both teams", "double chance", "half")
                )
            )[:15],
        }

    async def profondeur_des_cotes(self) -> None:
        """Jusqu'où l'historique des cotes remonte-t-il ?

        Question décisive : si les cotes ne sont pas disponibles sur les saisons
        passées, l'étape 7 ne peut pas enrichir l'historique, seulement l'avenir.
        """
        mesures = {}
        for saison_fd in ("2223", "2425"):
            saison = saison_api(saison_fd)
            enveloppe = await self._appel(
                "odds", {"league": LIGUES["E0"][0], "season": saison, "page": 1}
            )
            if not enveloppe:
                mesures[saison_fd] = {"erreur": "injoignable"}
                continue
            pagination = enveloppe.get("paging") or {}
            mesures[saison_fd] = {
                "matchs_avec_cotes": enveloppe.get("results", 0),
                "pages": pagination.get("total", 0),
            }
        self.rapport["profondeur_des_cotes"] = mesures

    async def blessures(self) -> None:
        """Les absences sont-elles renseignées, et de quand datent-elles ?"""
        enveloppe = await self._appel(
            "injuries", {"league": LIGUES["E0"][0], "season": self.saison}
        )
        if not enveloppe:
            self.rapport["blessures"] = {"erreur": "injoignable"}
            return

        entrees = ClientApiFootball.reponses(enveloppe)
        dates = sorted(d for d in ((e.get("fixture") or {}).get("date") for e in entrees) if d)
        self.rapport["blessures"] = {
            "entrees": len(entrees),
            "plus_ancienne": dates[0] if dates else None,
            "plus_recente": dates[-1] if dates else None,
            "rappel": (
                "Absence d'information n'est pas absence de blessure : une liste "
                "vide ne doit jamais devenir un injury_impact de 0."
            ),
        }

    # ── Sortie ───────────────────────────────────────────────────────────

    def ecrire(self, dossier: Path) -> Path:
        dossier.mkdir(parents=True, exist_ok=True)
        self.rapport["quota"] = self.client.etat_quota()

        horodatage = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        rapport = dossier / f"sonde_api_football_{horodatage}.json"
        rapport.write_text(json.dumps(self.rapport, ensure_ascii=False, indent=2), encoding="utf-8")

        for code, noms in self.equipes.items():
            fichier = dossier / f"noms_api_football_{code}.json"
            fichier.write_text(
                json.dumps({"noms": noms}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return rapport


def resumer(rapport: dict) -> None:
    """Afficher l'essentiel, et surtout ce qui exige une décision."""
    statut = rapport.get("statut", {})
    print("\n─── Abonnement ───")
    print(f"  plan            : {statut.get('plan')}  (actif : {statut.get('actif')})")
    print(
        f"  quota du jour   : {statut.get('requetes_du_jour')} / {statut.get('quota_journalier')}"
    )

    print("\n─── Championnats ───")
    for code, infos in (rapport.get("ligues") or {}).items():
        if "erreur" in infos:
            print(f"  {code:4s} ⚠ {infos['erreur']}")
            continue
        marque = "✓" if infos["identifiant_confirme"] else "✗ IDENTIFIANT FAUX"
        couverture = infos.get("couverture") or {}
        matchs = couverture.get("fixtures") or {}
        actifs = [
            nom
            for nom, valeur in (
                ("cotes", couverture.get("odds")),
                ("blessures", couverture.get("injuries")),
                ("compositions", matchs.get("lineups")),
                ("statistiques", matchs.get("statistics_fixtures")),
            )
            if valeur
        ]
        print(f"  {code:4s} {marque}  {infos['nom']} — couvre : {', '.join(actifs) or 'rien'}")

    print("\n─── Équipes récupérées ───")
    for code, infos in (rapport.get("equipes") or {}).items():
        print(f"  {code:4s} {infos['nombre']} noms")

    print("\n─── Cotes ───")
    cotes = rapport.get("cotes", {})
    if "erreur" in cotes or cotes.get("bookmakers") == 0:
        print(f"  {cotes.get('erreur') or cotes.get('note')}")
    else:
        print(f"  {cotes['bookmakers']} bookmakers, {cotes['marches_distincts']} marchés")
        print(f"  marchés utiles : {', '.join(cotes.get('marches_utiles', [])) or '—'}")

    print("\n  profondeur historique :")
    for saison, mesure in (rapport.get("profondeur_des_cotes") or {}).items():
        if "erreur" in mesure:
            print(f"    {saison} : {mesure['erreur']}")
        else:
            print(f"    {saison} : {mesure['matchs_avec_cotes']} matchs avec cotes")

    blessures = rapport.get("blessures", {})
    print(
        f"\n─── Blessures ───\n  {blessures.get('entrees', '?')} entrées, "
        f"la plus récente : {blessures.get('plus_recente')}"
    )

    quota = rapport.get("quota", {})
    print(
        f"\n─── Coût de la sonde ───\n  {quota.get('consommes')} appels — "
        f"restant annoncé : {quota.get('restant')}"
    )


async def executer(saison: str, sortie: Path) -> None:
    client = ClientApiFootball(quota=SuiviQuota(plafond_execution=PLAFOND_APPELS))
    sonde = Sonde(client, saison)

    await sonde.statut()
    await sonde.ligues()
    await sonde.noms_d_equipes()
    await sonde.calendrier()
    await sonde.cotes()
    await sonde.profondeur_des_cotes()
    await sonde.blessures()

    chemin = sonde.ecrire(sortie)
    resumer(sonde.rapport)

    print(f"\nRapport complet : {chemin}")
    print(f"Noms d'équipes  : {sortie}/noms_api_football_*.json")
    print("\nÉtape suivante — construire le registre de correspondances :")
    print(
        f"  python scripts/generer_correspondances.py --fournisseur api_football "
        f"--ligue E0 --noms {sortie}/noms_api_football_E0.json"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saison", default="2526", help="Saison Football-Data (défaut : 2526)")
    parser.add_argument("--sortie", type=Path, default=Path("rapports"), help="Dossier de sortie")
    args = parser.parse_args()

    try:
        asyncio.run(executer(args.saison, args.sortie))
    except CleManquanteError as erreur:
        raise SystemExit(str(erreur)) from erreur


if __name__ == "__main__":
    main()
