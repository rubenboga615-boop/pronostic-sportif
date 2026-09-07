-- Migration : purger la fuite des cotes de clôture (2026-09-06)
--
-- ⚠️ SAUVEGARDE OBLIGATOIRE AVANT EXÉCUTION.
--     cp data/pronostic.db data/backups/pronostic_avant_purge_odds_movement.db
--     sqlite3 data/backups/pronostic_avant_purge_odds_movement.db "PRAGMA integrity_check;"
--
-- Contexte
-- --------
-- `features.odds_movement` était calculé comme l'écart entre la cote
-- d'ouverture et la cote de CLÔTURE (B365_close). La cote de clôture est
-- relevée au coup d'envoi : elle n'est pas disponible au moment de prédire, et
-- `PROJECT_SPEC.md` l'exclut explicitement des variables prédictives.
--
-- Sur les 1 520 lignes de la base, la colonne était remplie à 100 %, et ses
-- valeurs portaient la trace du résultat : moyenne de -0,0074 côté domicile
-- quand l'équipe à domicile gagne, +0,0132 quand elle perd.
--
-- Par ailleurs, l'import donnait à TOUTES les cotes un `captured_at` égal à la
-- date du match, y compris aux cotes d'ouverture dont Football-Data.co.uk ne
-- publie pas l'instant de relevé. Une cote non datée passait ainsi pour une
-- cote pré-match exploitable.
--
-- Sens aller (UP) — idempotent.

-- Transaction : les deux effacements doivent réussir ensemble. Interrompue
-- entre les deux, la migration laisserait une base à moitié purgée — features
-- nettoyées mais horodatages toujours menteurs — c'est-à-dire dans un état
-- qu'aucune des deux versions du code ne sait interpréter.
BEGIN TRANSACTION;

-- 1) Effacer les valeurs contaminées.
UPDATE features
   SET odds_movement = NULL
 WHERE odds_movement IS NOT NULL;

-- 2) Rendre l'horodatage honnête : seule la clôture a un instant connu.
UPDATE odds_snapshots
   SET captured_at = NULL
 WHERE is_closing = 0;

COMMIT;

-- Sens retour (DOWN)
-- ------------------
-- Non réversible : les valeurs effacées ne sont pas reconstructibles depuis la
-- base. Elles n'ont d'ailleurs pas vocation à revenir — les recalculer
-- reproduirait la fuite. Pour retrouver l'état antérieur, restaurer la
-- sauvegarde prise avant exécution.
--
-- Après cette migration, `odds_movement` reste NULL tant qu'aucune source ne
-- fournit plusieurs relevés pré-match horodatés (voir étape 7 de
-- docs/ROADMAP.md, API-Football). Le calcul redeviendra alors automatique,
-- sans modification du code.
