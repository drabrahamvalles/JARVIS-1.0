# Atajo Agendar Pantalla

Se activa con doble toque en la parte trasera del iPhone
(Accesibilidad → Tocar → Toque posterior → Doble toque).

## Acciones
1. Tomar captura de pantalla (antes de dictar).
2. Redimensionar imagen: ancho 1200.
3. Convertir imagen: JPEG, calidad 80 %, sin metadatos.
4. Codificar en Base64: sin saltos de línea.
5. Dictar texto: Español (México).
6. Obtener ubicación actual: precisión a 1 km.
7. Obtener contenido de URL: POST a `<URL_DEL_SERVICIO>/captura`.
   - Encabezado `Authorization: Bearer <TOKEN>`.
   - Cuerpo JSON: `texto`, `imagen_base64`, `lat`, `lon`, `ciudad`,
     `dispositivo` = `iphone`.
8. Obtener diccionario de Contenido de URL.
9. Obtener valor `tipo`.
10. Si `tipo` es `evento`: obtener `titulo`, `inicio`, `fin` y `lugar`, y
    Agregar evento al calendario de Google, sin hoja de redacción.
11. De lo contrario, si `tipo` es `recordatorio`: obtener `titulo` e
    `inicio`, y Agregar recordatorio a Tareas con alerta a la hora de
    `inicio`.
12. Obtener valor `respuesta` y Leer texto (Siri Voz 2).

## Notas
- Para que el Si permita "es", la variable `tipo` debe ser de tipo Texto.
- Cada "Obtener valor" debe leer de Diccionario, no del valor anterior.
- Con ida y vuelta en pantalla, el servidor separa los viajes y elige el
  próximo.
- No usar con expedientes ni datos de pacientes: la imagen va a OpenAI.
