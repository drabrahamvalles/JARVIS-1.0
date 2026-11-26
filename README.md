# JARVIS

In development since October 2026.

JARVIS is a personal voice assistant I use on my iPhone. I'm a physician preparing for the USMLE and for research in the US.
I built JARVIS to run my day by voice: briefings, calendar, travel and study. The server runs on FastAPI and uses the OpenAI API.

## What it does today

- Answers spoken questions and can check the time and weather.
- Reads a morning briefing with the weather, calendar events, and reminders when I turn off my alarm.
- Turns screenshots, including flight itineraries, into calendar events or reminders.
- Chooses a model based on the request and logs estimated cost and latency.

The Apple Shortcuts run on the iPhone. See the [technical notes](docs/notas-tecnicas.md) for the API and how the briefing and screenshot capture work.

## Run on a Mac

For a fresh setup with Python 3.15, run these commands from the repository root:

```sh
python3.15 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

Set `OPENAI_API_KEY` and `JARVIS_TOKEN` in `.env`. Generate a separate token for JARVIS with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.

If `.venv` already exists, activate it and start the server:

```sh
source .venv/bin/activate
python -m app
```

Open [the local API docs](http://127.0.0.1:8000/docs). Use `GET /health` to check that the server is running. The other endpoints require `Authorization: Bearer <JARVIS_TOKEN>`.

## Deploy to Cloud Run

Follow the [Cloud Run deployment guide](infra/cloud-run/README.md) and see [infra/](infra/) for the scheduler and budget.

Built with the help of AI coding tools.
