# JARVIS · Fase 1

Servidor FastAPI para ejecutarse en tu Mac. No se ha desplegado ningún servicio.
Recibe texto y devuelve texto preparado para escucharse. La captura de voz y la
síntesis de audio corresponden al cliente y quedan fuera de esta fase.

## Ejecutar en este Mac

El entorno `.venv` ya está instalado. Las variables de `.env` están vacías: configura
localmente `OPENAI_API_KEY` y `JARVIS_TOKEN` antes de usar `/ask`. Son dos secretos
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
Si falta `JARVIS_TOKEN`, `/ask` permanece cerrado con `503`.

## Modelo y personalidad

`config/config.yaml` define dos modelos y permite cambiarlos sin editar Python:

- `gpt-6-luna` atiende las solicitudes normales con razonamiento `low`.
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
No registra el texto de entrada o salida. El cálculo suma todas las rondas de
herramientas y no sustituye la factura del proveedor.

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
correspondan. La ciudad configurada, Monterrey, es una referencia; no se afirma
que el dispositivo esté allí. Las coordenadas no se envían a OpenAI en esta fase.

JARVIS dispone de tres herramientas: fijar una zona manual, volver al modo
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
Se incluyen el reloj y las tres herramientas de zona horaria, una por archivo.

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

Las pruebas cubren HTTP, autenticación, seis ciudades por coordenadas, horario de
verano, estado manual/automático, memoria, enrutamiento, costos, descubrimiento de
módulos y function calling con transporte simulado. No consumen crédito ni envían
datos a OpenAI.

El servidor conserva en memoria los últimos diez turnos completos y los pierde al
reiniciar. Sólo añade intercambios exitosos; no persiste resultados de herramientas,
coordenadas ni etiquetas de dispositivo. Se solicita `store=False` a Responses;
esto no modifica las políticas de retención del proveedor.

## Preparado para Railway o Render

No se ha hecho ningún despliegue. Para el futuro, ambos pueden usar el mismo
código y estos comandos, con Python 3.12:

- Instalación: `pip install -r requirements.txt`.
- Arranque: `python -m app` (también declarado en `Procfile`).
- Health check: `/health`.
- Secretos del servicio: `OPENAI_API_KEY` y `JARVIS_TOKEN`.

El puerto se obtiene de `PORT`. Cuando el proveedor define `PORT`, escucha en
`0.0.0.0` salvo un `HOST` explícito. Con `HOST` y `PORT` vacíos, el servidor usa
`127.0.0.1:8000`. En Railway debe usarse el puerto asignado por el proveedor.
`data/estado.json` puede perderse al reiniciar o redesplegar un contenedor con
almacenamiento efímero.
