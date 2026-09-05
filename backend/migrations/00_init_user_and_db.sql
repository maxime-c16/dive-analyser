-- Bootstrap: application role and database (template).
-- Credentials are provisioned from the runtime environment (.env) via
-- docker-compose variable substitution. Do NOT embed live secrets here.
-- The live database already exists; this file is first-boot bootstrap only.

DO
$do$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'diving') THEN
    CREATE ROLE diving WITH LOGIN PASSWORD 'CHANGE_ME_USE_RUNTIME_ENV' CREATEDB;
  END IF;
END
$do$;

-- Create database
CREATE DATABASE diving_analyzer_db OWNER diving;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE diving_analyzer_db TO diving;
