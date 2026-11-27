# Notas técnicas

## API

`GET /health` devuelve `{"status":"ok"}`. Para los demás endpoints usa `Authorization: Bearer <JARVIS_TOKEN>`.

### Consulta por voz

`POST /ask` necesita el encabezado `Authorization: Bearer <JARVIS_TOKEN>`.

```json
{
  "texto": "¿Qué hora es, JARVIS?",
  "lat": 25.6866,
  "lon": -100.3161,
  "dispositivo": "iPhone"
}
```

`texto` es obligatorio y admite hasta 12 000 caracteres. Los demás campos son
opcionales. Las coordenadas se envían juntas como números: latitud de −90 a 90
y longitud de −180 a 180. También puedes omitir ambas o enviarlas como `null`.
El dispositivo es una etiqueta opcional de hasta 120 caracteres.

La respuesta exitosa contiene únicamente `respuesta`:

```json
{"respuesta": "A su servicio, Dr. Valles."}
```

## Briefing matutino

`POST /briefing` usa el mismo encabezado Bearer y recibe:

```json
{
  "fecha_iso": "2026-10-24T07:00:00-07:00",
  "lat": 23.2494,
  "lon": -106.4111,
  "ciudad": "Mazatlán",
  "eventos": ["09:00 Consulta administrativa"],
  "recordatorios": ["Comprar café"]
}
```

`fecha_iso` admite `AAAA-MM-DD` o una fecha y hora ISO 8601 con zona. Eventos y
recordatorios aceptan listas o texto con un elemento por renglón. Los renglones
vacíos se ignoran. Ambos campos son obligatorios y pueden quedar vacíos.

El briefing menciona `ciudad` si la envías. Con coordenadas y sin ciudad, omite el
nombre de la ciudad. Si faltan las coordenadas, consulta el clima de Monterrey y
menciona Monterrey salvo que hayas enviado otra ciudad. Las coordenadas pueden
omitirse o enviarse juntas como `null` o cadenas vacías. Nunca envíes nombres ni
otros datos identificables de pacientes en eventos o recordatorios.

El briefing lee el clima de hoy y la agenda. Los lunes añade un resumen de la
semana. Si falla el pronóstico o la agenda está vacía, el servidor lo indica.

### Cómo se prepara

- Open-Meteo devuelve ocho días de mínimas, máximas y probabilidad de lluvia.
  El servidor calcula la zona IANA a partir de las coordenadas y redondea las
  temperaturas en °C antes de redactar. Las reglas de ropa y paraguas se
  configuran en [config.yaml](../config/config.yaml).
- El saludo usa la hora actual en la zona activa. La fecha que se lee viene
  de `fecha_iso`. La respuesta está pensada para leerse en voz alta, sin
  Markdown y en alrededor de 110 palabras.
- El resumen del lunes menciona lluvia de 50 % o más, cambios de al menos
  5 °C y frío o calor notables en una o dos oraciones.
- El servidor elimina avisos contradictorios y añade los avisos de clima no
  disponible y agenda vacía cuando corresponden. Usa una plantilla fija si
  detecta varios errores o si un error deja el texto incoherente al corregirlo.

## Captura de pantalla

`POST /captura` analiza una captura de pantalla y devuelve los datos que el Atajo
necesita para crear automáticamente un evento o recordatorio, sin una confirmación
intermedia:

```json
{
  "texto": "Ponlo en mi agenda",
  "imagen_base64": "<imagen PNG, JPEG, WebP o GIF no animado>",
  "lat": 23.2494,
  "lon": -106.4111,
  "ciudad": "Mazatlán",
  "dispositivo": "iPhone"
}
```

La imagen puede ser Base64 puro o una URL `data:image/...;base64,...` y no puede
superar 5 MB una vez decodificada. Sólo se mantiene en memoria durante la petición:
no se escribe en disco ni aparece en los registros. Nunca envíes capturas con nombres
u otros datos identificables de pacientes.

La respuesta siempre conserva esta forma:

```json
{
  "tipo": "evento",
  "titulo": "Cena con Ana",
  "inicio": "2026-11-05 09:00",
  "fin": "2026-11-05 10:00",
  "lugar": "Centro",
  "notas": null,
  "respuesta": "Listo, Dr. Valles."
}
```

Las fechas y horas se resuelven en la zona horaria del usuario. Un evento sin duración
dura una hora. Un recordatorio con fecha pero sin hora usa
`hora_recordatorio_por_defecto` de `config/config.yaml`. Un recordatorio claro sin
fecha se crea sin vencimiento. Si un evento no tiene fecha u hora, o no hay una acción
clara, `tipo` es `ninguno` y `respuesta` explica qué faltó. Las extracciones
válidas responden con `Listo, Dr. Valles.` El Atajo crea el elemento en Calendario
o Recordatorios y lee esa respuesta en voz alta.

