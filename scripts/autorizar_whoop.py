"""Autoriza a JARVIS a leer el WHOOP del Dr. Valles y guarda el token en Secret Manager.

Uso (en la Mac, desde la raíz del repo):

1. En developer-dashboard.whoop.com → app JARVIS, copia el Client Secret con el ícono
   del ojo (queda en el portapapeles; no lo pegues en ningún chat).
2. Corre:

    .venv/bin/python scripts/autorizar_whoop.py <CLIENT_ID> <PROYECTO> <CUENTA_DE_SERVICIO>

El script lee el secreto del portapapeles con pbpaste, lo borra del portapapeles,
abre el navegador para aceptar el permiso y manda el token por stdin a
`gcloud secrets`. Nunca se imprime ni se escribe en disco.
"""

import http.server
import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
# Debe coincidir con la Redirect URI registrada en el portal de WHOOP.
REDIRECT_URI = "http://localhost:8765/whoop"
PORT = 8765
SCOPES = (
    "offline",
    "read:recovery",
    "read:cycles",
    "read:sleep",
    "read:workout",
    "read:profile",
    "read:body_measurement",
)
SECRET = "JARVIS_WHOOP"


def read_clipboard_secret() -> str:
    value = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout.strip()
    if not value or " " in value or len(value) < 20:
        raise SystemExit("Copie primero el Client Secret de WHOOP (ícono del ojo) y repita.")
    # Se limpia el portapapeles para que el secreto no se quede ahí.
    subprocess.run(["pbcopy"], input="", text=True, check=True)
    return value


def receive_code(state: str) -> tuple[dict[str, str], threading.Event, http.server.HTTPServer]:
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (nombre impuesto por http.server)
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if parts.path != "/whoop" or query.get("state", [""])[0] != state:
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

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return result, done, server


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    client_id, project, service_account = sys.argv[1:]
    client_secret = read_clipboard_secret()

    # WHOOP exige un state de al menos 8 caracteres.
    state = secrets.token_urlsafe(16)
    result, done, server = receive_code(state)
    url = (
        AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "state": state,
            }
        )
    )
    print("Se abrió el navegador. Inicie sesión en WHOOP y acepte el permiso.")
    webbrowser.open(url)
    if not done.wait(timeout=300):
        server.shutdown()
        raise SystemExit("Pasaron 5 minutos sin respuesta; vuelva a correr el script.")
    server.shutdown()
    if result.get("error") or not result.get("code"):
        raise SystemExit(f"WHOOP no dio el permiso: {result.get('error') or 'sin código'}")

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise SystemExit(f"WHOOP rechazó el intercambio del código (HTTP {response.status_code}).")
    tokens = response.json()
    if not tokens.get("refresh_token"):
        raise SystemExit("WHOOP no devolvió refresh_token; revise que pidió el permiso offline.")
    payload = json.dumps(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens["refresh_token"],
        }
    ).encode()

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
