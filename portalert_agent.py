"""Agente de PortAlert.

Uso:
  portalert-agent enroll --server http://localhost:8001 --token <TOKEN> [--name MI-PC]
  portalert-agent run [--once] [--interval 60]
"""
import argparse
import hashlib
import json
import os
import platform
import socket
import stat
import sys
import time
from pathlib import Path

import httpx
import psutil

MAX_HASH_BYTES = 200 * 1024 * 1024
MAX_ELEMENTOS = 2000  


def config_path() -> Path:
    override = os.environ.get("PORTALERT_CONFIG")
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
        try:  # p. ej. "Ubuntu 24.04 LTS" en lugar de la version del kernel
            version = platform.freedesktop_os_release().get("PRETTY_NAME", version)
        except (OSError, AttributeError):
            pass
    elif family == "windows":
        version = f"Windows {platform.release()} ({platform.version()})"
    return family, version[:100]


#  enroll 
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


#  recolección 
def sha256_of(path: str | None) -> str | None:
    try:
        if not path or os.path.getsize(path) > MAX_HASH_BYTES:
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def collect() -> dict:
    ports, pids = [], set()
    try:
        conns = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        conns = []  # en macOS/Windows sin privilegios puede fallar
    for c in conns:
        is_tcp = c.type == socket.SOCK_STREAM
        if is_tcp and c.status != psutil.CONN_LISTEN:
            continue
        if not c.laddr or (not is_tcp and c.raddr):
            continue
        ports.append(
            {
                "port": c.laddr.port,
                "protocol": "tcp" if is_tcp else "udp",
                "bind_address": c.laddr.ip,
                "pid": c.pid,
            }
        )
        if c.pid:
            pids.add(c.pid)

    processes = []
    for pid in pids:
        try:
            p = psutil.Process(pid)
            exe = None
            try:
                exe = p.exe()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                pass
            deleted = bool(exe) and exe.endswith(" (deleted)")
            if deleted:
                exe = exe.removesuffix(" (deleted)")
            try:
                user = p.username()
            except psutil.AccessDenied:
                user = None
            processes.append(
                {
                    "pid": pid,
                    "name": p.name()[:255],
                    "exe_path": exe,
                    "username": user[:100] if user else None,
                    "sha256": None if deleted else sha256_of(exe),
                    "exe_deleted": deleted,
                }
            )
        except psutil.NoSuchProcess:
            continue
    return {"processes": processes[:MAX_ELEMENTOS], "ports": ports[:MAX_ELEMENTOS]}


# envío 
def send_report(cfg: dict) -> None:
    report = collect()
    r = httpx.post(
        f"{cfg['server']}/reports",
        json=report,
        headers={"X-API-Key": cfg["api_key"]},
        timeout=30,
    )
    if r.status_code == 401:
        sys.exit("La API key ya no es válida (¿borraste el dispositivo?). Vincula de nuevo.")
    r.raise_for_status()
    print(
        f"Reporte enviado: {len(report['ports'])} puertos, "
        f"{len(report['processes'])} procesos, score={r.json().get('score')}"
    )


def cmd_run(args) -> None:
    cfg = load_config()
    while True:
        try:
            send_report(cfg)
        except httpx.HTTPError as e:
            print(f"Error de red, reintento en el próximo ciclo: {e}", file=sys.stderr)
        if args.once:
            return
        time.sleep(args.interval)


def main() -> None:
    ap = argparse.ArgumentParser(prog="portalert-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll", help="vincula este equipo con tu cuenta")
    e.add_argument("--server", required=True)
    e.add_argument("--token", required=True)
    e.add_argument("--name")
    e.set_defaults(fn=cmd_enroll)

    r = sub.add_parser("run", help="envía reportes periódicos")
    r.add_argument("--once", action="store_true")
    r.add_argument("--interval", type=int, default=60)
    r.set_defaults(fn=cmd_run)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
