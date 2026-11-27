"""Reglas compartidas para acciones que requieren un «sí» explícito del usuario."""

import re
import unicodedata
from datetime import timedelta

VIGENCIA = timedelta(minutes=10)

AFIRMACION = re.compile(
    r"\b(si|confirmo|confirmado|borralo|borrala|borralos|borralas|eliminalo|eliminala"
    r"|envialo|enviala|mandalo|mandala|adelante|hazlo|dale|claro|correcto|de acuerdo|ok|okay)\b"
)
# Un «sí, pero…» o un «ok, cambia…» pide cambios: no cuenta como confirmación.
NEGACION = re.compile(
    r"\b(no|espera|cancela|cancelalo|mejor no|todavia no|aun no|pero|cambia|cambialo"
    r"|corrige|corrigelo|modifica|agrega|quita)\b"
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def es_confirmacion(text: str) -> bool:
    normalized = _normalize(text)
    return bool(AFIRMACION.search(normalized)) and not NEGACION.search(normalized)
