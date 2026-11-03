# Compilar el ejecutable

```bash
cd agent
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name portalert-agent portalert_agent.py
# resultado: dist/portalert-agent  (dist\portalert-agent.exe en Windows)
```
PyInstaller no compila de forma cruzada: el .exe se genera en Windows y el binario de Linux en Linux.

## Publicar para los instaladores
El backend sirve `instalar-<token>.sh` / `.ps1`, que descargan el binario desde las URLs que configures en el backend
(`AGENT_DOWNLOAD_URL_LINUX`, `AGENT_DOWNLOAD_URL_WINDOWS`, y opcionalmente `AGENT_SHA256_*`). Sube los binarios compilados
(p. ej. a GitHub Releases) y pon esas URLs en el `.env` del backend. El agente lee su configuración de
`PORTALERT_CONFIG` si está definida (los instaladores la usan para correr como servicio del sistema).
