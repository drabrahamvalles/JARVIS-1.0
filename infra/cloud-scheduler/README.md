# Cloud Scheduler

Configuración de `jarvis-despertador` consultada el 26 de noviembre de 2026.

| Ajuste | Valor |
| --- | --- |
| Proyecto y ubicación | `<PROYECTO>`, `us-central1` |
| Estado | Activo (`ENABLED`) |
| Horario | `*/10 6-22 * * *`, de 06:00 a 22:50 cada diez minutos, todos los días |
| Zona horaria | `America/Mazatlan` |
| Destino | `GET https://<URL_CLOUD_RUN>/health` |
| Autenticación | El endpoint es público. El trabajo no envía token ni cuerpo |
| Tiempo límite por intento | 180 s |
| Ajustes de reintento | Espera mínima de 5 s y máxima de 3600 s, hasta 5 duplicaciones de la espera. Duración máxima de 0 s y sin `retryCount` explícito |

El trabajo llama a `/health`. El briefing depende de la automatización de alarma del iPhone.

Consulta de solo lectura:

```sh
gcloud scheduler jobs describe jarvis-despertador --project='<PROYECTO>' --location=us-central1
```
