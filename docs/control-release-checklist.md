# WOKKER CONTROL — release security checklist

Do not merge or deploy without explicit approval. PR 85 targets feature/wokker-control, not main.

## Required environment checks (staging first)
- Configure CONTROL_GUEST_ALIAS_SECRET as a stable, independently generated cryptographically random secret (at least 32 random bytes). Never commit or log it. Missing secret prevents anonymous guest assignment. Rotation invalidates previously displayed aliases; reload directory before assigning.
- Verify TRUSTED_PROXY_NETWORKS against the actual ingress topology; do not trust arbitrary clients or broad networks. Confirm ingress overwrites forwarded headers and direct access is restricted.
- Require HTTPS and verify no-store responses for authenticated CONTROL endpoints, including photos.
- Verify database credentials have only required privileges; restrict access to guest identity history, backups and logs.
- Confirm rate limits under actual ingress and worker topology. In-memory limits are per process.
- Confirm RUN_MIGRATIONS and database backup/restore procedure; test migrations 017–019 on a staging copy. Index creation can lock writes; schedule maintenance if needed.
- Verify guest role, HR, super admin, TU, US and revoked accounts on staging. Check historical identity redaction and guest alias assignment.
- Verify physical mobile devices, interrupted connections and concurrent users.
- Confirm monitoring of HTTP 5xx, latency, database connections and migration failures without logging tokens or guest identities.

## Rollback
Record deployed commit and migration state, take a verified backup before rollout, and rehearse application rollback on staging. Do not drop identity history or restore over live data without an approved recovery plan.

## Known limitations
SQL benchmarks are not end-to-end concurrent load tests. Free text and photo pixels may contain identifying information. Historical names changed before identity capture may not be recoverable. Production configuration and actual ingress have not been verified by repository CI.
