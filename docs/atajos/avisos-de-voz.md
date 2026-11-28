# Atajo: avisos de salida en voz

JARVIS se manda un correo con el asunto «Aviso de JARVIS» cuando toca salir. Esta
automatización del iPhone lo lee en voz alta sin tocar nada.

Requisito: la cuenta de Gmail conectada a JARVIS debe estar en la app **Mail** del
iPhone (Configuración → Apps → Mail → Cuentas).

1. Atajos → **Automatización** → **+** → **Correo**.
2. **Remitente:** la cuenta de Gmail de JARVIS. **Asunto contiene:** `Aviso de JARVIS`.
3. Elegir **Ejecutar inmediatamente** y desactivar **Notificar al ejecutar**.
4. Acciones:
   1. **Obtener detalles de correo** → *Cuerpo* del correo de entrada del atajo.
   2. **Leer texto** → el cuerpo, con **Voz 2**, Español (México), «Esperar hasta que
      termine» encendido.
5. Prueba: con el iPhone bloqueado, mandarse un correo con ese asunto desde la misma
   cuenta. Debe leerlo en voz alta.
