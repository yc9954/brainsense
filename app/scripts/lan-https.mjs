#!/usr/bin/env node
// One HTTPS origin for the phone: https://<lan-ip>:8443
//   /api/*, /_copilotkit*  -> OpenMuse sample server 127.0.0.1:8787 (loopback-only; Origin rewritten
//                            to the allowed localhost one, real origin put back in the CORS reply)
//   /assets/*              -> BrainSense FastAPI 127.0.0.1:8000 (brain meshes)
//   everything else (+ws)  -> Metro web dev server 127.0.0.1:8081 (the Expo web build)
// Why: iPhone Safari only opens the live camera (getUserMedia) on a secure context, and the sample
// server cannot bind to the LAN itself. A self-signed cert is generated on first run; on the phone
// accept the warning once (Show details → visit this website).
//   node scripts/lan-https.mjs            # LISTEN=8443 METRO=8081 TARGET=8787 BRAIN=8000
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { networkInterfaces } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const LISTEN = Number(process.env.LISTEN ?? 8443);
const METRO = Number(process.env.METRO ?? 8081);
const TARGET = Number(process.env.TARGET ?? 8787);
const BRAIN = Number(process.env.BRAIN ?? 8000);
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN ?? `http://localhost:${METRO}`;

const ips = Object.values(networkInterfaces())
  .flat()
  .filter((i) => i && i.family === "IPv4" && !i.internal)
  .map((i) => i.address);

const certDir = join(dirname(fileURLToPath(import.meta.url)), ".certs");
const keyPath = join(certDir, "lan.key");
const crtPath = join(certDir, "lan.crt");
if (!existsSync(keyPath) || !existsSync(crtPath)) {
  mkdirSync(certDir, { recursive: true });
  const san = ["DNS:localhost", "IP:127.0.0.1", ...ips.map((ip) => `IP:${ip}`)].join(",");
  execFileSync("openssl", [
    "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "30",
    "-keyout", keyPath, "-out", crtPath,
    "-subj", "/CN=BrainSense LAN",
    "-addext", `subjectAltName=${san}`,
  ]);
  console.log(`generated self-signed cert for ${san}`);
}

function route(url) {
  if (url.startsWith("/api/") || url.startsWith("/_copilotkit")) return { port: TARGET, rewriteOrigin: true };
  if (url.startsWith("/assets/")) return { port: BRAIN, rewriteOrigin: false };
  return { port: METRO, rewriteOrigin: false };
}

const server = https.createServer({ key: readFileSync(keyPath), cert: readFileSync(crtPath) }, (req, res) => {
  const { port, rewriteOrigin } = route(req.url ?? "/");
  const realOrigin = req.headers.origin;
  const headers = { ...req.headers, host: `127.0.0.1:${port}` };
  if (realOrigin && rewriteOrigin) headers.origin = ALLOWED_ORIGIN;
  const upstream = http.request({ host: "127.0.0.1", port, method: req.method, path: req.url, headers }, (up) => {
    const out = { ...up.headers };
    if (realOrigin && rewriteOrigin) {
      out["access-control-allow-origin"] = realOrigin;
      out.vary = "Origin";
      if (!out["access-control-allow-credentials"]) out["access-control-allow-credentials"] = "true";
    }
    res.writeHead(up.statusCode ?? 502, out);
    up.pipe(res);
  });
  upstream.on("error", (e) => {
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: `proxy: ${e.message}` }));
  });
  req.pipe(upstream);
});

// WebSocket upgrades (Metro HMR, Expo dev tools) go to Metro as raw TCP
server.on("upgrade", (req, socket, head) => {
  const { port } = route(req.url ?? "/");
  const up = net.connect(port, "127.0.0.1", () => {
    const lines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
    for (const [k, v] of Object.entries(req.headers)) lines.push(`${k}: ${Array.isArray(v) ? v.join(", ") : v}`);
    up.write(`${lines.join("\r\n")}\r\n\r\n`);
    if (head.length) up.write(head);
    socket.pipe(up).pipe(socket);
  });
  up.on("error", () => socket.destroy());
  socket.on("error", () => up.destroy());
});

server.listen(LISTEN, "0.0.0.0", () => {
  console.log(`BrainSense HTTPS proxy on :${LISTEN}  →  Metro :${METRO}, OpenMuse :${TARGET}, BrainSense :${BRAIN}`);
  for (const ip of ips) console.log(`  phone: https://${ip}:${LISTEN}   (accept the certificate warning once)`);
});
