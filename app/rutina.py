"""Rutina: JARVIS aprende los lugares y horarios del Dr. Valles y le pregunta por su cuenta.

El despertador llama /tareas/avisos cada 10 minutos; al final de cada corrida se llama
Rutina.run, que decide por la hora qué toca:

- 22:00 o después, una vez al día: agrupa las ubicaciones de los últimos 60 días en
  lugares frecuentes (radio de 150 m), calcula en qué días y horas suele estar en cada
  uno, anota esos patrones en el expediente y detecta si dejó de ir a un lugar.
- Sábado de 19:00 a 21:30, si está en casa: pregunta a qué misa y a qué hora irá el
  domingo (una vez por sábado).
- De 19:00 a 21:30, si está en casa: como mucho una pregunta al día por iniciativa
  propia, por ejemplo qué es un lugar frecuente que todavía no tiene nombre.

Las preguntas se dicen por el mismo canal que los avisos de salida (correo que el iPhone
lee en voz alta) y se guardan en el historial de la conversación, así la respuesta del
Dr. Valles en /ask llega con su contexto.
"""

import hashlib
import logging
import math
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.expediente import normalized
from app.storage import Store

usage_logger = logging.getLogger("jarvis.usage")

RADIO_LUGAR = 150
EN_CASA_METROS = 300
RETENCION = timedelta(days=60)
MIN_PUNTOS = 5
MIN_DIAS = 3
YA_NO_VA = timedelta(days=21)
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
PREGUNTA_MISA = "Doctor, ¿a qué misa y a qué hora va a ir mañana?"
MARCA_PREGUNTA = "(JARVIS pregunta por iniciativa propia)"


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6_371_000 * 2 * math.asin(math.sqrt(h))


