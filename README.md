# JARVIS – LLM-Powered Personal Voice Assistant

**Status:** in progress · actively developed since October 2026

JARVIS is a personal voice assistant built by a physician with no formal software background.
It uses a large language model (OpenAI API) as its reasoning engine and is used by voice from
an iPhone. The project is also a hands-on way to learn how LLMs behave in real use, including
when their answers sound confident but are wrong.

## What works today

| Feature | Server (this repository) | iPhone (Apple Shortcuts) |
| --- | --- | --- |
| Voice Q&A | `/ask` answers the question | Captures the voice and reads the answer aloud |
| Morning briefing | `/briefing` writes the briefing: date, local weather with clothing advice, and the day's events and reminders | An automation triggers it when the alarm is turned off and reads it aloud |
| Screenshot capture | `/captura` extracts events and reminders from a screenshot, including flights across time zones | Adds the results to Calendar and Reminders |
| Model routing | Sends simple requests to a lighter model and complex ones to a more capable model, logging cost and latency | — |

The Apple Shortcuts clients are configured on the device and are not part of this repository.

## Roadmap

Memory and email integration · health-data integration · custom voice and desktop client ·
in-room voice devices

## How it is built

- **Server:** Python + FastAPI, configured for deployment on Google Cloud Run
- **Reasoning:** OpenAI API with function calling (one tool per file in `app/tools/`)
- **Quality:** automated tests with pytest and linting with Ruff
- **Security:** the functional endpoints (`/ask`, `/briefing`, `/captura`) require a bearer token;
  interactive API docs are disabled in production; secrets live only in environment variables
- **Privacy rules:** nothing is sent on the user's behalf without explicit confirmation, and
  identifiable patient data must never be sent to JARVIS

## How it was developed

I act as the project lead: I define the requirements, review each implementation plan, test
the results, and decide on changes. The code is written by an AI coding agent (OpenAI Codex),
with Claude (Anthropic) serving as the architectural guide. The working rules for the agent are
documented in [`AGENTS.md`](AGENTS.md).

