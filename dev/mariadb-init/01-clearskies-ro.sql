-- Create the clearskies_ro (read-only) database user for the API service.
--
-- This user has SELECT-only on the weewx database. The clearskies-api startup
-- write-probe (ADR-012) verifies the runtime user cannot write; this is the
-- fixture user for those positive tests ("probe should accept startup").
--
-- The seed user (MARIADB_USER from .env) retains full DML so the seed loader
-- can populate data. The API service must NOT use the seed user at runtime.
--
-- Per ADR-012: defense in depth requires both the DB-level grant AND the
-- startup probe. This script provides the DB-level half.
--
-- The password is set from the MARIADB_CLEARSKIES_RO_PASSWORD env variable
-- when this script is sourced by the entrypoint, but MariaDB init SQL cannot
-- interpolate env vars directly. We use a known test password here because
-- this is dev/test infrastructure only — never production.
-- Password: clearskies_ro_test
--
-- To rotate: update this file + the CLEARSKIES_DB_RO_PASSWORD value in .env.example.

CREATE USER IF NOT EXISTS 'clearskies_ro'@'%' IDENTIFIED BY 'clearskies_ro_test';
GRANT SELECT ON weewx.* TO 'clearskies_ro'@'%';
FLUSH PRIVILEGES;
