"""Cliente mínimo de Google Calendar para la cuenta de servicio de Cloud Run.

El Dr. Valles comparte sus calendarios con el correo de la cuenta de servicio.
Así no hacen falta tokens OAuth personales: la cuenta de servicio usa sus
credenciales de Cloud Run y solo ve los calendarios que él compartió.
"""

import asyncio
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

API = "https://www.googleapis.com/calendar/v3"
SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
MAX_EVENTOS = 25
MAX_DIAS = 31
_EVENT_ID = re.compile(r"[a-zA-Z0-9_\-@.]{1,1024}")


class CalendarioNoConfigurado(Exception):
    """No hay calendarios compartidos configurados en JARVIS_CALENDARIOS."""


class CalendarioError(Exception):
    """Google Calendar no respondió como se esperaba."""


@dataclass(frozen=True)
class Evento:
    id: str
    titulo: str
    inicio: str
    fin: str
    todo_el_dia: bool
    lugar: str | None
    calendario: int

    def para_modelo(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "titulo": self.titulo,
            "inicio": self.inicio,
            "fin": self.fin,
            "todo_el_dia": self.todo_el_dia,
            "lugar": self.lugar,
        }


def calendar_ids_from_env(env: dict[str, str] | None = None) -> tuple[str, ...]:
    raw = (env if env is not None else os.environ).get("JARVIS_CALENDARIOS", "")
    ids = tuple(part.strip() for part in raw.split(",") if part.strip())
    if any(len(value) > 320 or "/" in value for value in ids):
        raise ValueError("JARVIS_CALENDARIOS contiene un identificador inválido")
    return ids


