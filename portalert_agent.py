"""Agente de PortAlert.

Uso:
  portalert-agent enroll --server http://localhost:8001 --token <TOKEN> [--name MI-PC]
  portalert-agent scan [--json]
"""
import argparse
import hashlib
import json
import os
import platform
import socket
import stat
import sys
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


# escaneo local 
def cmd_scan(args) -> None:
    """Muestra lo que el agente reportaría, sin enviarlo a ningún lado."""
    report = collect()
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(f"{len(report['ports'])} puertos en escucha, {len(report['processes'])} procesos:")
    for p in report["ports"]:
        print(f"  {p['protocol']}/{p['port']:<5} {p['bind_address']:<15} pid={p['pid']}")
    for p in report["processes"]:
        sha = (p["sha256"] or "sin hash")[:12]
        extra = " [binario borrado]" if p["exe_deleted"] else ""
        print(f"  pid={p['pid']:<7} {p['name']:<24} {sha}{extra}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="portalert-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll", help="vincula este equipo con tu cuenta")
    e.add_argument("--server", required=True)
    e.add_argument("--token", required=True)
    e.add_argument("--name")
    e.set_defaults(fn=cmd_enroll)

    s = sub.add_parser("scan", help="muestra los puertos y procesos detectados, sin enviarlos")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()