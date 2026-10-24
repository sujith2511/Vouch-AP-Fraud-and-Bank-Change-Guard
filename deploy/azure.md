# Azure deployment notes (not yet deployed or verified)
- `./deploy/azure_deploy.sh` builds the Dockerfile and creates Container Apps + Application Insights + an Azure Files share. It has not been run: it needs an Azure login and credits.
- **Single replica only.** SQLite allows one writer; `BEGIN IMMEDIATE` serialises transactions inside one process. SQLite on an Azure Files (SMB) mount has weaker file-locking than local disk. For the hackathon, one replica is fine; for anything real, move to Azure SQL/Postgres (the schema's triggers need rewriting there).
- Fallback if the volume misbehaves: keep the DB on the container's local disk and re-seed on start (demo data only).
- Set `VOUCH_API_KEYS` (JSON key->role/user map). With `VOUCH_ENV=prod` the app refuses to start on the built-in dev keys.
- Logs: JSON to stdout (Container Apps -> Log Analytics). Every audit row is mirrored as a log line (logger `vouch.audit`); each request logs method/path/status/ms/role with an `x-request-id`. Tracing: set `APPLICATIONINSIGHTS_CONNECTION_STRING` and OpenTelemetry/Azure Monitor is enabled automatically.
