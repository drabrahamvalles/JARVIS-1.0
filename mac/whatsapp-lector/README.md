# Lector de WhatsApp (fase 5.3)

Programa pequeño en Swift que corre en una Mac siempre prendida. Lee el archivo local
de WhatsApp para Mac (`ChatStorage.sqlite`) sin conectarse a WhatsApp: no hay riesgo
de bloqueo y no cuesta nada.

## Qué hace

1. A las 6:00, 15:00 y 21:00 (launchd; si la Mac estaba dormida, corre al despertar)
   copia el archivo a una carpeta temporal y lee los mensajes nuevos.
2. Salta los chats de `excluir` en `~/.jarvis/whatsapp.json` (por ejemplo, chats de
   pacientes).
3. Se queda solo con los mensajes que mencionan una fecha u hora («mañana», «el
   jueves», «a las 7», «19:00») y les agrega hasta 3 mensajes anteriores y 2
   posteriores del mismo chat como contexto. Lo demás no sale de la Mac.
4. Lo manda a `POST /whatsapp/mensajes`. El servidor salta lo clínico, quita los
   nombres de los chats antes de mandar nada al modelo, agenda y lo dice en el briefing.

## Instalar

1. WhatsApp para Mac con sesión iniciada (vinculado al iPhone).
2. `xcode-select --install` si no hay `swiftc`.
3. `mac/whatsapp-lector/instalar.sh '<PROYECTO>' '<URL_CLOUD_RUN>'`
4. Configuración del Sistema → Privacidad y seguridad → **Acceso total al disco** →
   **+** → `~/.jarvis/bin/whatsapp-lector` (Cmd+Shift+G y pega la ruta).
5. Prueba: `~/.jarvis/bin/whatsapp-lector --revisar`. Solo muestra las tablas y los
   conteos; no manda nada.

## Datos

- El token de JARVIS vive en el Llavero (servicio `jarvis`, cuenta `token`).
- `~/.jarvis/whatsapp-estado.json` guarda el último mensaje revisado.
- La primera corrida revisa solo las últimas 24 horas.
- Registro en `~/.jarvis/whatsapp.log` (solo conteos, sin contenido).
