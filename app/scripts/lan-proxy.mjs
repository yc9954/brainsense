#!/usr/bin/env node
// Expose the loopback-only OpenMuse sample server (and the BrainSense FastAPI assets) to a phone
// on the same Wi-Fi. The sample workspace refuses HOST other than 127.0.0.1 and only allows the
// localhost origin for CORS (apps/server/src/config.ts), so this proxy:
//   - listens on all interfaces and forwards to 127.0.0.1:8787, streaming bodies both ways (SSE ok)
//   - forwards /assets/* (brain meshes) to the BrainSense server on 127.0.0.1:8000
//   - rewrites the browser's Origin to the allowed localhost one on the way in, and puts the real
//     origin back into Access-Control-Allow-Origin on the way out, so a phone browser at
//     http://<lan-ip>:8081 passes the server's origin check.
//   node scripts/lan-proxy.mjs            # 0.0.0.0:8788 -> 127.0.0.1:8787 (+ :8000 for /assets)
import http from "node:http";
import { networkInterfaces } from "node:os";

const LISTEN = Number(process.env.LISTEN ?? 8788);
const TARGET = Number(process.env.TARGET ?? 8787);
const BRAIN = Number(process.env.BRAIN ?? 8000);
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN ?? "http://localhost:8081";

const server = http.createServer((req, res) => {
  const realOrigin = req.headers.origin;
  const toBrain = (req.url ?? "").startsWith("/assets/");
  const port = toBrain ? BRAIN : TARGET;
  const headers = { ...req.headers, host: `127.0.0.1:${port}` };
  if (realOrigin && !toBrain) headers.origin = ALLOWED_ORIGIN;
  const upstream = http.request({ host: "127.0.0.1", port, method: req.method, path: req.url, headers }, (up) => {
    const out = { ...up.headers };
    if (realOrigin) {
      out["access-control-allow-origin"] = realOrigin;
      out.vary = "Origin";
      if (!out["access-control-allow-credentials"]) out["access-control-allow-credentials"] = "true";
    }
    res.writeHead(up.statusCode ?? 502, out);
    up.pipe(res);
  });
  upstream.on("error", (e) => {
    res.writeHead(502, { "content-type": "application/json", ...(realOrigin ? { "access-control-allow-origin": realOrigin } : {}) });
    res.end(JSON.stringify({ error: `proxy: ${e.message}` }));
  });
  req.pipe(upstream);
});
server.listen(LISTEN, "0.0.0.0", () => {
  const ips = Object.values(networkInterfaces())
    .flat()
    .filter((i) => i && i.family === "IPv4" && !i.internal)
    .map((i) => i.address);
  console.log(`OpenMuse LAN proxy: http://0.0.0.0:${LISTEN} -> http://127.0.0.1:${TARGET} (+ /assets -> :${BRAIN})`);
  for (const ip of ips) console.log(`  phone browser: http://${ip}:8081   (API auto-routes to http://${ip}:${LISTEN})`);
});
