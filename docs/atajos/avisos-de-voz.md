# Atajos: avisos de voz, preguntas de JARVIS y ubicación

## 1. Avisos y preguntas en voz

JARVIS se manda un correo con el asunto «Aviso de JARVIS» cuando toca salir o cuando
quiere preguntar algo. Esta automatización lo lee en voz alta y, si es pregunta,
escucha la respuesta.

Requisito: la cuenta de Gmail conectada a JARVIS debe estar en la app **Mail** del
iPhone (Configuración → Apps → Mail → Cuentas).

1. Atajos → **Automatización** → **+** → **Correo**.
2. **Remitente:** la cuenta de Gmail de JARVIS. **Asunto contiene:** `Aviso de JARVIS`.
3. **Ejecutar inmediatamente**, sin **Notificar al ejecutar**.
4. Acciones:
   1. **Obtener detalles de correo** → *Cuerpo*.
   2. **Leer texto** → el cuerpo, **Voz 2**, Español (México), «Esperar hasta que
      termine» encendido.
   3. **Si** el cuerpo **contiene** `?`:
      1. **Dictar texto**.
      2. **Obtener ubicación actual** (precisión Óptima).
      3. **Obtener contenido de URL** → `POST /ask` igual que el Atajo JARVIS, con el
         texto dictado, lat y lon.
      4. **Obtener valor del diccionario** `respuesta` → **Leer texto** con Voz 2.
5. Prueba: con el iPhone bloqueado, mandarse un correo con ese asunto desde la misma
   cuenta. Debe leerlo en voz alta.

## 2. Ubicación automática (para aprender lugares)

Una automatización por horario; cada una corre el mismo atajo «JARVIS Ubicación».

Atajo «JARVIS Ubicación»:
1. **Obtener ubicación actual** (precisión **Óptima**).
2. **Obtener contenido de URL** → `POST https://<URL_CLOUD_RUN>/ubicacion`, encabezado
   `Authorization: Bearer <JARVIS_TOKEN>`, cuerpo JSON `{"lat": Latitud, "lon": Longitud}`.

Automatizaciones (Atajos → Automatización → **+** → **Hora del día**), todas con
**Ejecutar inmediatamente**: 8:00, 11:00, 14:00, 17:00, 20:00 y 22:30.

Para que la ubicación sea exacta: Configuración → Privacidad y seguridad → Localización →
Atajos → **Ubicación exacta** encendida.
