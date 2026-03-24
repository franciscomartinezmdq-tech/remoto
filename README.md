# Remote Desktop — Signaling Server

Servidor de señalización WebRTC para el sistema de acceso remoto.  
No toca video ni audio — solo coordina la conexión entre host y viewer.

## Stack
- Node.js + Express
- Socket.io 4.x

## Eventos Socket.io

| Evento | Dirección | Descripción |
|---|---|---|
| `host:register` | Client → Server | Host pide un PIN |
| `host:pin` | Server → Host | Devuelve el PIN generado |
| `host:viewer-joined` | Server → Host | Un viewer se conectó |
| `host:viewer-left` | Server → Host | El viewer se desconectó |
| `viewer:join` | Client → Server | Viewer ingresa un PIN |
| `viewer:ready` | Server → Viewer | PIN válido, listo para WebRTC |
| `signal:offer` | Host → Server → Viewer | SDP offer WebRTC |
| `signal:answer` | Viewer → Server → Host | SDP answer WebRTC |
| `signal:ice` | Cualquiera → peer | ICE candidate |
| `input:event` | Viewer → Server → Host | Mouse / teclado |
| `error` | Server → Client | Error con mensaje |

## Deploy en Railway

```bash
# 1. Crear repo y subir
git init
git add .
git commit -m "feat: signaling server"

# 2. En Railway: New Project → Deploy from GitHub repo
# 3. Variables de entorno (opcionales):
#    PORT         → Railway lo setea automáticamente
#    VIEWER_ORIGIN → URL del viewer en producción (ej: https://mi-viewer.com)
```

## Health check

```
GET /health
→ { status: "ok", rooms: 2, uptime: 3600 }
```

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `PORT` | 3000 | Railway lo setea solo |
| `VIEWER_ORIGIN` | `*` | Restringir CORS en producción |
