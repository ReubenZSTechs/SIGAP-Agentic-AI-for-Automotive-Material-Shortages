#!/bin/sh
# Runs once, on first start of an empty data volume (postgres image entrypoint).
# Satu database aplikasi (mrp, dipakai juga oleh chatbot dalam transaksi READ ONLY) + database test.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE DATABASE ${TEST_DB} OWNER ${POSTGRES_USER};
SQL
