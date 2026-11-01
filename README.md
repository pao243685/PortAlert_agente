# PortAlert · Agente

Programa que se instala en un equipo y lo vincula con una cuenta de PortAlert.

## Vincular
1. Inicia sesión en PortAlert y genera un token de vinculación (vence a los 10 minutos y sirve una sola vez).
2. En el equipo:
```bash
uv venv && uv pip install -r requirements.txt
uv run python portalert_agent.py enroll --server http://localhost:8001 --token TU_TOKEN [--name MI-PC]
```
La API key queda guardada en:
- Windows: `%APPDATA%\portalert\config.json`
- Linux/macOS: `~/.config/portalert/config.json` (permisos 0600)

Si defines `PORTALERT_CONFIG` con una ruta, el agente usa ese archivo en lugar del anterior; los instaladores lo usan para correr como servicio del sistema.