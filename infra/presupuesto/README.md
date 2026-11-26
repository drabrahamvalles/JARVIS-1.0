# Presupuesto de Google Cloud

Configuración consultada el 26 de noviembre de 2026 en la cuenta de facturación
asociada a `<PROYECTO>`.

| Ajuste | Valor |
| --- | --- |
| Nombre | JARVIS mensual ~USD 5 |
| Importe y período | MXN 89.07 por mes calendario |
| Alcance | Un proyecto (`<PROYECTO>`), con todos los créditos incluidos |
| Umbrales | 50 %, 90 % y 100 % del gasto acumulado |
| Avisos | Canal de correo de Cloud Monitoring habilitado (`<CANAL_DE_AVISOS>`) con destino a `<CORREO>` |
| Pub/Sub | Sin tema configurado |

Los umbrales disparan avisos. Llegar al 100 % no suspende el servicio.

Consultas de solo lectura:

```sh
gcloud billing projects describe '<PROYECTO>'
gcloud billing budgets list --billing-account='<CUENTA_DE_FACTURACION>'
```