**Author:** Abraham Valles, MD · [LinkedIn](https://www.linkedin.com/in/abraham-valles-75560a3b1/)

## Documentación técnica (español)

Servidor FastAPI desplegado en Google Cloud Run y ejecutable también en la Mac.
Recibe preguntas y genera un briefing matutino preparado para escucharse. La captura
de voz, la alarma, las capturas de pantalla y la síntesis de audio corresponden a los
clientes de Apple.

## Ejecutar en este Mac

El entorno `.venv` ya está instalado. Las variables de `.env` están vacías: configura
localmente `OPENAI_API_KEY` y `JARVIS_TOKEN` antes de usar `/ask` o `/briefing`. Son dos secretos
distintos; no los pongas en `config.yaml` ni los compartas en el chat.

Desde la carpeta del proyecto:

```sh
source .venv/bin/activate
python -m app
```

El servidor local escucha en `127.0.0.1:8000`. La documentación interactiva está
en [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
Reinicia el proceso después de editar `.env`, la configuración, la personalidad
o los módulos de herramientas. Para detenerlo, usa Control-C.

La instalación se verificó con el Python 3.15 del sistema. Para recrear el entorno:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

En una instalación nueva, copia `.env.example` a `.env`, configura
`OPENAI_API_KEY` y genera `JARVIS_TOKEN` con
`python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
No sobrescribas tu `.env` actual. El archivo está excluido de Git.

## Endpoints

`GET /health` no necesita token y responde exactamente:

```json
{"status": "ok"}
```

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

`fecha_iso` admite `AAAA-MM-DD` o una fecha-hora ISO 8601 completa con zona. Eventos
y recordatorios aceptan listas o un solo texto con un elemento por renglón; los
renglones vacíos se ignoran. Ambos campos son obligatorios pero pueden estar vacíos.
`ciudad` es opcional: si llega se
menciona; si no llega con coordenadas, se omite. Si las coordenadas se omiten, son
`null` o cadenas vacías, se usan Monterrey y sus coordenadas configuradas. Nunca
envíes nombres ni otros datos identificables de pacientes en eventos o recordatorios.

El servidor consulta Open-Meteo sin llave para obtener ocho días de mínimas, máximas
y probabilidad de lluvia en °C. Usa la zona IANA calculada a partir de las coordenadas.
Las reglas de chamarra, suéter, paraguas, calor y sus textos están en
`config/config.yaml`. Si el clima falla, el briefing continúa sin inventarlo.
Los avisos de clima no disponible y agenda vacía los agrega el servidor, no el
modelo. El servidor elimina oraciones contradictorias y usa una plantilla fija si
detecta varios errores o si la reparación deja un texto incoherente.

El saludo usa la hora actual de la zona resuelta, no `fecha_iso`. Las temperaturas se
redondean antes de redactar. Los lunes incluye en una o dos oraciones sólo lluvia de
50 % o más, cambios de al menos 5 °C y frío o calor notables; no enumera cada día.
Los demás días sólo incluye el clima de hoy. La respuesta es prosa hablada sin
markdown y de aproximadamente 110 palabras.

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
`hora_recordatorio_por_defecto` de `config/config.yaml`; un recordatorio claro sin
fecha se crea sin vencimiento. Si un evento no tiene fecha u hora, o no hay una acción
clara, `tipo` es `ninguno` y `respuesta` explica brevemente qué faltó. Los eventos y
recordatorios confirmados responden sólo `Listo, Dr. Valles.` El Atajo de iOS es quien
crea finalmente el elemento en Calendar o Recordatorios y lee esa respuesta en voz alta.

Los vuelos se titulan `Vuelo ORIGEN → DESTINO (números de vuelo)` sin nombres de
pasajeros. El modelo separa los viajes visibles y sus tramos: una conexión pertenece al
mismo viaje, mientras que ida y regreso nunca se combinan. Si el texto pide `ida`,
`regreso`, un día o una fecha, el servidor elige ese viaje; de otro modo selecciona la
próxima salida que no haya pasado.

El servidor convierte la salida del primer tramo y la llegada del último a la zona
activa del usuario. Primero consulta `zonas_horarias_vuelos` de `config/config.yaml`,
incluidos alias de código como `AICM → MEX` y `AIFA → NLU`; si el aeropuerto no está
allí, valida la zona IANA propuesta por el modelo. Si ninguna fuente permite resolverla,
no descarta el evento: conserva la hora impresa y añade en `notas` que corresponde a la
hora local del origen o del destino. Una escala dudosa tampoco se descarta; se marca
`Revisar escalas.`. El servidor sí rechaza vuelos que empiezan y terminan en el mismo
aeropuerto, duran más de 24 horas o cuyo fin no es posterior al inicio.

Prueba local desde otra terminal, cargando las variables de tu `.env`:

```sh
source .venv/bin/activate
set -a
source .env
set +a
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ask \
  -H "Authorization: Bearer $JARVIS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"texto":"¿Qué hora es?","lat":25.6866,"lon":-100.3161,"dispositivo":"Mac"}'
```

Errores: `401` si falta el Bearer o es incorrecto; `422` si el cuerpo es inválido;
`503` si falta configuración, hay saturación o se agotó la cuota de OpenAI;
`502` si OpenAI falla o no produce una respuesta completa; `504` si vence el
tiempo de espera. `/health` comprueba el proceso, no la clave ni la cuota de OpenAI.
Si falta `JARVIS_TOKEN`, todos los endpoints protegidos permanecen cerrados con `503`.

## Modelo y personalidad

`config/config.yaml` define los modelos y permite cambiarlos sin editar Python:

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

La personalidad se carga de `config/personalidad.md`: español de México,
"Dr. Valles", estilo británico, humor sutil y máximo cuatro oraciones salvo
petición de detalle. En medicina, pide nivel de médico y reconocimiento de la
incertidumbre. Estas reglas se envían como instrucciones en cada llamada;
no se recortan respuestas mecánicamente, lo que podría mutilar información clínica.

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
ciudad es ambigua, JARVIS debe pedir país o región antes de cambiarla; una zona
inválida también produce una solicitud de aclaración.

El modo manual se conserva en `data/estado.json`. Toda la carpeta `data/` está
excluida de Git. La escritura es atómica para no dejar un JSON parcial. El reloj
consulta el estado activo en cada ejecución, incluso si el modo cambió durante
la misma petición.

## Agregar herramientas

Crea un módulo Python dentro de `app/tools/`, usa `@tool`, agrega docstring
y anota los tipos de sus parámetros. Reinicia el servidor; no necesitas editar
`brain.py` ni mantener una lista central. Ejemplo:

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
Los errores no exponen datos internos. Las herramientas de zona sólo escriben el
estado local aprobado; cualquier herramienta nueva es código local de confianza.

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
descubrimiento de módulos y function calling. Open-Meteo y OpenAI se simulan; las
pruebas no usan red ni crédito.

El servidor conserva en memoria los últimos diez turnos completos y los pierde al
reiniciar. Sólo añade intercambios exitosos; no persiste resultados de herramientas,
coordenadas ni etiquetas de dispositivo. Se solicita `store=False` a Responses;
esto no modifica las políticas de retención del proveedor.

## Despliegue en Google Cloud Run

El servicio `jarvis` se despliega desde el código fuente con Python 3.15. Cloud Run usa:

- Instalación: `pip install -r requirements.txt`.
- Arranque: `python -m app` (también declarado en `Procfile`).
- Health check: `/health`.
- Secretos del servicio: `OPENAI_API_KEY` y `JARVIS_TOKEN`.

El puerto se obtiene de `PORT`. Cuando Cloud Run define `PORT`, escucha en
`0.0.0.0` salvo un `HOST` explícito. Con `HOST` y `PORT` vacíos, el servidor usa
`127.0.0.1:8000`. La documentación interactiva sólo se expone en modo local.
`data/estado.json` puede perderse al reiniciar o redesplegar un contenedor con
almacenamiento efímero.
