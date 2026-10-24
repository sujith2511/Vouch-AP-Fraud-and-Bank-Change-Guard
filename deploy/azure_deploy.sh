#!/usr/bin/env bash
# Deploy the core API to Azure Container Apps. NOT yet run: needs `az login`, a subscription and Azure credits.
#   VOUCH_API_KEYS='{"<random>":{"role":"agent","user":"agent-1"}, ...}' ./deploy/azure_deploy.sh
set -euo pipefail
: "${VOUCH_API_KEYS:?set VOUCH_API_KEYS (JSON key->role map); never use the dev keys in Azure}"
RG=${RG:-vouch-rg}; LOC=${LOC:-westus2}; ENVN=${ENVN:-vouch-env}; APP=${APP:-vouch-core}; SA=${SA:-vouchdata$RANDOM}
az group create -n "$RG" -l "$LOC"
az monitor app-insights component create -a vouch-ai -g "$RG" -l "$LOC" --kind web >/dev/null
CS=$(az monitor app-insights component show -a vouch-ai -g "$RG" --query connectionString -o tsv)
# persistent volume for the SQLite file (Azure Files); keep a single replica
az storage account create -n "$SA" -g "$RG" -l "$LOC" --sku Standard_LRS >/dev/null
az storage share-rm create --storage-account "$SA" -g "$RG" -n vouchdb >/dev/null
az containerapp env create -n "$ENVN" -g "$RG" -l "$LOC"
KEY=$(az storage account keys list -n "$SA" -g "$RG" --query '[0].value' -o tsv)
az containerapp env storage set -n "$ENVN" -g "$RG" --storage-name vouchdb --azure-file-account-name "$SA" \
   --azure-file-account-key "$KEY" --azure-file-share-name vouchdb --access-mode ReadWrite
az containerapp up -n "$APP" -g "$RG" --environment "$ENVN" --source . --ingress external --target-port 8000
az containerapp update -n "$APP" -g "$RG" --min-replicas 1 --max-replicas 1 \
   --set-env-vars VOUCH_ENV=prod VOUCH_DB=/data/vouch.db "APPLICATIONINSIGHTS_CONNECTION_STRING=$CS" "VOUCH_API_KEYS=$VOUCH_API_KEYS"
echo "mount the 'vouchdb' storage at /data via the portal or a YAML export/update (az containerapp CLI cannot add volumes inline)"
az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv
