# Cloud Run

Configuración consultada el 26 de noviembre de 2026 con `gcloud run services
describe` y `gcloud run services get-iam-policy`.

| Ajuste | Valor |
| --- | --- |
| Servicio | `jarvis` |
| Proyecto y región | `<PROYECTO>`, `us-central1` |
| Despliegue | Desde código fuente. Python 3.15 con `python -m app` según el [Procfile](../../Procfile) |
| Cuenta de ejecución | `<CUENTA_DE_SERVICIO>` |
| Escalado | 0 instancias mínimas. Máximo de 1 por revisión y de 20 para el servicio |
| Contenedor | 1 CPU, 256 MiB, primera generación y CPU limitada fuera de solicitudes. Aumento de CPU al arrancar |
| Solicitudes | Hasta 80 simultáneas por instancia. Cloud Run espera hasta 300 s y la aplicación limita sus operaciones protegidas a 90 s |
| Arranque | Puerto 8080. Sonda TCP en ese puerto, con 240 s de período y de espera y un intento fallido permitido |
| Red y acceso | Ingreso desde cualquier origen. El rol `roles/run.invoker` incluye `allUsers`. La aplicación exige el token de JARVIS en los endpoints protegidos |
| Tráfico | 100 % a la última revisión lista |
| Variables | `HOST=0.0.0.0`. Secret Manager suministra `OPENAI_API_KEY` y `JARVIS_TOKEN` desde las versiones `latest` |

`GET /health` comprueba que el proceso responde. Cloud Scheduler lo usa para
despertar el servicio. La sonda de arranque de Cloud Run también verifica que
el contenedor abra el puerto TCP.

## Desplegar desde la Mac

1. Autentica `gcloud` con una cuenta con permiso de despliegue. Comprueba que los dos secretos ya existen y que la cuenta de ejecución puede leerlos.
2. Desde la raíz del repositorio, sustituye los marcadores y ejecuta:

   ```sh
   ./infra/deploy.sh '<PROYECTO>' '<CUENTA_DE_SERVICIO>'
   ```

3. Consulta la URL y verifica `/health`:

   ```sh
   gcloud run services describe jarvis --project='<PROYECTO>' --region=us-central1 --format='value(status.url)'
   curl --fail --show-error 'https://<URL_CLOUD_RUN>/health'
   ```

[deploy.sh](../deploy.sh) reproduce el comando de despliegue anterior. El
[manifiesto de ejemplo](servicio.example.yaml) documenta los ajustes observados
de la revisión. Sustituye `<IMAGEN>` si necesitas identificar una imagen ya
construida. El acceso público se configura mediante IAM, como hace el script
con `--allow-unauthenticated`.

Cloud Run proporciona `PORT`. La documentación interactiva de la API se muestra
al ejecutar el servidor en la Mac con el host local predeterminado.
`data/estado.json` vive en el almacenamiento temporal del contenedor y se
puede perder al reiniciar o desplegar.
