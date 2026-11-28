#!/bin/sh
# Crea o actualiza el trabajo que revisa el correo a las 6:00, 15:00 y 21:00.
# El token se lee de Secret Manager y pasa directo a gcloud; nunca se imprime.
# Si se rota JARVIS_TOKEN, vuelve a correr este script.
set -eu

project="${1:-<PROYECTO>}"
url="${2:-<URL_CLOUD_RUN>}"

if [ "$#" -ne 2 ] || [ "$project" = '<PROYECTO>' ] || [ "$url" = '<URL_CLOUD_RUN>' ]; then
    printf 'Ejecuta %s con el ID del proyecto y la URL de Cloud Run.\n' "$0" >&2
    exit 2
fi

job=jarvis-revisar-correo
token="$(gcloud secrets versions access latest --secret=JARVIS_TOKEN --project="$project")"
common="--project=$project --location=us-central1"

if gcloud scheduler jobs describe "$job" $common >/dev/null 2>&1; then
    action=update
    headers_flag=--update-headers
else
    action=create
    headers_flag=--headers
fi

# shellcheck disable=SC2086
gcloud scheduler jobs "$action" http "$job" $common \
    --schedule='0 6,15,21 * * *' \
    --time-zone='America/Monterrey' \
    --uri="$url/tareas/revisar-correo" \
    --http-method=POST \
    "$headers_flag=Authorization=Bearer $token" \
    --attempt-deadline=180s \
    --quiet >/dev/null
unset token
printf 'Trabajo %s listo (%s).\n' "$job" "$action"
