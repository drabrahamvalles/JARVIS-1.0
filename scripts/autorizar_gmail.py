"""Autoriza a JARVIS a leer y enviar desde el Gmail del Dr. Valles y guarda el token en
Secret Manager.

Uso (en la Mac, desde la raíz del repo):

    .venv/bin/python scripts/autorizar_gmail.py ~/Downloads/client_secret_XXXX.json \
        <PROYECTO> <CUENTA_DE_SERVICIO>

Abre el navegador, el Dr. Valles acepta los permisos (leer y enviar) y el token se
manda por stdin a `gcloud secrets`. Nunca se imprime ni se escribe en disco.
"""

import base64
import hashlib
import http.server
import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)
SECRET = "JARVIS_GMAIL"


def load_client(path: Path) -> dict[str, str]:
    data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    client = data.get("installed")
    if not client:
        raise SystemExit("El archivo debe ser de un cliente OAuth tipo «App de escritorio».")
    return {"client_id": client["client_id"], "client_secret": client["client_secret"]}


def receive_code(
    state: str,
) -> tuple[dict[str, str], str, threading.Event, http.server.HTTPServer]:
    """Levanta un servidor local de un solo uso en 127.0.0.1 para recibir el código."""
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (nombre impuesto por http.server)
            query = parse_qs(urlsplit(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result["code"] = query.get("code", [""])[0]
            result["error"] = query.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>Listo. Ya puede cerrar esta pestaña.</p>".encode())
            done.set()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return result, redirect_uri, done, server


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    client = load_client(Path(sys.argv[1]))
    project, service_account = sys.argv[2], sys.argv[3]

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    result, redirect_uri, done, server = receive_code(state)
    url = (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": client["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": challenge.decode().rstrip("="),
                "code_challenge_method": "S256",
            }
        )
    )
    print("Se abrió el navegador. Acepte los permisos de Gmail (leer y enviar).")
    webbrowser.open(url)
    if not done.wait(timeout=300):
        server.shutdown()
        raise SystemExit("Pasaron 5 minutos sin respuesta; vuelva a correr el script.")
    server.shutdown()
    if result.get("error") or not result.get("code"):
        raise SystemExit(f"Google no dio el permiso: {result.get('error') or 'sin código'}")

    response = httpx.post(
        TOKEN_URL,
        data={
            **client,
            "code": result["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise SystemExit(f"Google rechazó el intercambio del código (HTTP {response.status_code}).")
    tokens = response.json()
    granted = set(tokens.get("scope", "").split())
    if not set(SCOPES) <= granted:
        raise SystemExit("Faltó marcar un permiso de Gmail (leer o enviar); repita el proceso.")
    if not tokens.get("refresh_token"):
        raise SystemExit("Google no devolvió refresh_token; quite el acceso de JARVIS y repita.")
    payload = json.dumps({**client, "refresh_token": tokens["refresh_token"]}).encode()

    exists = (
        subprocess.run(
            ["gcloud", "secrets", "describe", SECRET, f"--project={project}"],
            capture_output=True,
        ).returncode
        == 0
    )
    command = (
        ["gcloud", "secrets", "versions", "add", SECRET]
        if exists
        else ["gcloud", "secrets", "create", SECRET, "--replication-policy=automatic"]
    )
    subprocess.run([*command, "--data-file=-", f"--project={project}"], input=payload, check=True)
    subprocess.run(
        [
            "gcloud",
            "secrets",
            "add-iam-policy-binding",
            SECRET,
            f"--member=serviceAccount:{service_account}",
            "--role=roles/secretmanager.secretAccessor",
            f"--project={project}",
            "--quiet",
        ],
        check=True,
        capture_output=True,
    )
    print(f"Token guardado en Secret Manager ({SECRET}). No se mostró en pantalla.")


if __name__ == "__main__":
    main()
