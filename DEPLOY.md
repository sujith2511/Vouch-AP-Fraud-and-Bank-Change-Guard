# Deploying the Vouch API

One container, one process, one SQLite file. Nothing here has been run against a cloud account yet; see `deploy/azure.md` for the Azure walkthrough.

## Build and run locally

```
docker build -t vouch-api .
docker run --rm -p 8000:8000 -v vouch-data:/data \
  -e VOUCH_ENV=prod \
  -e VOUCH_API_KEYS='{"<long-random-1>":{"role":"sync","user":"sync-bot"},"<long-random-2>":{"role":"agent","user":"agent-1"},"<long-random-3>":{"role":"accountant","user":"ann"},"<long-random-4>":{"role":"policy","user":"policy-bot"},"<long-random-5>":{"role":"gateway","user":"gateway"}}' \
  -e CORS_ORIGINS=https://your-ui.example \
  vouch-api
curl localhost:8000/health        # {"ok": true}
```

## Environment

| Variable | Meaning |
|---|---|
| `VOUCH_ENV=prod` | Required in production. Refuses to start without `VOUCH_API_KEYS` (no built-in dev keys), and turns `/demo/inject` off. |
| `VOUCH_API_KEYS` | JSON object `{"<key>": {"role": "...", "user": "..."}}`. Roles: `sync`, `agent`, `accountant`, `policy`, `gateway`. The actor is always taken from the key, never from a request body. Use long random keys, one per person or service. Keep two accountant keys, since approving a bank change needs a different person than the one who answered the question. |
| `VOUCH_DB` | SQLite path. The image sets `/data/vouch.db`; **mount a persistent volume at `/data`**. Without it the audit log disappears on restart. The eval answer key (`<db>.evalkey`, only created when seeding a v2 dataset) sits next to it. |
| `CORS_ORIGINS` | Comma-separated allowed browser origins. Default is `http://localhost:3000,http://localhost:5173`. |
| `DEMO_ENDPOINTS=1` | Turns `POST /demo/inject` on even when `VOUCH_ENV=prod`. Leave unset in real production. |
| `VOUCH_DATASET` | `v1` (default) or `v2`; used by `vouch.seed` / `vouch.run_pipeline`. |

## Health

`GET /health` (and `/healthz`) returns `{"ok": true}` with no key. The Dockerfile has a `HEALTHCHECK` that calls it.

## Seeding a demo database

```
docker exec <container> python -m vouch.seed --db /data/vouch.db --dataset v2 --which emails
```

Run it once on an empty volume. Do not seed a real deployment with the demo data.

## Rules for operators

- Run exactly **one replica** and one uvicorn worker. SQLite has one writer.
- Back up `/data` (the audit log is the record of every decision; it is hash-chained and `GET /audit/verify` checks it).
- `data/v2/demo_real_vendors.json` is not copied into the image and the loader refuses it.
