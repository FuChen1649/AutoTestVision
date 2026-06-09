import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5179,
    proxy: {
      "/api": {
        target: "http://localhost:8099",
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          proxy.on("error", (_err, _req, res) => {
            if (res && "writeHead" in res && !res.headersSent) {
              res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
              res.end(JSON.stringify({ detail: "offline" }));
            }
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            if (req.url?.includes("/stream")) {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["content-type"] = "text/event-stream";
            }
          });
        },
      },
    },
  },
});