def parse_local_day(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("Se requiere una fecha AAAA-MM-DD") from exc


def encode_event_id(calendar_index: int, event_id: str) -> str:
    return f"{calendar_index}:{event_id}"


def decode_event_id(value: str) -> tuple[int, str]:
    index, separator, event_id = value.strip().partition(":")
    if not separator or not index.isdigit() or _EVENT_ID.fullmatch(event_id) is None:
        raise ValueError("Identificador de evento inválido")
    return int(index), event_id


def _parse_event(raw: dict[str, Any], calendar_index: int, zone: ZoneInfo) -> Evento | None:
    if raw.get("status") == "cancelled" or not isinstance(raw.get("id"), str):
        return None
    start = raw.get("start") or {}
    end = raw.get("end") or {}
    if "dateTime" in start:
        begins = datetime.fromisoformat(start["dateTime"]).astimezone(zone)
        ends = datetime.fromisoformat(end.get("dateTime", start["dateTime"])).astimezone(zone)
        start_text = begins.strftime("%Y-%m-%d %H:%M")
        end_text = ends.strftime("%Y-%m-%d %H:%M")
        all_day = False
    elif "date" in start:
        start_text = start["date"]
        # Google marca el fin de un evento de día completo como el día siguiente (exclusivo).
        last_day = date.fromisoformat(end.get("date", start["date"])) - timedelta(days=1)
        end_text = max(last_day, date.fromisoformat(start["date"])).isoformat()
        all_day = True
    else:
        return None
    title = str(raw.get("summary") or "Sin título").strip()[:300]
    place = raw.get("location")
    return Evento(
        id=encode_event_id(calendar_index, raw["id"]),
        titulo=title,
        inicio=start_text,
        fin=end_text,
        todo_el_dia=all_day,
        lugar=str(place).strip()[:300] if place else None,
        calendario=calendar_index,
    )


class GoogleCalendar:
    def __init__(
        self,
        calendar_ids: tuple[str, ...],
        *,
        credentials: Any = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not calendar_ids:
            raise CalendarioNoConfigurado
        self.calendar_ids = calendar_ids
        self._credentials = credentials
        self._transport = transport
        self._lock = threading.Lock()

    def _token(self) -> str:
        with self._lock:
            if self._credentials is None:
                import google.auth

                self._credentials, _ = google.auth.default(scopes=list(SCOPES))
            if not self._credentials.valid:
                from google.auth.transport.requests import Request

                self._credentials.refresh(Request())
            return self._credentials.token

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        token = await run_in_threadpool(self._token)
        timeout = httpx.Timeout(8.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            response = await client.request(
                method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        if response.status_code >= 400 and response.status_code not in (404, 410):
            raise CalendarioError(f"HTTP {response.status_code}")
        return response

    def _events_url(self, index: int, event_id: str | None = None) -> str:
        calendar = quote(self.calendar_ids[index], safe="")
        url = f"{API}/calendars/{calendar}/events"
        return url if event_id is None else f"{url}/{quote(event_id, safe='')}"

    async def list_events(
        self, first_day: date, last_day: date, zone_name: str, text: str | None = None
    ) -> list[Evento]:
        zone = ZoneInfo(zone_name)
        time_min = datetime.combine(first_day, time.min, zone).isoformat()
        time_max = datetime.combine(last_day + timedelta(days=1), time.min, zone).isoformat()
        params: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": MAX_EVENTOS,
            "timeZone": zone_name,
        }
        if text:
            params["q"] = text

        async def one(index: int) -> list[Evento]:
            response = await self._request("GET", self._events_url(index), params=params)
            if response.status_code in (404, 410):
                # El calendario dejó de estar compartido con la cuenta de servicio.
                logger.warning("calendar_not_shared index=%d", index)
                return []
            items = response.json().get("items", [])
            return [e for e in (_parse_event(item, index, zone) for item in items) if e]

        groups = await asyncio.gather(*(one(index) for index in range(len(self.calendar_ids))))
        events = [event for group in groups for event in group]
        # Un mismo evento compartido entre dos calendarios aparece dos veces.
        unique: dict[tuple[str, str, str], Evento] = {}
        for event in events:
            unique.setdefault((event.titulo, event.inicio, event.fin), event)
        return sorted(unique.values(), key=lambda event: event.inicio)[:MAX_EVENTOS]

    async def get_event(self, event_id: str, zone_name: str) -> Evento | None:
        index, raw_id = decode_event_id(event_id)
        if index >= len(self.calendar_ids):
            return None
        response = await self._request("GET", self._events_url(index, raw_id))
        if response.status_code in (404, 410):
            return None
        return _parse_event(response.json(), index, ZoneInfo(zone_name))

    async def create_event(
        self,
        title: str,
        start: datetime | date,
        end: datetime | date,
        zone_name: str,
        location: str | None = None,
    ) -> Evento:
        if isinstance(start, datetime):
            body: dict[str, Any] = {
                "start": {"dateTime": start.isoformat(), "timeZone": zone_name},
                "end": {"dateTime": end.isoformat(), "timeZone": zone_name},
            }
        else:
            body = {"start": {"date": start.isoformat()}, "end": {"date": end.isoformat()}}
        body["summary"] = title
        if location:
            body["location"] = location
        # Se crea en el primer calendario configurado; sendUpdates=none no invita a nadie.
        response = await self._request(
            "POST", self._events_url(0), params={"sendUpdates": "none"}, json=body
        )
        if response.status_code >= 300:
            raise CalendarioError(f"HTTP {response.status_code}")
        event = _parse_event(response.json(), 0, ZoneInfo(zone_name))
        if event is None:
            raise CalendarioError("Respuesta sin evento")
        return event

    async def delete_event(self, event_id: str) -> bool:
        index, raw_id = decode_event_id(event_id)
        if index >= len(self.calendar_ids):
            return False
        # sendUpdates=none: nunca enviar correos a invitados en nombre del usuario.
        response = await self._request(
            "DELETE", self._events_url(index, raw_id), params={"sendUpdates": "none"}
        )
        return response.status_code < 300


_client: GoogleCalendar | None = None
_client_lock = threading.Lock()


def get_calendar() -> GoogleCalendar:
    global _client
    with _client_lock:
        if _client is None:
            _client = GoogleCalendar(calendar_ids_from_env())
        return _client


def set_calendar(client: GoogleCalendar | None) -> None:
    """Para pruebas: reemplaza el cliente compartido."""
    global _client
    with _client_lock:
        _client = client
