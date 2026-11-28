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

## jarvis-revisar-correo

| Ajuste | Valor |
| --- | --- |
| Horario | `0 6,15,21 * * *`, a las 6:00, 15:00 y 21:00 |
| Zona horaria | `America/Monterrey` |
| Destino | `POST https://<URL_CLOUD_RUN>/tareas/revisar-correo` |
| Autenticación | Encabezado `Authorization: Bearer JARVIS_TOKEN` |
| Tiempo límite por intento | 180 s |

Se crea o actualiza con `infra/cloud-scheduler/programar-revision-correo.sh '<PROYECTO>' '<URL_CLOUD_RUN>'`.
El script lee el token de Secret Manager sin imprimirlo. Si se rota `JARVIS_TOKEN`, hay que volver a
correrlo. Cloud Scheduler da 3 trabajos gratis por cuenta de facturación; con este quedan 2.

## Avisos de salida (desde el 27/11/2026)

`infra/cloud-scheduler/programar-avisos.sh '<PROYECTO>' '<URL_CLOUD_RUN>'` cambia
`jarvis-despertador` para que llame `POST /tareas/avisos` con el token, cada 10 minutos de
4:00 a 23:50 en `America/Monterrey` (desde las 4 por los vuelos temprano). Sigue despertando al
servidor. Si se rota `JARVIS_TOKEN`, hay que volver a correrlo.
