import uvicorn

from app.settings import runtime_environment


def main() -> None:
    env = runtime_environment()
    raw_port = env.get("PORT") or "8000"
    try:
        port = int(raw_port)
    except ValueError:
        raise SystemExit("PORT debe ser un número entero") from None
    if not 1 <= port <= 65535:
        raise SystemExit("PORT debe estar entre 1 y 65535")
    # Los proveedores asignan PORT. Sin PORT, escuchar solo en este Mac.
    default_host = "0.0.0.0" if env.get("PORT") else "127.0.0.1"
    uvicorn.run(
        "app.main:app",
        host=env.get("HOST") or default_host,
        port=port,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
