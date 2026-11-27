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
