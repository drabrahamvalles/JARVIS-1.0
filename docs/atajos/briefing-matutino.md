# Atajo BRIEFING y automatización de la alarma

## Atajo BRIEFING
1. Ajustar volumen: 60 %.
2. Buscar eventos de calendario: fecha de inicio es hoy, del más antiguo
   al más reciente.
3. Repetir con cada elemento → Texto: `Título a las Fecha de inicio`
   (fecha: ninguno, hora: corta).
4. Buscar recordatorios: no completados y con fecha límite hoy.
5. Obtener ubicación actual: precisión a 1 km.
6. Obtener contenido de URL: POST a `<URL_DEL_SERVICIO>/briefing`.
   - Encabezado `Authorization: Bearer <TOKEN>`.
   - Cuerpo JSON: `fecha_iso` (Fecha actual, ISO 8601 sin hora),
     `eventos` (Resultados de repetición), `recordatorios`, `lat`, `lon`,
     `ciudad`.
7. Obtener valor del diccionario: `respuesta`.
8. Leer texto: Español (México), voz Siri Voz 2.

## Automatización "Alarma BRIEFING"
- Cuando se detenga: Despertador (alarma del horario de sueño).
- Ejecutar inmediatamente, sin notificar.
- Acción: Ejecutar atajo BRIEFING.

## Notas
- El servidor se mantiene despierto de 6:00 a 22:50 (Cloud Scheduler).
- Con la ubicación en "Óptima" tardaba unos 30 s más.
