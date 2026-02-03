-- Create the role if it doesn't exist
DO
$do$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'diving') THEN
    CREATE ROLE diving WITH LOGIN PASSWORD 'REDACTED-HISTORICAL-DB-CREDENTIAL' CREATEDB;
  END IF;
END
$do$;

-- Create database
CREATE DATABASE diving_analyzer_db OWNER diving;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE diving_analyzer_db TO diving;
