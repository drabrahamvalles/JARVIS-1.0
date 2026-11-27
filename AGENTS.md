# Proyecto JARVIS

## Quién soy
Dr. Valles, médico mexicano, principiante en programación (aprendiendo R y ciencia de datos).
Explícame cada decisión en español, en lenguaje simple, y por qué se hace así.

## Cómo trabajamos
- Claude diseña el plan en otra conversación. Codex lo implementa, prueba y despliega.
- Si una orden contradice este archivo o ves una mejor opción, no la cambies por tu cuenta:
  explica la alternativa y espera mi decisión.
- Antes de programar, muéstrame el plan y espera mi aprobación.
- Al terminar cada tarea, entrega un resumen: archivos creados o modificados, comandos
  ejecutados, resultado de las pruebas y pendientes.

## Qué es
Asistente personal por voz. Servidor Python + FastAPI desplegado en Google Cloud Run.
Cerebro: API de OpenAI con function calling; el modelo se define en config/config.yaml.
Clientes: Atajos de iOS (iPhone y Mac), programa "Hey Jarvis" en la Mac y, después,
satélites de voz en el cuarto y el consultorio.

## Reglas
- Guardo las llaves y los tokens en `.env` o en Cloud Run. Nunca los pongas en el código ni me los pidas por chat. Mantén `.env.example` al día con los nombres de las variables.
- Todo endpoint, excepto /health, exige el encabezado Authorization: Bearer JARVIS_TOKEN.
- Una herramienta por archivo en app/tools/.
- Escribe pruebas en tests/ para cada herramienta y ejecútalas antes de dar algo por terminado.
- Nada se envía a nombre del usuario sin su confirmación explícita.
- Nunca proceses datos identificables de pacientes.
- Nunca crees un recurso con costo mensual fijo (instancias mínimas, bases de datos siempre
  encendidas, IPs reservadas, etc.) sin aprobación explícita del usuario.
- Al terminar cada tarea, haz commit con un mensaje descriptivo en español.

## Entorno
- Mac: MacBook Air M3. iPhone 15 Pro Max. Calendario de Google sincronizado con Apple. Correo Gmail.
- Python del sistema: 3.15. Si una librería no es compatible, usa un entorno virtual con
  Python 3.13 solo para este proyecto y explícame por qué.

## Protocolo
Construimos por fases según docs/protocolo-jarvis.md.
Fase actual: 4 (4.1 y 4.2 hechas; 4.3 Gmail de solo lectura por autorizar; 4.4 recordatorios: falta el Atajo).
