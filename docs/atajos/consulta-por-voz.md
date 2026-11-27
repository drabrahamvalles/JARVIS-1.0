# Atajo JARVIS (consulta por voz)

Se activa con el Botón de Acción o con "Oye Siri, JARVIS".

## Acciones
1. Dictar texto: Español (México), dejar de escuchar después de la pausa.
2. Obtener ubicación actual: precisión a 100 m.
3. Obtener contenido de URL: POST a `<URL_DEL_SERVICIO>/ask`.
   - Encabezado `Authorization: Bearer <TOKEN>`.
   - Cuerpo JSON: `texto` (Texto dictado), `lat` y `lon` (Ubicación
     actual), `dispositivo` = `iphone`.
4. Obtener valor del diccionario: `respuesta`.
5. Leer texto: Español (México), voz Siri Voz 2, velocidad y tono al centro.

## Notas
- Las voces "mejoradas" de iOS se trababan dentro de Atajos; las de Siri no.
- Si "Leer texto" queda arriba de "Obtener valor", la variable se pone en
  rojo y no habla.

## Recordatorios por voz (fase 4.4)

Después de «Obtener valor del diccionario: respuesta», agrega:

1. Obtener valor del diccionario: `recordatorio_titulo` en Contenido de URL.
2. Si «Valor del diccionario» tiene algún valor:
   1. Obtener valor del diccionario: `recordatorio_alerta` en Contenido de URL.
   2. Si ese valor tiene algún valor: Nuevo recordatorio con el título del paso 1,
      lista Tareas, alerta a una hora = `recordatorio_alerta`.
   3. De lo contrario: Nuevo recordatorio con el título, sin alerta.
3. Leer texto sigue leyendo `respuesta` (elige esa variable tocando su acción).

## Conversación continua

Para no volver a presionar el botón después de cada respuesta:

1. Pon todas las acciones dentro de **Repetir 10 veces**.
2. Justo después de Dictar texto, agrega **Si** Texto dictado **contiene** `gracias`
   (o `eso es todo`): Leer texto «A sus órdenes, Dr. Valles» y **Detener este atajo**.
3. Si no dices nada, el dictado termina el atajo solo.

JARVIS recuerda los últimos diez turnos, así que «¿y por qué?» o «sí, bórralo»
funcionan dentro de la misma conversación.
