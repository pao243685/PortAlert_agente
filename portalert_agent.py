"""Agente de PortAlert.

Uso:
  portalert-agent enroll --server http://localhost:8001 --token <TOKEN> [--name MI-PC]
"""
import argparse
import json
import os
import platform
import socket
import stat
import sys
from pathlib import Path

import httpx


def config_path() -> Path:
    override = os.environ.get("PORTALERT_CONFIG")  # lo usan los instaladores (servicio del sistema)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "portalert" / "config.json"


def save_config(cfg: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg))
    if sys.platform != "win32":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600: contiene la API key
    return path


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        sys.exit("El agente no está vinculado. Ejecuta primero: portalert-agent enroll ...")
    return json.loads(path.read_text())


def os_info() -> tuple[str, str]:
    family = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    version = f"{platform.system()} {platform.release()}"
    if family == "linux":
        try:  # p. ej. "Ubuntu 24.04 LTS" en lugar de la versión del kernel
            version = platform.freedesktop_os_release().get("PRETTY_NAME", version)
        except (OSError, AttributeError):
            pass
    elif family == "windows":
        version = f"Windows {platform.release()} ({platform.version()})"
    return family, version[:100]


# enroll 
def cmd_enroll(args) -> None:
    family, version = os_info()
    r = httpx.post(
        f"{args.server.rstrip('/')}/hosts/enroll",
        json={
            "enroll_token": args.token,
            "name": args.name or socket.gethostname(),
            "os_family": family,
            "os_version": version,
        },
        timeout=15,
    )
    if r.status_code != 201:
        sys.exit(f"No se pudo vincular ({r.status_code}): {r.json().get('detail', r.text)}")
    path = save_config({"server": args.server.rstrip("/"), "api_key": r.json()["api_key"]})
    print(f"Dispositivo vinculado. Configuración guardada en {path}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="portalert-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll", help="vincula este equipo con tu cuenta")
    e.add_argument("--server", required=True)
    e.add_argument("--token", required=True)
    e.add_argument("--name")
    e.set_defaults(fn=cmd_enroll)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()