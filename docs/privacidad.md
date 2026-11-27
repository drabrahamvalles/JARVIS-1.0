# Privacidad de JARVIS

JARVIS es un asistente personal de uso privado. Lo usa una sola persona, su
autor, el Dr. Abraham Valles. No es un servicio público ni tiene otros usuarios.

## Qué datos usa

- **Gmail (`gmail.readonly` y `gmail.send`).** Busca y lee correos cuando el
  usuario se lo pide por voz, para resumirlos. Envía un correo nuevo solo
  cuando el usuario lo dicta y después confirma con un «sí» explícito. No
  borra, no archiva y no modifica correos.
- **Google Calendar.** Consulta, crea y borra eventos en los calendarios que el
  usuario compartió con la cuenta de servicio del proyecto. Para borrar pide
  confirmación.
- **WHOOP (solo lectura).** Lee la recuperación, el sueño, los ciclos y el
  esfuerzo para el briefing de la mañana y para preguntas como «¿cómo dormí?».
  No escribe nada en WHOOP. El token de acceso se guarda en Firestore porque
  WHOOP lo renueva en cada uso.
- **Ubicación aproximada** del iPhone, para la zona horaria y el clima.

## Dónde se procesan

- El servidor corre en Google Cloud Run, dentro del proyecto del autor.
- Para redactar las respuestas, el texto de la pregunta y los datos necesarios
  se envían a la API de OpenAI.
- La memoria de la conversación (cada pregunta con su respuesta) se guarda en
  Firestore y se borra sola a los 7 días. Si una respuesta resumió un correo,
  ese resumen se borra con ella.
- El texto completo de los correos no se guarda en ninguna base de datos: solo
  se lee en el momento de la consulta. Un borrador por enviar se guarda 10
  minutos mientras el usuario lo confirma y después se borra.

## Qué no hace

- No vende, comparte ni publica datos.
- No usa los datos de Google para entrenar modelos ni para publicidad.
- Cumple la Política de Datos del Usuario de los Servicios de las APIs de
  Google, incluidos los requisitos de uso limitado.

## Revocar el acceso

En myaccount.google.com → Seguridad → «Apps de terceros con acceso a tu
cuenta» → JARVIS → «Quitar acceso». Después de eso, JARVIS ya no puede leer
ni enviar correos. Para WHOOP: app de WHOOP → Configuración → apps conectadas
→ JARVIS → desconectar.

Contacto: abrahamvalles620@gmail.com