def cluster(points: list[dict[str, Any]], zone: ZoneInfo) -> list[dict[str, Any]]:
    """Agrupa puntos cercanos y describe cuándo suele estar en cada grupo."""
    groups: list[dict[str, Any]] = []
    for point in points:
        here = (float(point["lat"]), float(point["lon"]))
        when = datetime.fromisoformat(point["en"]).astimezone(zone)
        target = next(
            (g for g in groups if distance_m((g["lat"], g["lon"]), here) <= RADIO_LUGAR), None
        )
        if target is None:
            target = {"lat": here[0], "lon": here[1], "momentos": []}
            groups.append(target)
        target["momentos"].append(when)
        count = len(target["momentos"])
        # El centro se mueve al promedio, así un GPS que brinca no parte el lugar en dos.
        target["lat"] += (here[0] - target["lat"]) / count
        target["lon"] += (here[1] - target["lon"]) / count

    frequent = []
    for group in groups:
        moments = group.pop("momentos")
        days = {moment.date() for moment in moments}
        if len(moments) < MIN_PUNTOS or len(days) < MIN_DIAS:
            continue
        weekdays = Counter(moment.weekday() for moment in moments)
        hours = sorted(moment.hour for moment in moments)
        frequent.append(
            {
                **group,
                "puntos": len(moments),
                "dias": sorted(d for d, n in weekdays.items() if n >= max(2, len(days) // 7)),
                "desde": hours[len(hours) // 10],
                "hasta": hours[(len(hours) * 9) // 10],
                "noche": sum(1 for hour in hours if hour >= 22 or hour <= 7),
                "ultima": max(moments).isoformat(),
            }
        )
    return sorted(frequent, key=lambda g: -g["puntos"])


def describe_days(days: list[int]) -> str:
    if days == [0, 1, 2, 3, 4]:
        return "entre semana"
    if days == [5, 6]:
        return "los fines de semana"
    if len(days) == 7:
        return "todos los días"
    names = [DIAS[d] for d in days]
    if not names:
        return "algunos días"
    return "los " + (
        " y ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " y " + names[-1]
    )


def pattern_sentence(name: str, place: dict[str, Any]) -> str:
    return (
        f"Suele estar en {name} {describe_days(place['dias'])}, "
        f"de {place['desde']}:00 a {place['hasta'] + 1}:00"
    )


def match_named(place: dict[str, Any], named: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in named:
        if item.get("lat") is None:
            continue
        if distance_m((place["lat"], place["lon"]), (item["lat"], item["lon"])) <= RADIO_LUGAR * 2:
            return item
    return None


def home_of(named: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((p for p in named if normalized(p["nombre"]) in ("casa", "mi casa")), None)


class Rutina:
    def __init__(self, speak: Callable[[str], Awaitable[None]]) -> None:
        self.speak = speak

    async def run(self, store: Store, zone_name: str) -> dict[str, Any]:
        zone = ZoneInfo(zone_name)
        now = datetime.now(zone)
        today = now.date().isoformat()
        state = await run_in_threadpool(store.read_rutina) or {}
        profile = await run_in_threadpool(store.read_expediente) or {}
        named = [p for p in profile.get("lugares") or [] if p.get("lat") is not None]
        done: list[str] = []

        if now.hour >= 22 and state.get("aprendido_el") != today:
            await self._learn(store, zone, state, profile, named)
            state["aprendido_el"] = today
            done.append("aprendio")

        location = await run_in_threadpool(store.read_ubicacion)
        at_home = False
        home = home_of(named)
        if location and home:
            seen = datetime.fromisoformat(location["en"])
            at_home = (
                now - seen <= timedelta(hours=2)
                and distance_m(
                    (float(location["lat"]), float(location["lon"])), (home["lat"], home["lon"])
                )
                <= EN_CASA_METROS
            )
        evening = (19, 0) <= (now.hour, now.minute) <= (21, 30)

        if evening and at_home and now.weekday() == 5 and state.get("misa_el") != today:
            await self._ask(store, PREGUNTA_MISA)
            state["misa_el"] = today
            # Cuenta como la pregunta del día: nunca dos preguntas la misma tarde.
            state["pregunta_el"] = today
            done.append("misa")
        elif evening and at_home and state.get("pregunta_el") != today:
            question = self._next_question(state, named)
            if question:
                await self._ask(store, question["texto"])
                state["pregunta_el"] = today
                state["pregunta_pendiente"] = question
                done.append("pregunta")

        await run_in_threadpool(store.write_rutina, state)
        if done:
            usage_logger.info("rutina %s", " ".join(done))
        return {"rutina": done}

    async def _ask(self, store: Store, text: str) -> None:
        await self.speak(text)
        # Queda en la conversación para que la respuesta tenga contexto.
        await run_in_threadpool(store.append_turn, MARCA_PREGUNTA, text)

    async def _learn(
        self,
        store: Store,
        zone: ZoneInfo,
        state: dict[str, Any],
        profile: dict[str, Any],
        named: list[dict[str, Any]],
    ) -> None:
        log = await run_in_threadpool(store.read_ubicaciones) or {}
        cutoff = datetime.now(zone) - RETENCION
        points = [p for p in log.get("puntos") or [] if datetime.fromisoformat(p["en"]) >= cutoff]
        # Se borra lo de más de 60 días.
        await run_in_threadpool(store.write_ubicaciones, {"puntos": points})
        places = cluster(points, zone)
        unnamed, patterns, notes = [], [], []
        for place in places[:10]:
            match = match_named(place, named)
            if match is None:
                unnamed.append(place)
                continue
            patterns.append(pattern_sentence(match["nombre"], place))
            last = datetime.fromisoformat(place["ultima"])
            if datetime.now(zone) - last >= YA_NO_VA:
                notes.append(
                    f"Hace {(datetime.now(zone) - last).days} días que no va a {match['nombre']}"
                )
        # Los patrones aprendidos reemplazan a los de la noche anterior.
        facts = [f for f in profile.get("datos") or [] if f.get("origen") != "aprendido"]
        for text in patterns + notes:
            facts.append(
                {
                    "id": "a" + hashlib.sha256(text.encode()).hexdigest()[:7],
                    "categoria": "rutina",
                    "texto": text,
                    "origen": "aprendido",
                    "fecha": datetime.now(zone).date().isoformat(),
                }
            )
        await run_in_threadpool(
            store.write_expediente, {"datos": facts, "lugares": profile.get("lugares") or []}
        )
        state["sin_nombre"] = [
            {k: place[k] for k in ("lat", "lon", "dias", "desde", "hasta", "noche", "puntos")}
            for place in unnamed[:5]
        ]

    def _next_question(
        self, state: dict[str, Any], named: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        for place in state.get("sin_nombre") or []:
            if match_named(place, named) is not None:
                continue  # Ya tiene nombre desde la última vez que aprendió.
            if place.get("noche", 0) >= place.get("puntos", 1) // 2:
                text = "Doctor, veo que suele pasar las noches en el mismo lugar. ¿Es su casa?"
            else:
                when = (
                    f"{describe_days(place['dias'])} de {place['desde']}:00 "
                    f"a {place['hasta'] + 1}:00"
                )
                text = f"Doctor, veo que suele ir a un mismo lugar {when}. ¿Qué lugar es?"
            return {"texto": text, "lat": place["lat"], "lon": place["lon"]}
        return None
