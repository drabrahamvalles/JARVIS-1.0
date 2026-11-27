#!/bin/sh
set -eu

project="${1:-<PROYECTO>}"
service_account="${2:-<CUENTA_DE_SERVICIO>}"

if [ "$#" -ne 2 ] || [ "$project" = '<PROYECTO>' ] || [ "$service_account" = '<CUENTA_DE_SERVICIO>' ]; then
    printf 'Ejecuta %s con el ID del proyecto y el correo de la cuenta de servicio.\n' "$0" >&2
    exit 2
fi

cd "$(dirname "$0")/.."

secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,JARVIS_TOKEN=JARVIS_TOKEN:latest"
# Los calendarios compartidos con la cuenta de servicio son opcionales (fase 4.2).
if gcloud secrets describe JARVIS_CALENDARIOS --project="$project" >/dev/null 2>&1; then
    secrets="$secrets,JARVIS_CALENDARIOS=JARVIS_CALENDARIOS:latest"
fi
# El token de Gmail (solo lectura) es opcional (fase 4.3).
if gcloud secrets describe JARVIS_GMAIL --project="$project" >/dev/null 2>&1; then
    secrets="$secrets,JARVIS_GMAIL=JARVIS_GMAIL:latest"
fi

gcloud run deploy jarvis \
    --source=. \
    --project="$project" \
    --region=us-central1 \
    --allow-unauthenticated \
    --min-instances=0 \
    --max-instances=1 \
    --cpu=1 \
    --memory=256Mi \
    --concurrency=80 \
    --timeout=300 \
    --execution-environment=gen1 \
    --cpu-throttling \
    --cpu-boost \
    --set-env-vars=HOST=0.0.0.0 \
    --set-secrets="$secrets" \
    --service-account="$service_account" \
    --quiet
