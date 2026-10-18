#!/bin/sh
# Runs once, on first start of an empty data volume (postgres image entrypoint).
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE ${CHAT_RO_USER} LOGIN PASSWORD '${CHAT_RO_PASSWORD}';
CREATE DATABASE ${TEST_DB} OWNER ${POSTGRES_USER};
SQL

for db in "$POSTGRES_DB" "$TEST_DB"; do
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE ${db} TO ${CHAT_RO_USER};
GRANT USAGE ON SCHEMA public TO ${CHAT_RO_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${CHAT_RO_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT SELECT ON TABLES TO ${CHAT_RO_USER};
ALTER ROLE ${CHAT_RO_USER} SET default_transaction_read_only = on;
ALTER ROLE ${CHAT_RO_USER} SET statement_timeout = '10s';
SQL
done
