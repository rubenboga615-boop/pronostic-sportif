-- Migration : arbitre du match (2026-09-07)
--
-- ⚠️ SAUVEGARDE OBLIGATOIRE AVANT EXÉCUTION.
--     cp data/pronostic.db data/backups/pronostic_avant_arbitre.db
--     sqlite3 data/backups/pronostic_avant_arbitre.db "PRAGMA integrity_check;"
--
-- Contexte
-- --------
-- La colonne `Referee` des fichiers Football-Data était lue par personne. Elle
-- n'a aucun effet sur les marchés de buts de la Phase 1 — c'est pourquoi elle
-- avait été omise — mais elle est la variable centrale des marchés de cartons
-- de la Phase 2, où les écarts entre arbitres sont bien plus marqués qu'entre
-- équipes.
--
-- Elle est importée maintenant pour une raison de calendrier, pas de modèle :
-- les fichiers de Football-Data ne sont pas versionnés. Une colonne qu'on
-- n'importe pas aujourd'hui est perdue le jour où le fournisseur la retire —
-- c'est déjà arrivé aux cotes Interwetten entre 2023/24 et 2024/25, et aux
-- hors-jeu vers 2019.
--
-- Les matchs déjà en base gardent NULL. Ils seront renseignés au prochain
-- import complet, la colonne `Referee` étant présente dans les fichiers source
-- des saisons concernées.
--
-- Cette migration n'est PAS idempotente. Pour vérifier si elle a déjà été
-- appliquée :
--
--     sqlite3 data/pronostic.db "PRAGMA table_info(matches);" | grep referee
--
-- Une ligne renvoyée signifie que la migration est déjà passée.

BEGIN TRANSACTION;

ALTER TABLE matches ADD COLUMN referee VARCHAR;

COMMIT;

-- Sens retour (DOWN)
-- ------------------
-- SQLite gère DROP COLUMN depuis la version 3.35 :
--   ALTER TABLE matches DROP COLUMN referee;
-- Sur une version antérieure, restaurer la sauvegarde.