Los vuelos se titulan `Vuelo ORIGEN → DESTINO (números de vuelo)` sin nombres de
pasajeros. Una conexión forma parte del mismo viaje. La ida y el regreso se procesan
por separado. Si el texto pide `ida`, `regreso`, un día o una fecha, el servidor
elige ese viaje. De otro modo, selecciona la próxima salida.

El servidor convierte la salida del primer tramo y la llegada del último a la zona
activa del usuario. Primero consulta `zonas_horarias_vuelos` de `config/config.yaml`,
incluidos alias como `AICM → MEX` y `AIFA → NLU`. Si el aeropuerto no está allí,
valida la zona IANA propuesta por el modelo. Si la zona sigue sin resolverse,
conserva la hora impresa e indica en `notas` si es la hora local del origen o del
destino. Una escala dudosa se marca con `Revisar escalas.`. Se rechazan los vuelos
que empiezan y terminan en el mismo aeropuerto, duran más de 24 horas o terminan antes
de la salida o a la misma hora.

## Errores de la API

- `401` si falta el token Bearer o es incorrecto.
- `413` si la imagen de `/captura` supera 5 MB.
- `422` si el cuerpo de la petición es inválido.
- `502` si OpenAI falla o devuelve una respuesta incompleta.
- `503` si falta configuración, OpenAI está ocupado o se agotó su cuota. Esto
  incluye los endpoints protegidos cuando falta `JARVIS_TOKEN`.
- `504` si vence el tiempo de espera.

`/health` comprueba que el proceso responde.

## Modelo y personalidad

[config.yaml](../config/config.yaml) define los modelos y permite cambiarlos sin editar Python:

- `gpt-6-luna` atiende las solicitudes normales con razonamiento `low`.
- `gpt-6-luna` redacta también el briefing en una llamada independiente y sin memoria.
- `gpt-6-luna` analiza capturas con visión y salida JSON estructurada.
- `gpt-6.1-sol` atiende medicina, ciencia y razonamiento con esfuerzo `medium`.
- La frase "a fondo" usa Sol con modo de razonamiento `pro`, esfuerzo `high` y
  respuesta extensa.
- "Modo científico" mantiene Sol y verbosidad alta hasta recibir "modo normal".

