#!/usr/bin/env bash
# Destructive test ONLY for an explicitly designated disposable PostgreSQL DB.
# Never use a production database URL.
set -euo pipefail

if [[ "${CONFIRM_DISPOSABLE_RESTORE:-}" != "YES" ]]; then
  echo "Set CONFIRM_DISPOSABLE_RESTORE=YES only for a disposable empty database" >&2
  exit 1
fi
: "${RESTORE_DATABASE_URL:?Set RESTORE_DATABASE_URL for a disposable empty database}"
if [[ "$#" -ne 1 || ! -f "$1" ]]; then
  echo "Usage: RESTORE_DATABASE_URL=... CONFIRM_DISPOSABLE_RESTORE=YES $0 backup.dump" >&2
  exit 1
fi
command -v pg_restore >/dev/null || { echo "pg_restore is required" >&2; exit 1; }
command -v psql >/dev/null || { echo "psql is required" >&2; exit 1; }

# Refuse restoration into a database containing user tables.
table_count="$(psql "$RESTORE_DATABASE_URL" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_type = 'BASE TABLE'")"
if [[ "$table_count" != "0" ]]; then
  echo "Restore target is not empty; refusing to proceed" >&2
  exit 1
fi

pg_restore --list "$1" >/dev/null
pg_restore --dbname="$RESTORE_DATABASE_URL" --no-owner --no-acl --exit-on-error --single-transaction "$1"
psql "$RESTORE_DATABASE_URL" -X -v ON_ERROR_STOP=1 -c "SELECT count(*) AS restored_tables FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
echo "Restore completed. Review table counts and application smoke tests before relying on backups."
