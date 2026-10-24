# Azure deployment (live)

The API runs at **https://vouch-core.livelygrass-b9211f5e.northcentralus.azurecontainerapps.io** (`GET /health` → `{"ok": true}`).
It was deployed on 2026-10-24 from commit `ae654b4`, on the *Azure for Students* subscription.

| Resource (group `vouch-app-rg`, region North Central US) | What it is |
|---|---|
| `vouch-core` | Container App with 1 replica (min = max = 1, because SQLite has a single writer), 0.5 vCPU and 1 GiB |
| `vouch-env` | Container Apps environment, in **WorkloadProfiles** mode on the Consumption profile. Express environments don't support storage. |
| `vouchsujithf26e80` | Container registry (Basic) |
| `vouchdata8d7a02` / share `vouchdb` | Azure Files share mounted at `/data`, holding `vouch.db` and `vouch.db.evalkey` |
| `vouch-logs` and `vouch-ai` | Log Analytics workspace and Application Insights (tracing through `APPLICATIONINSIGHTS_CONNECTION_STRING`) |

**Settings:**
- `VOUCH_ENV=prod`
- `VOUCH_DB=/data/vouch.db`
- `VOUCH_DATASET=v2`
- `DEMO_ENDPOINTS=1`
- `CORS_ORIGINS=http://localhost:3000,http://localhost:5173`. Add the UI's origin when it exists.
- `VOUCH_SQLITE_VFS=unix-dotfile` and `VOUCH_SQLITE_JOURNAL=DELETE`. The Azure Files share is SMB, where SQLite's normal locks fail with "database is locked".
- `VOUCH_API_KEYS` is a secret. It holds new random keys for sync, agent, accountant (ann), accountant (bob), policy and gateway. The keys are kept outside the repo; ask Sujith for yours. The built-in dev keys are refused in prod.

**Start command:** removes a stale `/data/vouch.db.lock`. It seeds v2 only when `/data/vouch.db` is missing or empty, then runs uvicorn with 1 worker.

**Checked after the deploy:**
- `/health` returns 200.
- A request with no key returns 401, and a dev key also returns 401.
- 300 items were seeded, and no answer-key fields appear through the API.
- `/audit/verify` is ok.
- When the agent tries to approve, the API returns 403 `ACTOR_NOT_ALLOWED` and writes the denial to the audit log.
- The demo endpoints are present.
- After a restart, the data and the audit chain are intact.

**Subscription constraints:** the only allowed regions are northcentralus, germanywestcentral, belgiumcentral, norwayeast and denmarkeast, so `deploy/azure_deploy.sh` with `westus2` fails. The image must be built for `linux/amd64` on an Apple Silicon Mac.

**To redeploy a new commit:**
```
az acr login -n vouchsujithf26e80
docker build --platform linux/amd64 -t vouchsujithf26e80.azurecr.io/vouch-api:<commit> .
docker push vouchsujithf26e80.azurecr.io/vouch-api:<commit>
az containerapp update -n vouch-core -g vouch-app-rg --image vouchsujithf26e80.azurecr.io/vouch-api:<commit>
```

**When the hackathon is over:** `az group delete -n vouch-app-rg` removes everything, so it stops using credit.