La selección por tema se hace localmente y no consume una llamada adicional. Los
precios estándar configurados por millón de tokens son USD 0.10/0.50 para entrada
y salida de Luna, y USD 2/10 para Sol. Las tarifas de caché también están en YAML.
Fuentes: [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) y
[razonamiento `pro`](https://developers.openai.com/api/docs/guides/reasoning).

Cada petición terminada registra modelo, ruta, parámetros, tokens y costo aproximado.
No registra el texto de entrada o salida. `/briefing` tampoco registra ciudad,
eventos, recordatorios ni coordenadas. `/captura` registra sólo modelo, tokens, costo,
latencia y estado: nunca la imagen, el texto o los datos extraídos. El cálculo no
sustituye la factura del proveedor.

La personalidad se carga de [personalidad.md](../config/personalidad.md): español de México,
"Dr. Valles", estilo británico, humor sutil y máximo cuatro oraciones salvo
petición de detalle. En medicina, pide nivel de médico y reconocimiento de la
incertidumbre. Estas reglas se envían como instrucciones en cada llamada. Se
conserva la respuesta completa para evitar omitir información clínica.

## Zona horaria

El modo predeterminado es `automatico`. Con coordenadas, `timezonefinder`
calcula una zona IANA localmente, sin consultar servicios externos de ubicación.
Sin coordenadas o sin una zona reconocible, usa `America/Monterrey`.

El reloj y las expresiones como "hoy" o "mañana" reciben la zona resuelta.
`zoneinfo` aplica las reglas IANA, incluidos los cambios estacionales donde
correspondan. La ciudad configurada, Monterrey, es la ubicación predeterminada para
el clima. Las coordenadas no se envían a OpenAI.

JARVIS dispone de tres herramientas de zona: fijar una zona manual, volver al modo
automático y consultar la zona activa. Para cualquier ciudad, el modelo propone
la zona IANA y el servidor la valida con `zoneinfo.available_timezones()`. Si la
ciudad es ambigua, JARVIS pide el país o la región antes de cambiarla. También pide
aclaración si la zona es inválida.

En Cloud Run, Firestore conserva el modo manual y la zona por usuario. En la Mac,
el usuario principal conserva su estado en `data/estado.json`. Toda la carpeta
`data/` está excluida de Git. Un cambio hecho por una herramienta se aplica
desde esa misma petición.

## Agregar herramientas

Crea un módulo Python dentro de `app/tools/`, usa `@tool`, agrega docstring
y anota los tipos de sus parámetros. El servidor descubre el módulo al reiniciar.

```python
from app.registry import tool

@tool
def sumar(a: float, b: float) -> float:
    """Suma dos números."""
    return a + b
```

También se admiten funciones `async`. Si necesitas ubicación o zona horaria,
agrega `*, context: ToolContext` e importa `ToolContext` de `app.context`.
Ese parámetro lo inyecta el servidor y no puede proporcionarlo el modelo.
Se incluyen el reloj, el clima y las tres herramientas de zona horaria, una por archivo.

Los esquemas se generan con Pydantic y el SDK oficial en modo estricto. Solo se
ejecutan nombres registrados y argumentos validados. El cerebro devuelve los
resultados a Responses, conserva los elementos de razonamiento y permite hasta
tres rondas de herramientas antes de solicitar una respuesta final sin herramientas.
Los errores no exponen datos internos. Las herramientas de zona guardan el estado
cuando el usuario pide fijar la zona o volver a automático.

Referencia: [function calling](https://developers.openai.com/api/docs/guides/function-calling).

## Verificación

```sh
python -m pytest -q
ruff check app tests
ruff format --check app tests
python -m pip check
```

Las pruebas cubren HTTP, autenticación, fechas de Atajos, clima, reglas de ropa,
agenda, captura visual, salida estructurada, límite de imagen, recordatorios con y sin
fecha, títulos y zonas horarias de vuelos, ubicación predeterminada, seis ciudades por
coordenadas, horario de verano, memoria, enrutamiento, costos, privacidad del registro,
descubrimiento de módulos y function calling. Las pruebas simulan Open-Meteo,
OpenAI y Firestore. Se ejecutan sin red ni crédito.

## Memoria persistente

`/ask` conserva hasta diez pares de pregunta y respuesta por usuario. Los turnos
dejan de usarse a los siete días. En Cloud Run, Firestore elimina por TTL los
documentos expirados. El estado de zona horaria dura hasta que el usuario lo
cambie. El despliegue inicial empieza con historial vacío y zona automática.

La Mac usa archivos bajo `data/`. Para usar el emulador, exporta
`FIRESTORE_EMULATOR_HOST=127.0.0.1:8080` antes de arrancar JARVIS. En Cloud Run
el servidor elige Firestore por la variable `K_SERVICE` de la plataforma.

Si falla una lectura de almacenamiento, `/ask` continúa sin historial y resuelve
la zona por coordenadas cuando están disponibles. Si falla el guardado de un turno,
se conserva la respuesta y el registro solo indica la operación y el tipo de error.
Si falla un cambio explícito de zona, responde «No pude guardarlo, Dr. Valles.».

Las coordenadas, la etiqueta de dispositivo y los resultados directos de las
herramientas quedan fuera del historial. El servidor envía `store=False` a
Responses. Las políticas de retención del proveedor aplican a esas llamadas.

## Agenda (fase 4.2)

`/ask` puede consultar y borrar eventos de Google Calendar con tres
herramientas:

- `consultar_agenda(desde, hasta, texto)`: fechas locales `AAAA-MM-DD`, máximo
  31 días. Devuelve hasta 25 eventos ordenados, con la hora convertida a la zona
  activa. Si el mismo evento aparece en dos calendarios compartidos, se muestra
  una vez.
- `proponer_borrado_evento(evento_id)`: no borra. Guarda la propuesta en
  Firestore (`usuarios/{id}/estado/borrado_pendiente`) durante 10 minutos y le
  pide al modelo que pregunte.
- `confirmar_borrado_evento()`: solo borra si la propuesta sigue vigente, se hizo
  en una petición anterior y el texto actual del usuario es afirmativo («sí»,
  «bórralo», «adelante») sin negación. Borra con `sendUpdates=none` para que
  Google no escriba a los invitados.

La cuenta de servicio de Cloud Run lee los calendarios que el usuario comparte
con su correo («Hacer cambios en eventos»). Los identificadores de esos
calendarios van separados por comas en el secreto `JARVIS_CALENDARIOS`. Sin ese
secreto, JARVIS responde que la agenda no está conectada. Los títulos de los
eventos llegan al modelo: no pongas nombres de pacientes en el calendario.

## Recordatorios por voz (fase 4.4)

Cuando el usuario dice «recuérdame…», el modelo llama `crear_recordatorio(titulo,
cuando)`. El servidor valida la fecha (formato local `AAAA-MM-DD HH:MM`; solo la
fecha usa 09:00; una hora pasada se rechaza) y `/ask` devuelve dos campos extra:

```json
{"respuesta": "Listo, Dr. Valles. Se lo recuerdo mañana a las 5.",
 "recordatorio_titulo": "Revisar los labs",
 "recordatorio_alerta": "2026-11-27 17:00"}
```

Sin recordatorio, `/ask` solo devuelve `respuesta`. Sin hora, falta
`recordatorio_alerta`. El servidor no toca Recordatorios: el Atajo JARVIS los
crea en el iPhone (ver [la guía del Atajo](atajos/consulta-por-voz.md)).
