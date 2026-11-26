# Protocolo JARVIS

Plan por fases. Una fase se cierra cuando funciona en uso real, no solo
en pruebas.

## Reglas
- Nada sale hacia otras personas sin mi confirmación. Agregar algo a mi
  propio calendario no la necesita.
- Llaves y tokens solo en .env y Secret Manager.
- Todo endpoint, excepto /health, pide token.
- Cero datos identificables de pacientes.
- Ningún costo mensual fijo sin mi aprobación.
- Lo que tiene que ser exacto lo decide el servidor; el modelo solo redacta.

## Fases

| Fase | Qué incluye | Estado |
|---|---|---|
| 0 | Repositorio, cuentas, AGENTS.md | Validada (23/10/2026) |
| 1 | Preguntas por voz, zona horaria, elección de modelo | Validada (24/10/2026) |
| 2 | Briefing al apagar la alarma | Validada (26/11/2026) |
| 2.5 | Captura de pantalla a calendario y recordatorios | Validada (26/11/2026) |
| 4 | Memoria, calendario (leer y borrar con confirmación), Gmail de solo lectura, recordatorios por voz | Siguiente |
| 5 | WHOOP: recuperación y sueño en el briefing | Pendiente |
| 3 | Rutas y tráfico al subir al carro | Pendiente |
| 6 | Voz propia, panel web, conversación con interrupción, "Hey Jarvis" en la Mac | Pendiente |
| 7 | FRIDAY: agente en la Mac que ejecuta tareas | Pendiente |
| 8 | WhatsApp con capturas y borradores | Pendiente |
| 9 | Cuarto y consultorio | Pendiente |

El orden cambió: WHOOP necesita la memoria de la fase 4, así que va antes
que las rutas.

## Decisiones

- Cloud Run para el servidor. Railway había cerrado registros y Render
  cobraba una cuota mensual.
- Python 3.15 en producción, la misma versión con la que se prueba en la
  Mac.
- No se puede reemplazar a Siri en México. JARVIS se abre con el Botón de
  Acción, con "Oye Siri, JARVIS" o con toque posterior.
- Para evitar el arranque en frío uso Cloud Scheduler cada 10 minutos de
  6:00 a 22:50, en vez de una instancia mínima. Costo: 0.
- La fase 4 usará Firestore en lugar de PostgreSQL: tiene nivel gratuito
  y no cobra por estar encendida. Se diseña lista para varios usuarios.
- El modelo de captura mantiene razonamiento "low" y detalle de imagen
  "high". Prefiero que tarde unos segundos más a que lea mal un número
  de vuelo.
- WhatsApp no usará librerías no oficiales: pueden bloquear el número.
- Voz: Siri Voz 2 por ahora. La voz propia llega en la fase 6.

## Pendientes con fecha

- Antes del 21/01/2027: activar la cuenta de pago de Google Cloud y usar
  el crédito restante.
