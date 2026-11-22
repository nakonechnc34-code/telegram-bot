#!/usr/bin/env bash
# Create a local PostgreSQL custom-format backup. Upload it to encrypted off-site
# storage separately; a local backup alone is not disaster recovery.
set -euo pipefail
umask 077

: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL connection URL}"
: "${BACKUP_DIR:?Set BACKUP_DIR to a secure directory outside the application web root}"

command -v pg_dump >/dev/null || { echo "pg_dump is required" >&2; exit 1; }
command -v pg_restore >/dev/null || { echo "pg_restore is required" >&2; exit 1; }

mkdir -p -- "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="${BACKUP_DIR%/}/postgres-${stamp}-$$.dump"
temporary="$(mktemp "${BACKUP_DIR%/}/.postgres-backup.XXXXXXXX")"
trap 'rm -f -- "$temporary"' EXIT

pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-acl --file="$temporary"
pg_restore --list "$temporary" >/dev/null
mv -- "$temporary" "$destination"
trap - EXIT
echo "Backup created: $destination"
echo "Next: transfer to encrypted off-site storage and test restoration."
