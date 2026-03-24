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
// Un solo host activo a la vez (uso personal)
let hostSocketId   = null;
let viewerSocketId = null;

// ── Health ────────────────────────────────────────────────────────────────────
app.get("/health", (req, res) => {
  res.json({
    status:    "ok",
    host:      !!hostSocketId,
    viewer:    !!viewerSocketId,
    uptime:    Math.floor(process.uptime()),
  });
});

// ── Sockets ───────────────────────────────────────────────────────────────────
io.on("connection", (socket) => {
  console.log(`[conn] ${socket.id}`);

  // ── Host se registra ────────────────────────────────────────────────────────
  socket.on("host:register", () => {
    hostSocketId = socket.id;
    console.log(`[host] Registrado: ${socket.id}`);

    // Si ya hay viewer esperando, notificarle de inmediato
    if (viewerSocketId) {
      io.to(hostSocketId).emit("host:viewer-joined");
    }
  });

  // ── Viewer se conecta (sin PIN) ─────────────────────────────────────────────
  socket.on("viewer:join", () => {
    if (viewerSocketId && viewerSocketId !== socket.id) {
      return socket.emit("error", { message: "Ya hay una sesión activa." });
    }

    viewerSocketId = socket.id;

    if (!hostSocketId) {
      // Host no conectado aún — le avisamos cuando llegue
      socket.emit("viewer:waiting");
      console.log(`[viewer] Esperando host…`);
      return;
    }

    // Host disponible → arrancar
    io.to(hostSocketId).emit("host:viewer-joined");
    socket.emit("viewer:ready");
    console.log(`[viewer] Conectado: ${socket.id}`);
  });

  // ── WebRTC signaling ─────────────────────────────────────────────────────────
  socket.on("signal:offer", ({ offer }) => {
    if (viewerSocketId) io.to(viewerSocketId).emit("signal:offer", { offer });
  });

  socket.on("signal:answer", ({ answer }) => {
    if (hostSocketId) io.to(hostSocketId).emit("signal:answer", { answer });
  });

  socket.on("signal:ice", ({ candidate }) => {
    const isHost = socket.id === hostSocketId;
    const target = isHost ? viewerSocketId : hostSocketId;
    if (target) io.to(target).emit("signal:ice", { candidate });
  });

  // ── Input (viewer → host) ────────────────────────────────────────────────────
  socket.on("input:event", (data) => {
    if (socket.id === viewerSocketId && hostSocketId) {
      io.to(hostSocketId).emit("input:event", data);
    }
  });

  // ── Disconnect ───────────────────────────────────────────────────────────────
  socket.on("disconnect", () => {
    if (socket.id === hostSocketId) {
      hostSocketId = null;
      if (viewerSocketId) {
        io.to(viewerSocketId).emit("error", { message: "El host se desconectó." });
      }
      console.log("[host] Desconectado.");
    } else if (socket.id === viewerSocketId) {
      viewerSocketId = null;
      if (hostSocketId) io.to(hostSocketId).emit("host:viewer-left");
      console.log("[viewer] Desconectado.");
    }
  });
});

server.listen(PORT, () => console.log(`✅ Signaling server en puerto ${PORT}`));
