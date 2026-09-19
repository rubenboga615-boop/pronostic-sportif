-- Migration : fusionner deux équipes dupliquées par l'import API-Football (2026-09-19)
--
-- ⚠️ SAUVEGARDE OBLIGATOIRE AVANT EXÉCUTION.
--     cp data/pronostic.db data/backups/pronostic_avant_fusion_doublons.db
--     sqlite3 data/backups/pronostic_avant_fusion_doublons.db "PRAGMA integrity_check;"
--
-- Contexte
-- --------
-- Le premier import API-Football a créé six équipes. Quatre sont de vrais
-- promus que la base n'avait jamais vus — Coventry, Racing Santander,
-- SV Elversberg, Le Mans — et doivent rester.
--
-- Les deux autres sont des doublons, nés d'un écart d'écriture que le
-- générateur de correspondances n'a pas signalé parce qu'il jugeait ces noms
-- « déjà résolus » :
--
--   id 159  « Borussia Mönchengladbach »  doublonne  id 36  « Borussia Monchengladbach »  (tréma)
--   id 162  « Paris Saint Germain »       doublonne  id 55  « Paris Saint-Germain »        (trait d'union)
--
-- Laissées en l'état, ces deux équipes neuves porteraient 34 matchs chacune
-- sans aucun historique, pendant que leurs jumelles en portent 306 et 319.
-- Dixon-Coles estimerait alors le Borussia et le PSG comme des promus — deux
-- des équipes les mieux documentées de la base.
--
-- La correction est un simple recollement : les matchs de 2026/27 sont
-- rattachés à l'équipe historique, puis les doublons disparaissent. Aucun
-- résultat, aucune cote, aucune probabilité n'est touché — seul un
-- identifiant d'équipe change, et il désigne le même club.
--
-- Les correspondances sont ajoutées au même moment dans
-- `collectors/mapping/equipes.json` : sans cela, le prochain import
-- recréerait les doublons.
--
-- Cette migration EST idempotente : les UPDATE ne trouvent plus rien à
-- déplacer une fois passés, et les DELETE portent sur des identifiants qui
-- n'existent plus. Pour vérifier si elle a déjà été appliquée :
--
--     sqlite3 data/pronostic.db \
--       "SELECT COUNT(*) FROM teams WHERE canonical_name IN
--        ('Borussia Mönchengladbach', 'Paris Saint Germain');"
--
-- Zéro signifie que la migration est déjà passée.

BEGIN TRANSACTION;

-- Borussia Mönchengladbach (159) -> Borussia Monchengladbach (36)
UPDATE matches
   SET home_team_id = 36
 WHERE home_team_id = 159;
UPDATE matches
   SET away_team_id = 36
 WHERE away_team_id = 159;

-- Paris Saint Germain (162) -> Paris Saint-Germain (55)
UPDATE matches
   SET home_team_id = 55
 WHERE home_team_id = 162;
UPDATE matches
   SET away_team_id = 55
 WHERE away_team_id = 162;

-- Les doublons n'ont ni features, ni statistiques, ni xG : ils viennent de
-- naître. Les tables filles sont tout de même nettoyées, par principe — une
-- ligne orpheline pointant vers une équipe supprimée est un défaut silencieux.
DELETE FROM features WHERE team_id IN (159, 162);
DELETE FROM team_match_stats WHERE team_id IN (159, 162);
DELETE FROM xg_match_stats WHERE team_id IN (159, 162);
DELETE FROM availability WHERE team_id IN (159, 162);

DELETE FROM teams WHERE id IN (159, 162);

COMMIT;

-- Sens retour (DOWN)
-- ------------------
-- Aucun : une fusion d'identité ne se défait pas, les matchs déplacés ne
-- portant plus trace de leur rattachement d'origine. Restaurer la sauvegarde.
