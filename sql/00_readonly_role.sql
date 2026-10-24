-- Run once as superuser. Read-only role used by the Gemini NL->SQL feature (defense in depth).
CREATE DATABASE olist;
\c olist
CREATE ROLE olist_reader LOGIN PASSWORD 'reader_pw';
GRANT CONNECT ON DATABASE olist TO olist_reader;
GRANT USAGE ON SCHEMA public TO olist_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO olist_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO olist_reader;
ALTER ROLE olist_reader SET statement_timeout = '15s';
