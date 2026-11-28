#!/bin/sh
# Convierte jarvis-despertador en el revisor de avisos de salida: corre cada 10 minutos de
# 4:00 a 23:50 (hora de Monterrey; desde las 4 por los vuelos temprano), sigue despertando
# al servidor y llama POST /tareas/avisos con el token, que nunca se imprime.
set -eu

project="${1:-<PROYECTO>}"
url="${2:-<URL_CLOUD_RUN>}"

if [ "$#" -ne 2 ] || [ "$project" = '<PROYECTO>' ] || [ "$url" = '<URL_CLOUD_RUN>' ]; then
    printf 'Ejecuta %s con el ID del proyecto y la URL de Cloud Run.\n' "$0" >&2
    exit 2
fi

token="$(gcloud secrets versions access latest --secret=JARVIS_TOKEN --project="$project")"
gcloud scheduler jobs update http jarvis-despertador \
    --project="$project" \
    --location=us-central1 \
    --schedule='*/10 4-23 * * *' \
    --time-zone='America/Monterrey' \
    --uri="$url/tareas/avisos" \
    --http-method=POST \
    "--update-headers=Authorization=Bearer $token" \
    --quiet >/dev/null
unset token
printf 'jarvis-despertador llama /tareas/avisos cada 10 minutos de 4:00 a 23:50.\n'
