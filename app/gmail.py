"""Cliente para leer el Gmail del Dr. Valles y enviar correos que él confirmó.

Gmail no acepta la cuenta de servicio de Cloud Run en una cuenta personal, así que
aquí se usa un token OAuth propio (gmail.readonly y gmail.send). El token vive en el
secreto JARVIS_GMAIL como JSON con client_id, client_secret y refresh_token; lo
genera scripts/autorizar_gmail.py y nunca pasa por el repositorio ni por el chat.
"""

import asyncio
import base64
import html
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
MAX_CORREOS = 10
MAX_CUERPO = 4000
_MESSAGE_ID = re.compile(r"[a-zA-Z0-9]{1,64}")
_TAGS = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)
_SPACES = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


class GmailNoConfigurado(Exception):
    """Falta el secreto JARVIS_GMAIL."""


class GmailError(Exception):
    """Gmail no respondió como se esperaba."""


class GmailSinPermisoDeEnvio(GmailError):
    """El token se autorizó solo para leer; hay que volver a autorizar con gmail.send."""


@dataclass(frozen=True)
class Credenciales:
    client_id: str
    client_secret: str
    refresh_token: str


def credentials_from_env(env: dict[str, str] | None = None) -> Credenciales | None:
    raw = (env if env is not None else os.environ).get("JARVIS_GMAIL", "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return Credenciales(
            client_id=str(data["client_id"]),
            client_secret=str(data["client_secret"]),
            refresh_token=str(data["refresh_token"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("JARVIS_GMAIL no tiene el formato esperado") from exc


def validate_message_id(value: str) -> str:
    value = value.strip()
    if _MESSAGE_ID.fullmatch(value) is None:
        raise ValueError("Identificador de correo inválido")
    return value


def _header(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name:
            return str(header.get("value", "")).strip()
    return ""


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", value, flags=re.IGNORECASE)
    return html.unescape(_TAGS.sub(" ", value))


def _body_text(payload: dict[str, Any]) -> str:
    plain, rich = [], []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_html_to_text(_decode(data)))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    text = "\n".join(plain) if plain else "\n".join(rich)
    lines = (_SPACES.sub(" ", line.replace("\xa0", " ")).strip() for line in text.splitlines())
    text = _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
    return text[:MAX_CUERPO]


def _local_time(raw: dict[str, Any], zone: ZoneInfo) -> str:
    try:
        moment = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, UTC)
    except (KeyError, TypeError, ValueError):
        return ""
    return moment.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _summary(raw: dict[str, Any], zone: ZoneInfo) -> dict[str, Any]:
    headers = (raw.get("payload") or {}).get("headers") or []
    return {
        "id": raw.get("id"),
        "de": _header(headers, "from")[:200],
        "asunto": (_header(headers, "subject") or "Sin asunto")[:300],
        "fecha": _local_time(raw, zone),
        "extracto": html.unescape(str(raw.get("snippet") or ""))[:300],
        "no_leido": "UNREAD" in (raw.get("labelIds") or []),
    }


class Gmail:
    def __init__(
        self,
        credentials: Credenciales | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if credentials is None:
            raise GmailNoConfigurado
        self._credentials = credentials
        self._transport = transport
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0), transport=self._transport)

    async def _access_token(self) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            async with self._client() as client:
                response = await client.post(
                    TOKEN_URL,
                    data={
                        "client_id": self._credentials.client_id,
                        "client_secret": self._credentials.client_secret,
                        "refresh_token": self._credentials.refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            if response.status_code != 200:
                # 400 invalid_grant: el permiso se revocó y hay que volver a autorizar.
                logger.warning("gmail_token_failed status=%d", response.status_code)
                raise GmailError(f"token HTTP {response.status_code}")
            data = response.json()
            self._token = data["access_token"]
            self._expires = time.monotonic() + int(data.get("expires_in", 3600)) - 60
            return self._token

    async def _get(self, path: str, params: Any = None) -> dict[str, Any]:
        token = await self._access_token()
        async with self._client() as client:
            response = await client.get(
                f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {token}"}
            )
        if response.status_code == 404:
            return {}
        if response.status_code >= 400:
            raise GmailError(f"HTTP {response.status_code}")
        return response.json()

    async def send(self, to: list[str], subject: str, body: str) -> str:
        message = EmailMessage()
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        token = await self._access_token()
        async with self._client() as client:
            response = await client.post(
                f"{API}/messages/send",
                json={"raw": raw},
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code == 403:
            raise GmailSinPermisoDeEnvio
        if response.status_code >= 400:
            raise GmailError(f"HTTP {response.status_code}")
        return str(response.json().get("id", ""))

    async def search(self, query: str, zone_name: str, limit: int) -> list[dict[str, Any]]:
        zone = ZoneInfo(zone_name)
        found = await self._get("messages", {"q": query, "maxResults": limit})
        ids = [item["id"] for item in found.get("messages") or [] if "id" in item][:limit]
        params = [
            ("format", "metadata"),
            ("metadataHeaders", "From"),
            ("metadataHeaders", "Subject"),
        ]
        messages = await asyncio.gather(*(self._get(f"messages/{i}", params) for i in ids))
        return [_summary(raw, zone) for raw in messages if raw]

    async def read(self, message_id: str, zone_name: str) -> dict[str, Any] | None:
        raw = await self._get(f"messages/{validate_message_id(message_id)}", {"format": "full"})
        if not raw:
            return None
        return {**_summary(raw, ZoneInfo(zone_name)), "texto": _body_text(raw.get("payload") or {})}


_client: Gmail | None = None
_client_lock = threading.Lock()


def get_gmail() -> Gmail:
    global _client
    with _client_lock:
        if _client is None:
            _client = Gmail(credentials_from_env())
        return _client


def set_gmail(client: Gmail | None) -> None:
    """Para pruebas: reemplaza el cliente compartido."""
    global _client
    with _client_lock:
        _client = client
