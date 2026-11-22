#!/usr/bin/env bash
# Encrypted off-site backup to private Cloudflare R2. No plaintext backups are
# uploaded or retained as GitHub Actions artifacts.
set -euo pipefail
set +x
umask 077

for name in DATABASE_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY R2_ACCOUNT_ID R2_BUCKET BACKUP_AGE_RECIPIENT; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required configuration: $name" >&2
    exit 1
  fi
done
for tool in pg_dump pg_restore age aws sha256sum; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done

# Do not allow credentials to be sent without TLS. The connection may be a
# Supabase direct or session-pooler connection (not transaction pooler).
if [[ "$DATABASE_URL" != *"sslmode=require"* && "$DATABASE_URL" != *"sslmode=verify-full"* ]]; then
  echo "BACKUP_DATABASE_URL must explicitly include sslmode=require or sslmode=verify-full" >&2
  exit 1
fi

workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
key="postgres/daily/${stamp}-${GITHUB_RUN_ID:-manual}.dump.age"
endpoint="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Keep the unencrypted dump in runner-private temporary storage only.
pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-acl --file="$workdir/db.dump"
pg_restore --list "$workdir/db.dump" >/dev/null
age -r "$BACKUP_AGE_RECIPIENT" -o "$workdir/db.dump.age" "$workdir/db.dump"
rm -f -- "$workdir/db.dump"
sha256sum "$workdir/db.dump.age" | awk '{print $1}' > "$workdir/sha256"
aws --endpoint-url "$endpoint" s3 cp "$workdir/db.dump.age" "s3://$R2_BUCKET/$key" --only-show-errors
remote_size="$(aws --endpoint-url "$endpoint" s3api head-object --bucket "$R2_BUCKET" --key "$key" --query ContentLength --output text)"
local_size="$(wc -c < "$workdir/db.dump.age" | tr -d ' ')"
if [[ "$remote_size" != "$local_size" ]]; then
  echo "Upload verification failed: size mismatch" >&2
  exit 1
fi
echo "Encrypted backup uploaded successfully: $key ($local_size bytes)"
echo "Upload size checked; full decryption and restore must be tested separately."
